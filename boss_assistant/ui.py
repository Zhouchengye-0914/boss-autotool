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

from .config import load_config
from .matching import recommend_titles
from .persistence import ProgressStore, load_tasks
from .scanner import save_tasks
from .talent_data import ChatDatabase, CommunicationsDatabase, JobsDatabase, parse_job_taxonomy
from .workflow import WorkflowStateStore


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
        self.stage = "空闲"
        self.logs: deque[str] = deque(maxlen=500)
        self.processes: dict[str, subprocess.Popen[str]] = {}
        self.process: subprocess.Popen[str] | None = None
        self.workflow = WorkflowStateStore(root / "data" / "workflow_state.json")
        self.workflow.load(recover_interrupted=True)

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
            jobs = JobsDatabase(config.storage.jobs_database_path); jobs.initialize()
            profile = jobs.latest_profile(); taxonomy = self.root / "data" / "job.md"
            if profile and taxonomy.exists(): suggestions = recommend_titles(profile, parse_job_taxonomy(taxonomy), config.search.recommendation_limit)
            chats = ChatDatabase(config.storage.chat_database_path); chats.initialize(); alerts = len(chats.pending_interview_alerts())
            CommunicationsDatabase(config.storage.communications_database_path).initialize()
        except Exception as exc: self.log(f"数据概览读取失败：{exc}")
        recovery = self.workflow.load()
        return {
            "running": self.running, "stage": self.stage, "logs": list(self.logs), "total": len(tasks),
            "pending": sum(t.task_id not in terminal for t in tasks), "success": success,
            "quota": max(0, config.scheduler.daily_success_limit - success), "interview_alerts": alerts,
            "recovery": {"resumable": recovery.resumable, "action": recovery.action,
                         "phase": recovery.phase, "label": ACTION_LABELS.get(recovery.action, recovery.action)},
            "paths": {"岗位库": str(config.storage.jobs_database_path), "沟通库": str(config.storage.communications_database_path),
                      "聊天库": str(config.storage.chat_database_path), "工作流断点": str(self.workflow.path),
                      "搜索断点": str(self.root / 'data' / 'scan_checkpoint.json')},
            "config": {"keywords": list(config.search.keywords), "max_pages": config.search.max_pages_per_keyword,
                       "workers": workers, "min_salary": config.search.min_salary_k, "greeting": config.search.greeting,
                       "exclude": list(config.search.exclude_title_keywords), "blacklist": list(config.search.company_blacklist),
                       "resume_general": names.get("general", ""), "resume_ai": names.get("ai", ""),
                       "resume_data": names.get("data", ""), "deepseek_enabled": config.resume.deepseek.enabled,
                       "preferences": config.resume.conversation_preferences, "suggestions": suggestions},
        }

    def start(self, action: str) -> None:
        if action not in ACTION_LABELS: raise ValueError("未知操作")
        with self.lock:
            if self.running: raise RuntimeError("已有任务运行中，请先停止")
            self.running = True; self.stop_requested = self.abort_requested = False
        self.workflow.update(action, "scanning" if action in {"scan", "full"} else "communicating" if action == "communicate" else "monitoring" if action == "watch" else "running", resumable=True)
        threading.Thread(target=self._worker, args=(action,), daemon=True).start()

    def resume(self) -> None:
        state = self.workflow.load()
        if not state.resumable or not state.action: raise RuntimeError("当前没有可恢复任务")
        self.start(state.action)

    def stop(self) -> None:
        with self.lock: self.stop_requested = True
        self.log("已请求安全停止；当前步骤结束后保留断点。")

    def abort(self) -> None:
        with self.lock:
            self.stop_requested = self.abort_requested = True
            processes = list(self.processes.values())
            if self.process is not None and self.process not in processes:
                processes.append(self.process)
        for process in processes:
            if process.poll() is None: process.terminate()
        self.log("已立即停止；已完成的搜索和沟通断点均保留。")

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
        threads = [threading.Thread(target=lambda n=n,a=a,l=l: results.update({n:self._command(a,l,n)}), daemon=True) for n,a,l in jobs]
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
                if first: ok = self._command(*first)
                if ok and action in {"communicate","full"} and not self.stop_requested:
                    self.workflow.update(action, "communicating", resumable=True); ok = self._parallel()
                if ok and action in {"watch","full"} and not self.stop_requested:
                    self.workflow.update(action, "monitoring", resumable=True)
                    while not self.stop_requested:
                        self._command(["chat-check","--send-resume"], "检查回复并匹配简历")
                        delay = random.randint(60,300); self.stage = f"等待下次检查（约 {delay//60} 分钟）"
                        for _ in range(delay):
                            if self.stop_requested: break
                            time.sleep(1)
        except Exception as exc:
            ok = False; error = f"{type(exc).__name__}: {exc}"; self.log(f"控制台异常：{error}")
        finally:
            interrupted = self.stop_requested or not ok
            self.workflow.update(action, "interrupted" if interrupted else "completed", error=error, resumable=interrupted)
            with self.lock:
                self.running = False; self.stage = "已停止，可继续" if interrupted else "已完成"


def _save_config(path: Path, payload: dict[str, Any]) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}; search = raw.setdefault("search", {})
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
    temporary = path.with_suffix(".yaml.tmp"); temporary.write_text(yaml.safe_dump(raw,allow_unicode=True,sort_keys=False),encoding="utf-8"); load_config(temporary); os.replace(temporary,path)


# 保留旧内部名称，避免已有脚本或测试在升级 UI 后中断。
_atomic_save_search = _save_config


def run_ui(root: Path, config_path: Path, host: str = "127.0.0.1", port: int = 8765) -> int:
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
                    if controller.running: raise RuntimeError("运行期间不能修改配置")
                    _save_config(config_path,payload)
                elif route=="/api/action": controller.start(str(payload.get("action") or ""))
                elif route=="/api/resume": controller.resume()
                elif route=="/api/stop": controller.stop()
                elif route=="/api/abort": controller.abort()
                else: return self.json({"error":"not found"},404)
                self.json({"ok":True})
            except Exception as exc: self.json({"error":str(exc)},400)
        def log_message(self,*_:Any)->None: pass
    server=ThreadingHTTPServer((host,port),Handler); url=f"http://{host}:{port}"; print(f"BOSS 自动化控制台：{url}"); threading.Timer(.7,lambda:webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
    return 0
