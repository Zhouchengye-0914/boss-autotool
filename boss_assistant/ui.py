from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .config import _merge_config, load_config
from .matching import recommend_titles
from .persistence import ProgressStore, load_tasks
from .scanner import save_tasks
from .talent_data import ChatDatabase, CommunicationsDatabase, JobsDatabase, parse_job_taxonomy
from .workflow import WorkflowStateStore

try:
    import msvcrt
except ImportError:  # pragma: no cover - 当前项目运行于 Windows
    msvcrt = None


ACTION_LABELS = {
    "browser": "检查 Chrome 登录", "profile": "同步在线简历", "init-workers": "初始化实例登录",
    "scan": "搜索岗位", "communicate": "沟通岗位", "check": "检查 HR 回复",
    "resume": "检查并匹配简历", "watch": "持续监听回复", "full": "完整流程",
}


class JobController:
    def __init__(self, root: Path, config_path: Path):
        self.root, self.config_path = root, config_path
        self.lock = threading.RLock()
        self.running = self.stop_requested = self.abort_requested = False
        self.active_actions: set[str] = set()
        self.stop_actions: set[str] = set()
        self.stage = "空闲"
        self.logs: deque[str] = deque(maxlen=500)
        self.processes: dict[str, subprocess.Popen[str]] = {}
        self.process: subprocess.Popen[str] | None = None
        self.config_lock = threading.Lock()
        self.last_data_error = ""
        self.jobs_db: JobsDatabase | None = None
        self.chat_db: ChatDatabase | None = None
        self.communications_db: CommunicationsDatabase | None = None
        self.taxonomy = []
        self.workflow_dir = root / "data" / "workflows"
        self.workflows = {action: WorkflowStateStore(self.workflow_dir / f"{action}.json") for action in ACTION_LABELS}
        for store in self.workflows.values():
            store.load(recover_interrupted=True)
        try:
            config = load_config(config_path)
            self.jobs_db = JobsDatabase(config.storage.jobs_database_path); self.jobs_db.initialize()
            self.chat_db = ChatDatabase(config.storage.chat_database_path); self.chat_db.initialize()
            self.chat_db.migrate_legacy(config.storage.database_path)
            self.communications_db = CommunicationsDatabase(config.storage.communications_database_path)
            self.communications_db.initialize()
            if config.search.output_file.exists():
                self.jobs_db.backfill_tasks(load_tasks(config.search.output_file),
                                            config.search.output_file)
            for instance_dir in (root / "data" / "instances").glob("*"):
                self.communications_db.migrate_from(instance_dir / "communications.db")
                self.chat_db.migrate_legacy(instance_dir / "boss_assistant.db")
            taxonomy_path = root / "data" / "job.md"
            if taxonomy_path.exists():
                self.taxonomy = parse_job_taxonomy(taxonomy_path)
        except Exception as exc:
            self.last_data_error = f"数据初始化失败：{exc}"
            self.log(self.last_data_error)

    def log(self, message: str) -> None:
        with self.lock:
            self.logs.append(f"[{time.strftime('%H:%M:%S')}] {message.rstrip()}")

    def _combined_progress(self, config: Any) -> tuple[set[str], int]:
        paths = [config.scheduler.progress_file, *(self.root / "data" / "instances").glob("*/progress.json")]
        terminal: set[str] = set(); success = 0
        for path in paths:
            store = ProgressStore(path)
            try: store.load()
            except Exception as exc:
                self.log(f"忽略无法读取的断点 {path}: {exc}"); continue
            success += store.success_count_today()
            terminal.update(k for k, v in store.data["tasks"].items() if v.get("status") in {"success", "skipped"})
        return terminal, success

    def state(self) -> dict[str, Any]:
        config = load_config(self.config_path)
        tasks = load_tasks(config.search.output_file) if config.search.output_file.exists() else []
        terminal, success = self._combined_progress(config)
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        workers = int((raw.get("ui") or {}).get("parallel_workers", 2))
        names = {x.key: x.display_name for x in config.resume.options}
        suggestions: list[str] = []; alerts = 0
        try:
            profile = self.jobs_db.latest_profile() if self.jobs_db else None
            if profile and self.taxonomy:
                suggestions = recommend_titles(profile, self.taxonomy, config.search.recommendation_limit)
            alerts = len(self.chat_db.pending_interview_alerts()) if self.chat_db else 0
        except Exception as exc:
            message = f"数据概览读取失败：{exc}"
            if message != self.last_data_error:
                self.log(message)
                self.last_data_error = message
        else:
            self.last_data_error = ""
        recoveries = [state for state in (store.load() for store in self.workflows.values()) if state.resumable]
        recovery = recoveries[0] if recoveries else None
        with self.lock:
            active_actions = sorted(self.active_actions)
            logs = list(self.logs)
            stage = self.stage
        return {
            "running": bool(active_actions), "active_actions": active_actions,
            "stage": stage, "logs": logs, "total": len(tasks),
            "pending": sum(t.task_id not in terminal for t in tasks), "success": success,
            "quota": max(0, config.scheduler.daily_success_limit - success), "interview_alerts": alerts,
            "recovery": {"resumable": bool(recoveries), "action": recovery.action if recovery else "",
                         "phase": recovery.phase if recovery else "idle",
                         "label": "、".join(ACTION_LABELS.get(x.action, x.action) for x in recoveries)},
            "paths": {"岗位库": str(config.storage.jobs_database_path), "沟通库": str(config.storage.communications_database_path),
                      "聊天库": str(config.storage.chat_database_path), "工作流断点": str(self.workflow_dir),
                      "搜索断点": str(self.root / 'data' / 'scan_checkpoint.json')},
            "config": {"keywords": list(config.search.keywords), "max_pages": config.search.max_pages_per_keyword,
                       "workers": workers, "min_salary": config.search.min_salary_k, "greeting": config.search.greeting,
                       "exclude": list(config.search.exclude_title_keywords), "blacklist": list(config.search.company_blacklist),
                       "resume_general": names.get("general", ""), "resume_ai": names.get("ai", ""),
                       "resume_data": names.get("data", ""), "deepseek_enabled": config.resume.deepseek.enabled,
                       "preferences": config.resume.conversation_preferences, "suggestions": suggestions},
            "greeting_previews": [
                {"job": t.job_title or t.job_id, "company": t.company, "greeting": t.greeting,
                 "personalized": t.greeting != config.search.greeting}
                for t in tasks[:8]
            ],
            "matching": {"method": "本地可解释评分", "threshold": config.search.match_threshold,
                         "deepseek_role": "通过阈值后生成个性化招呼语；简历选择冲突时辅助判断"},
        }

    def start(self, action: str) -> None:
        if action not in ACTION_LABELS: raise ValueError("未知操作")
        with self.lock:
            if action in self.active_actions: raise RuntimeError(f"{ACTION_LABELS[action]} 已经在运行")
            if "full" in self.active_actions or (action == "full" and self.active_actions):
                raise RuntimeError("完整流程为独占模式，请先停止其他模块")
            groups = ({"browser", "profile", "scan", "check", "resume", "watch"},
                      {"init-workers", "communicate"})
            conflict = next((running for group in groups if action in group
                             for running in self.active_actions if running in group), "")
            if conflict:
                raise RuntimeError(f"{ACTION_LABELS[conflict]} 正在占用同一功能模块")
            self.active_actions.add(action)
            self.running = True; self.stop_requested = self.abort_requested = False
            self.stop_actions.discard(action)
        self.workflows[action].update(action, "scanning" if action in {"scan", "full"} else "communicating" if action == "communicate" else "monitoring" if action == "watch" else "running", resumable=True)
        threading.Thread(target=self._worker, args=(action,), daemon=True).start()

    def resume(self) -> None:
        states = [store.load() for store in self.workflows.values()]
        actions = [state.action for state in states if state.resumable and state.action]
        if not actions: raise RuntimeError("当前没有可恢复任务")
        if "full" in actions:
            self.start("full")
            return
        for action in actions:
            if action not in self.active_actions:
                self.start(action)

    def stop(self, action: str = "") -> None:
        with self.lock:
            self.stop_requested = True
            targets = {action} if action else set(self.active_actions)
            self.stop_actions.update(targets & self.active_actions)
        label = ACTION_LABELS.get(action, "所有运行模块")
        self.log(f"已请求安全停止{label}；当前步骤结束后保留断点。")

    def abort(self, action: str = "") -> None:
        with self.lock:
            self.stop_requested = self.abort_requested = True
            targets = {action} if action else set(self.active_actions)
            self.stop_actions.update(targets & self.active_actions)
            prefixes = {"communicate": "communicate-", "init-workers": "init-", "watch": "watch-"}
            processes = [process for key, process in self.processes.items()
                         if not action or key == action or key.startswith(prefixes.get(action, action + "-"))]
            if not action and self.process is not None and self.process not in processes:
                processes.append(self.process)
        for process in processes:
            if process.poll() is None: process.terminate()
        self.log(f"已立即停止{ACTION_LABELS.get(action, '所有运行模块')}；已完成断点均保留。")

    def _stopped(self, action: str) -> bool:
        with self.lock:
            return action in self.stop_actions

    def _command(self, args: list[str], label: str, key: str = "main") -> bool:
        with self.lock: self.stage = label
        self.log(f"开始：{label}")
        env = os.environ.copy(); env["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen([sys.executable, str(self.root / "启动.py"), *args], cwd=self.root,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   encoding="utf-8", errors="replace", env=env)
        with self.lock: self.processes[key] = process; self.process = process
        assert process.stdout
        for line in process.stdout: self.log(line)
        code = process.wait()
        with self.lock:
            self.processes.pop(key, None)
            if self.process is process: self.process = None
        self.log(f"{label}结束，退出码 {code}")
        return code == 0

    def _worker_count(self) -> int:
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        return max(1, min(4, int((raw.get("ui") or {}).get("parallel_workers", 2))))

    def _parallel(self, browser_only: bool = False) -> bool:
        count = self._worker_count(); jobs: list[tuple[str, list[str], str]] = []
        if browser_only:
            for i in range(count):
                name = f"worker-{i+1:02d}"; jobs.append((name, ["browser-check", "--instance", name, "--port-offset", str(i+1), "--worker-index", str(i), "--worker-count", str(count)], f"[{name}] 初始化登录"))
        else:
            config = load_config(self.config_path)
            if not config.search.output_file.exists(): raise RuntimeError("没有搜索结果，请先搜索岗位")
            tasks = load_tasks(config.search.output_file); terminal, _ = self._combined_progress(config)
            parts = [[] for _ in range(count)]
            for task in tasks:
                if task.task_id not in terminal: parts[sum(task.task_id.encode()) % count].append(task)
            for i, part in enumerate(parts):
                if not part: continue
                name = f"worker-{i+1:02d}"; path = self.root / "data" / "instances" / name / "tasks.json"; save_tasks(path, part)
                jobs.append((name, ["run", "--tasks", str(path), "--instance", name, "--port-offset", str(i+1), "--worker-index", str(i), "--worker-count", str(count)], f"[{name}] 串行沟通"))
        results: dict[str, bool] = {}
        prefix = "init" if browser_only else "communicate"
        threads = [threading.Thread(target=lambda n=n,a=a,l=l: results.update({n:self._command(a,l,f"{prefix}-{n}")}), daemon=True) for n,a,l in jobs]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        return all(results.values())

    def _worker(self, action: str) -> None:
        ok = True; error = ""
        try:
            if action == "init-workers": ok = self._parallel(True)
            else:
                first = {"browser":(["browser-check"],"检查 Chrome 登录"), "profile":(["profile-sync"],"同步在线简历"),
                         "scan":(["scan"],"搜索岗位"), "check":(["chat-check"],"检查 HR 回复"),
                         "resume":(["chat-check","--send-resume"],"检查并匹配简历"), "full":(["scan"],"搜索岗位")}.get(action)
                if first: ok = self._command(*first, action)
                if ok and action in {"communicate","full"} and not self._stopped(action):
                    self.workflows[action].update(action, "communicating", resumable=True); ok = self._parallel()
                if ok and action in {"watch","full"} and not self._stopped(action):
                    self.workflows[action].update(action, "monitoring", resumable=True)
                    while not self._stopped(action):
                        self._command(["chat-check","--send-resume"], "检查回复并匹配简历", f"{action}-chat")
                        delay = random.randint(60,300); self.stage = f"等待下次检查（约 {delay//60} 分钟）"
                        for _ in range(delay):
                            if self._stopped(action): break
                            time.sleep(1)
        except Exception as exc:
            ok = False; error = f"{type(exc).__name__}: {exc}"; self.log(f"控制台异常：{error}")
        finally:
            interrupted = self._stopped(action) or not ok
            self.workflows[action].update(action, "interrupted" if interrupted else "completed", error=error, resumable=interrupted)
            with self.lock:
                self.active_actions.discard(action)
                self.stop_actions.discard(action)
                self.running = bool(self.active_actions)
                self.stage = ("运行中：" + "、".join(ACTION_LABELS[x] for x in sorted(self.active_actions))) if self.active_actions else ("已停止，可继续" if interrupted else "已完成")


def _save_config(path: Path, payload: dict[str, Any], output_path: Path | None = None) -> None:
    textual_values = json.dumps(payload, ensure_ascii=False)
    if "???" in textual_values:
        raise ValueError("请求中的中文编码已损坏，配置未保存；请刷新页面后重试")
    target = output_path or path
    source = target if target.exists() else path
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}; search = raw.setdefault("search", {})
    keywords = payload.get("keywords", [])
    if not isinstance(keywords, list): raise ValueError("搜索关键词格式错误")
    pages, salary, workers = int(payload.get("max_pages",0)), int(payload.get("min_salary",0)), int(payload.get("workers",0))
    if not 1 <= pages <= 50 or not 0 <= salary <= 100 or not 1 <= workers <= 4: raise ValueError("页数、薪资或实例数超出范围")
    greeting = str(payload.get("greeting") or "").strip()
    if not greeting: raise ValueError("招呼语不能为空")
    search.update(keywords=[str(x).strip() for x in keywords if str(x).strip()], max_pages_per_keyword=pages,
                  min_salary_k=salary, greeting=greeting, exclude_title_keywords=payload.get("exclude",[]), company_blacklist=payload.get("blacklist",[]))
    raw.setdefault("ui",{})["parallel_workers"] = workers
    resume = raw.setdefault("resume_delivery",{}); values = {k:str(payload.get(f"resume_{k}") or "").strip() for k in ("general","ai","data")}
    for option in resume.get("options",[]):
        if values.get(str(option.get("key"))): option["display_name"] = values[str(option["key"])]
    resume.setdefault("deepseek",{})["enabled"] = bool(payload.get("deepseek_enabled")); resume["conversation_preferences"] = str(payload.get("preferences") or "").strip()
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    validation = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.validate.tmp")
    try:
        temporary.write_text(yaml.safe_dump(raw,allow_unicode=True,sort_keys=False),encoding="utf-8")
        if output_path:
            base = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            validation.write_text(
                yaml.safe_dump(_merge_config(base, raw), allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            load_config(validation)
        else:
            load_config(temporary)
        os.replace(temporary,target)
    finally:
        if temporary.exists():
            temporary.unlink()
        if validation.exists():
            validation.unlink()


# 保留旧内部名称，避免已有脚本或测试在升级 UI 后中断。
_atomic_save_search = _save_config


def run_ui(root: Path, config_path: Path, host: str = "127.0.0.1", port: int = 8765) -> int:
    lock_path = root / "data" / "ui.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = lock_path.open("a+b")
    if lock_handle.tell() == 0:
        lock_handle.write(b"0"); lock_handle.flush()
    lock_handle.seek(0)
    if msvcrt is not None:
        try:
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock_handle.close()
            print(f"UI 已经在运行：http://{host}:{port}")
            return 2
    controller = JobController(root, config_path); web_root = Path(__file__).with_name("web")
    class Handler(BaseHTTPRequestHandler):
        def respond(self, data: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status); self.send_header("Content-Type",content_type); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        def json(self, value: Any, status: int = 200) -> None: self.respond(json.dumps(value,ensure_ascii=False).encode(),"application/json; charset=utf-8",status)
        def do_GET(self) -> None:
            route = urlparse(self.path).path
            if route == "/api/state": return self.json(controller.state())
            asset = {"/":("index.html","text/html; charset=utf-8"),"/assets/style.css":("style.css","text/css; charset=utf-8"),"/assets/app.js":("app.js","text/javascript; charset=utf-8")}.get(route)
            if asset: return self.respond((web_root/asset[0]).read_bytes(),asset[1])
            self.json({"error":"not found"},404)
        def do_POST(self) -> None:
            try:
                payload=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))) or b"{}"); route=urlparse(self.path).path
                if route=="/api/config":
                    with controller.config_lock:
                        _save_config(config_path, payload, root / "config.local.yaml")
                elif route=="/api/action": controller.start(str(payload.get("action") or ""))
                elif route=="/api/resume": controller.resume()
                elif route=="/api/stop": controller.stop(str(payload.get("action") or ""))
                elif route=="/api/abort": controller.abort(str(payload.get("action") or ""))
                else: return self.json({"error":"not found"},404)
                self.json({"ok":True})
            except Exception as exc: self.json({"error":str(exc)},400)
        def log_message(self,*_:Any)->None: pass
    server=ThreadingHTTPServer((host,port),Handler); url=f"http://{host}:{port}"; print(f"BOSS 自动化控制台：{url}"); threading.Timer(.7,lambda:webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        if msvcrt is not None:
            lock_handle.seek(0)
            try: msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError: pass
        lock_handle.close()
    return 0
