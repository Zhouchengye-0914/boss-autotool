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
from .persistence import ProgressStore, load_tasks
from .scanner import save_tasks


HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BOSS 自动化控制台</title><style>
:root{--bg:#f4f7f8;--card:#fff;--ink:#183039;--muted:#718087;--green:#18a899;--green2:#087f75;--line:#dce7e8;--warn:#e78a2f;--red:#d95858}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(140deg,#edf7f5,#f7f8fb 52%,#eef5f7);color:var(--ink);font:14px/1.5 system-ui,"Microsoft YaHei",sans-serif}
.wrap{max-width:1240px;margin:auto;padding:28px}.hero{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}.hero-right{display:flex;gap:8px;align-items:center}.hero h1{font-size:28px;margin:0}.hero p{color:var(--muted);margin:4px 0}.pill{padding:8px 14px;border-radius:99px;background:#e0f5f1;color:var(--green2);font-weight:700}.grid{display:grid;grid-template-columns:1.05fr .95fr;gap:18px}.card{background:rgba(255,255,255,.94);border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 10px 35px rgba(25,65,72,.07)}h2{font-size:17px;margin:0 0 14px}.fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}.wide{grid-column:1/-1}label{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}input,textarea{width:100%;border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:#fbfdfd;color:var(--ink);outline:none}textarea{min-height:78px;resize:vertical}input:focus,textarea:focus{border-color:var(--green)}button{border:0;border-radius:11px;padding:11px 15px;font-weight:700;cursor:pointer;background:#e8f3f2;color:var(--green2)}button.primary{background:var(--green);color:white}button.dark{background:#213c45;color:white}button.warn{background:#fff0df;color:#a65d16}button.stop{background:#fde9e9;color:var(--red)}button.abort{background:var(--red);color:white}button:disabled{opacity:.45;cursor:not-allowed}.actions{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px}.actions .wide{grid-column:1/-1}.advanced{grid-column:1/-1;border:1px solid var(--line);border-radius:12px;padding:9px 12px}.advanced summary{cursor:pointer;font-weight:700;color:var(--muted)}.advanced-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.stat{padding:13px;background:#f5faf9;border-radius:12px}.stat b{display:block;font-size:21px}.stat span{font-size:12px;color:var(--muted)}.flow{display:flex;gap:7px;align-items:center;margin:14px 0;color:var(--muted)}.flow i{height:1px;flex:1;background:var(--line)}.log{height:365px;overflow:auto;background:#12262c;color:#d8eeee;border-radius:13px;padding:14px;font:12px/1.65 Consolas,monospace;white-space:pre-wrap}.notice{margin-top:10px;color:var(--muted);font-size:12px}.statusline{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.busy{color:var(--warn)}.ok{color:var(--green2)}.modal{display:none;position:fixed;inset:0;background:#18303988;z-index:20;align-items:center;justify-content:center;padding:20px}.modal.open{display:flex}.modal-box{background:white;max-width:680px;max-height:85vh;overflow:auto;border-radius:18px;padding:24px}.help-row{padding:11px 0;border-bottom:1px solid var(--line)}.help-row b{display:block}.help-row span{color:var(--muted)}@media(max-width:850px){.grid{grid-template-columns:1fr}.stats{grid-template-columns:1fr 1fr}.wrap{padding:14px}}
</style></head><body><div class="wrap">
<div class="hero"><div><h1>BOSS 自动化控制台</h1><p>搜索、串行沟通、回复检查与附件简历投递</p></div><div class="hero-right"><button onclick="help(true)">功能说明</button><div id="badge" class="pill">正在连接</div></div></div>
<div class="grid"><section class="card"><h2>搜索与沟通设置</h2><div class="fields">
<div class="wide"><label>搜索关键词（逗号或换行分隔）</label><textarea id="keywords"></textarea></div>
<div><label>每个关键词最多页数</label><input id="pages" type="number" min="1" max="50"></div><div><label>最低薪资 K</label><input id="salary" type="number" min="0" max="100"></div>
<div><label>并行沟通实例数（1–4）</label><input id="workers" type="number" min="1" max="4"></div><div><label>运行方式</label><input value="独立 Chrome + 独立断点" disabled></div>
<div class="wide"><label>自动招呼语</label><textarea id="greeting"></textarea></div>
<div class="wide"><label>排除职位词（逗号分隔）</label><input id="exclude"></div><div class="wide"><label>公司黑名单（逗号分隔）</label><input id="blacklist"></div>
</div><div class="actions"><button onclick="saveConfig()">保存搜索设置</button><button class="dark" onclick="run('browser')">检查登录</button>
<button class="primary wide" onclick="run('full')">一键开始：搜索 → 串行沟通 → 持续检查回复并投递</button>
<button class="stop" onclick="stopRun()">当前步骤结束后停止</button><button class="abort" onclick="abortRun()">立即中止当前任务</button>
<details class="advanced"><summary>单独执行某项功能（高级操作）</summary><div class="advanced-grid"><button class="dark wide" onclick="run('init-workers')">首次使用：初始化全部并行实例登录</button><button onclick="run('scan')">只搜索岗位</button><button onclick="run('communicate')">只执行并行沟通</button><button onclick="run('check')">只检查 HR 回复</button><button class="warn" onclick="run('resume')">单次检查并自动投递</button><button class="dark wide" onclick="run('watch')">持续监控回复与简历邀请</button></div></details></div>
<p class="notice">自动投递不需要输入联系人，只处理未读回复；明确邀请或符合主动联系规则后才发送，并按岗位匹配通用 / AI / 数据简历。</p></section>
<section class="card"><div class="statusline"><h2>运行状态</h2><strong id="stage">空闲</strong></div><div class="stats">
<div class="stat"><b id="total">0</b><span>扫描任务</span></div><div class="stat"><b id="pending">0</b><span>待沟通</span></div><div class="stat"><b id="success">0</b><span>今日成功</span></div><div class="stat"><b id="quota">300</b><span>今日剩余额度</span></div></div>
<div class="flow"><span>搜索</span><i></i><span>串行沟通</span><i></i><span>回复检查</span><i></i><span>简历匹配</span></div><div id="log" class="log">等待操作…</div></section></div></div>
<div id="help" class="modal" onclick="if(event.target===this)help(false)"><div class="modal-box"><div class="statusline"><h2>按钮功能说明</h2><button onclick="help(false)">关闭</button></div>
<div class="help-row"><b>一键开始</b><span>先按当前搜索设置采集岗位，再逐条串行沟通；完成后每隔随机 1–5 分钟检查 HR 回复并自动匹配附件简历。</span></div>
<div class="help-row"><b>当前步骤结束后停止</b><span>不打断正在操作的职位，当前搜索或沟通步骤完成后停止后续步骤。</span></div>
<div class="help-row"><b>立即中止当前任务</b><span>马上终止当前搜索/沟通/检查子进程，不删除已完成断点；下次启动会从未完成任务继续。</span></div>
<div class="help-row"><b>只搜索岗位</b><span>更新任务池，不发送消息。页面会显示累计岗位和耗时。</span></div>
<div class="help-row"><b>并行沟通实例</b><span>将岗位分片给 1–4 个独立 Chrome 进程；每个进程内部仍串行操作，并使用独立端口、用户目录、断点和日志。</span></div>
<div class="help-row"><b>初始化全部并行实例登录</b><span>每个独立 Chrome 用户目录首次需要手动登录一次。初始化完成后会持久复用各自会话。</span></div>
<div class="help-row"><b>只执行沟通</b><span>读取最近搜索结果并按实例数并行；每个实例发送后都必须到自己的固定聊天页复核才算成功。</span></div>
<div class="help-row"><b>检查 / 自动投递</b><span>检查红色未读数字；只有明确简历邀请或符合主动联系规则时才按岗位发送通用、AI 或数据简历。</span></div></div></div>
<script>
let initialized=false;
async function api(path,options={}){let r=await fetch(path,options);let j=await r.json();if(!r.ok)throw Error(j.error||'请求失败');return j}
function split(v){return v.split(/[，,\n]/).map(x=>x.trim()).filter(Boolean)}
async function saveConfig(silent=false){try{await api('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keywords:split(keywords.value),max_pages:+pages.value,min_salary:+salary.value,workers:+workers.value,greeting:greeting.value.trim(),exclude:split(exclude.value),blacklist:split(blacklist.value)})});if(!silent)alert('配置已同步到后端');return true}catch(e){alert(e.message);return false}}
async function run(action){try{if(!await saveConfig(true))return;await api('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})})}catch(e){alert(e.message)}}
async function stopRun(){try{await api('/api/stop',{method:'POST'})}catch(e){alert(e.message)}}
async function abortRun(){if(!confirm('立即中止当前任务？已成功的断点会保留。'))return;try{await api('/api/abort',{method:'POST'})}catch(e){alert(e.message)}}
function help(open){document.getElementById('help').classList.toggle('open',open)}
async function poll(){try{let s=await api('/api/state');badge.textContent=s.running?'运行中':'系统就绪';badge.className='pill '+(s.running?'busy':'ok');stage.textContent=s.stage;total.textContent=s.total;pending.textContent=s.pending;success.textContent=s.success;quota.textContent=s.quota;let box=document.getElementById('log');let atBottom=box.scrollHeight-box.scrollTop-box.clientHeight<40;box.textContent=s.logs.join('\n')||'等待操作…';if(atBottom)box.scrollTop=box.scrollHeight;if(!initialized){keywords.value=s.config.keywords.join('\n');pages.value=s.config.max_pages;salary.value=s.config.min_salary;workers.value=s.config.workers;greeting.value=s.config.greeting;exclude.value=s.config.exclude.join(', ');blacklist.value=s.config.blacklist.join(', ');initialized=true}}catch(e){badge.textContent='连接失败'}setTimeout(poll,1200)}poll();
</script></body></html>"""


class JobController:
    def __init__(self, root: Path, config_path: Path):
        self.root = root
        self.config_path = config_path
        self.lock = threading.Lock()
        self.running = False
        self.stage = "空闲"
        self.logs: deque[str] = deque(maxlen=500)
        self.stop_requested = False
        self.abort_requested = False
        self.process: subprocess.Popen[str] | None = None
        self.processes: dict[str, subprocess.Popen[str]] = {}

    def log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        with self.lock:
            self.logs.append(f"[{stamp}] {message.rstrip()}")

    def state(self) -> dict[str, Any]:
        config = load_config(self.config_path)
        tasks = load_tasks(config.search.output_file) if config.search.output_file.exists() else []
        terminal, success = self._combined_progress(config)
        pending = [task for task in tasks if task.task_id not in terminal]
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        workers = int((raw.get("ui") or {}).get("parallel_workers", 2))
        with self.lock:
            return {
                "running": self.running, "stage": self.stage, "logs": list(self.logs),
                "total": len(tasks), "pending": len(pending), "success": success,
                "quota": max(0, config.scheduler.daily_success_limit - success),
                "config": {"keywords": list(config.search.keywords),
                    "max_pages": config.search.max_pages_per_keyword,
                    "workers": workers,
                    "min_salary": config.search.min_salary_k, "greeting": config.search.greeting,
                    "exclude": list(config.search.exclude_title_keywords),
                    "blacklist": list(config.search.company_blacklist)},
            }

    def _combined_progress(self, config: Any) -> tuple[set[str], int]:
        paths = [config.scheduler.progress_file]
        paths.extend((self.root / "data" / "instances").glob("*/progress.json"))
        terminal: set[str] = set()
        success = 0
        for path in paths:
            store = ProgressStore(path)
            try:
                store.load()
            except Exception as exc:
                self.log(f"忽略无法读取的实例断点 {path}: {exc}")
                continue
            success += store.success_count_today()
            terminal.update(
                task_id for task_id, value in store.data.get("tasks", {}).items()
                if value.get("status") in {"success", "skipped"}
            )
        return terminal, success

    def start(self, action: str) -> None:
        with self.lock:
            if self.running:
                raise RuntimeError("已有任务正在运行；搜索、沟通和检查必须串行")
            self.running = True
            self.stop_requested = False
            self.abort_requested = False
        threading.Thread(target=self._worker, args=(action,), daemon=True).start()

    def stop(self) -> None:
        with self.lock:
            self.stop_requested = True
        self.log("已请求停止：当前步骤安全结束后，不再执行后续步骤。")

    def abort(self) -> None:
        with self.lock:
            self.stop_requested = True
            self.abort_requested = True
            processes = list(self.processes.values())
            if self.process is not None and self.process not in processes:
                processes.append(self.process)
        active = [process for process in processes if process.poll() is None]
        if active:
            for process in active:
                process.terminate()
            self.log("已立即中止当前子任务；已完成断点保留，下次可继续。")
        else:
            self.log("当前没有正在执行的子任务。")

    def _command(self, args: list[str], label: str, process_key: str = "main") -> bool:
        with self.lock:
            self.stage = label
        self.log(f"开始：{label}")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            [sys.executable, str(self.root / "启动.py"), *args], cwd=self.root,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", env=env,
        )
        with self.lock:
            self.process = process
            self.processes[process_key] = process
        assert process.stdout is not None
        try:
            for line in process.stdout:
                self.log(line)
            code = process.wait()
        finally:
            with self.lock:
                if self.process is process:
                    self.process = None
                self.processes.pop(process_key, None)
        self.log(f"{label}结束，退出码 {code}")
        return code == 0

    def _parallel_workers(self) -> int:
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        return max(1, min(4, int((raw.get("ui") or {}).get("parallel_workers", 2))))

    def _prepare_partitions(self, worker_count: int) -> list[tuple[str, Path, int]]:
        config = load_config(self.config_path)
        if not config.search.output_file.exists():
            raise RuntimeError("没有搜索结果，请先搜索岗位")
        tasks = load_tasks(config.search.output_file)
        terminal, _ = self._combined_progress(config)
        partitions: list[list[Any]] = [[] for _ in range(worker_count)]
        for task in tasks:
            if task.task_id in terminal:
                continue
            bucket = sum(task.task_id.encode("utf-8")) % worker_count
            partitions[bucket].append(task)
        result: list[tuple[str, Path, int]] = []
        for index, part in enumerate(partitions):
            name = f"worker-{index + 1:02d}"
            path = self.root / "data" / "instances" / name / "tasks.json"
            save_tasks(path, part)
            if part:
                result.append((name, path, index))
            self.log(f"{name} 分配 {len(part)} 个待沟通岗位。")
        return result

    def _parallel_communicate(self) -> bool:
        worker_count = self._parallel_workers()
        partitions = self._prepare_partitions(worker_count)
        if not partitions:
            self.log("没有待沟通岗位。")
            return True
        with self.lock:
            self.stage = f"{len(partitions)} 个独立实例并行沟通"
        results: dict[str, bool] = {}
        threads: list[threading.Thread] = []
        config = load_config(self.config_path)
        _, success_today = self._combined_progress(config)
        remaining_quota = max(0, config.scheduler.daily_success_limit - success_today)

        def run_one(name: str, path: Path, index: int) -> None:
            worker_store = ProgressStore(self.root / "data" / "instances" / name / "progress.json")
            worker_store.load()
            share = remaining_quota // worker_count + (1 if index < remaining_quota % worker_count else 0)
            worker_limit = worker_store.success_count_today() + share
            if share <= 0:
                self.log(f"{name} 今日没有剩余额度，跳过。")
                results[name] = True
                return
            args = ["run", "--tasks", str(path), "--instance", name,
                    "--port-offset", str(index + 1), "--worker-index", str(index),
                    "--worker-count", str(worker_count), "--daily-limit", str(worker_limit)]
            results[name] = self._command(args, f"[{name}] 串行沟通", name)

        for name, path, index in partitions:
            thread = threading.Thread(target=run_one, args=(name, path, index), daemon=True)
            thread.start(); threads.append(thread)
        for thread in threads:
            thread.join()
        return all(results.values())

    def _parallel_browser_check(self) -> bool:
        worker_count = self._parallel_workers()
        results: dict[str, bool] = {}
        threads: list[threading.Thread] = []

        def run_one(index: int) -> None:
            name = f"worker-{index + 1:02d}"
            args = ["browser-check", "--instance", name, "--port-offset", str(index + 1),
                    "--worker-index", str(index), "--worker-count", str(worker_count)]
            results[name] = self._command(args, f"[{name}] 初始化登录", name)

        with self.lock:
            self.stage = f"初始化 {worker_count} 个独立 Chrome 登录"
        for index in range(worker_count):
            thread = threading.Thread(target=run_one, args=(index,), daemon=True)
            thread.start(); threads.append(thread)
        for thread in threads:
            thread.join()
        return all(results.values())

    def _worker(self, action: str) -> None:
        plans = {
            "browser": [(["browser-check"], "检查 Chrome 登录")],
            "init-workers": [],
            "scan": [(["scan"], "搜索岗位")],
            "communicate": [],
            "check": [(["chat-check"], "检查 HR 回复")],
            "resume": [(["chat-check", "--send-resume"], "自动匹配并投递简历")],
            "watch": [],
            "full": [(["scan"], "搜索岗位")],
        }
        try:
            proceed = True
            if action == "init-workers":
                proceed = self._parallel_browser_check()
            for args, label in plans[action]:
                with self.lock:
                    if self.stop_requested:
                        break
                if not self._command(args, label):
                    self.log("当前步骤失败，完整流程已停止。")
                    proceed = False
                    break
            if proceed and action in {"communicate", "full"} and not self.stop_requested:
                proceed = self._parallel_communicate()
                if not proceed:
                    self.log("至少一个沟通实例失败，后续自动监控未启动。")
            if proceed and action in {"watch", "full"} and not self.stop_requested:
                while True:
                    with self.lock:
                        if self.stop_requested:
                            break
                    self._command(["chat-check", "--send-resume"], "检查回复并自动匹配简历")
                    wait_seconds = random.randint(60, 300)
                    self.log(f"下一次回复检查将在约 {wait_seconds // 60} 分 {wait_seconds % 60} 秒后执行。")
                    with self.lock:
                        self.stage = "等待下一次回复检查"
                    for _ in range(wait_seconds):
                        time.sleep(1)
                        with self.lock:
                            if self.stop_requested:
                                break
                    if self.stop_requested:
                        break
        except Exception as exc:
            self.log(f"控制台异常：{type(exc).__name__}: {exc}")
        finally:
            with self.lock:
                self.running = False
                self.stage = "已立即中止" if self.abort_requested else (
                    "已停止" if self.stop_requested else "空闲"
                )


def _atomic_save_search(config_path: Path, payload: dict[str, Any]) -> None:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    search = raw.setdefault("search", {})
    keywords = payload.get("keywords")
    if not isinstance(keywords, list) or not keywords or not all(isinstance(x, str) and x.strip() for x in keywords):
        raise ValueError("至少填写一个搜索关键词")
    pages = int(payload.get("max_pages", 0))
    salary = int(payload.get("min_salary", 0))
    workers = int(payload.get("workers", 0))
    greeting = str(payload.get("greeting") or "").strip()
    if not 1 <= pages <= 50:
        raise ValueError("每个关键词页数必须在 1-50 之间")
    if not 0 <= salary <= 100:
        raise ValueError("最低薪资必须在 0-100K 之间")
    if not 1 <= workers <= 4:
        raise ValueError("并行沟通实例数必须在 1-4 之间")
    if not greeting:
        raise ValueError("招呼语不能为空")
    search.update(keywords=[x.strip() for x in keywords], max_pages_per_keyword=pages,
                  min_salary_k=salary, greeting=greeting,
                  exclude_title_keywords=[str(x).strip() for x in payload.get("exclude", []) if str(x).strip()],
                  company_blacklist=[str(x).strip() for x in payload.get("blacklist", []) if str(x).strip()])
    raw.setdefault("ui", {})["parallel_workers"] = workers
    temp = config_path.with_suffix(".yaml.tmp")
    temp.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    load_config(temp)
    os.replace(temp, config_path)


def run_ui(root: Path, config_path: Path, host: str = "127.0.0.1", port: int = 8765) -> int:
    controller = JobController(root, config_path)

    class Handler(BaseHTTPRequestHandler):
        def _json(self, value: Any, status: int = 200) -> None:
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_GET(self) -> None:
            if urlparse(self.path).path == "/":
                data = HTML.encode("utf-8"); self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            elif urlparse(self.path).path == "/api/state":
                try: self._json(controller.state())
                except Exception as exc: self._json({"error": str(exc)}, 500)
            else: self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                path = urlparse(self.path).path
                if path == "/api/config":
                    if controller.running: raise RuntimeError("任务运行期间不能修改配置")
                    _atomic_save_search(config_path, payload); controller.log("搜索设置已同步到 config.yaml")
                elif path == "/api/action":
                    action = str(payload.get("action") or "")
                    if action not in {"browser", "init-workers", "scan", "communicate", "check", "resume", "watch", "full"}:
                        raise ValueError("未知操作")
                    controller.start(action)
                elif path == "/api/stop": controller.stop()
                elif path == "/api/abort": controller.abort()
                else: return self._json({"error": "not found"}, 404)
                self._json({"ok": True})
            except Exception as exc: self._json({"error": str(exc)}, 400)

        def log_message(self, *_: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"BOSS 自动化控制台已启动：{url}")
    threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
    return 0
