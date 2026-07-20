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


HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BOSS 自动化控制台</title><style>
:root{--bg:#f4f7f8;--card:#fff;--ink:#183039;--muted:#718087;--green:#18a899;--green2:#087f75;--line:#dce7e8;--warn:#e78a2f;--red:#d95858}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(140deg,#edf7f5,#f7f8fb 52%,#eef5f7);color:var(--ink);font:14px/1.5 system-ui,"Microsoft YaHei",sans-serif}
.wrap{max-width:1240px;margin:auto;padding:28px}.hero{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}.hero h1{font-size:28px;margin:0}.hero p{color:var(--muted);margin:4px 0}.pill{padding:8px 14px;border-radius:99px;background:#e0f5f1;color:var(--green2);font-weight:700}.grid{display:grid;grid-template-columns:1.05fr .95fr;gap:18px}.card{background:rgba(255,255,255,.94);border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 10px 35px rgba(25,65,72,.07)}h2{font-size:17px;margin:0 0 14px}.fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}.wide{grid-column:1/-1}label{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}input,textarea{width:100%;border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:#fbfdfd;color:var(--ink);outline:none}textarea{min-height:78px;resize:vertical}input:focus,textarea:focus{border-color:var(--green)}button{border:0;border-radius:11px;padding:11px 15px;font-weight:700;cursor:pointer;background:#e8f3f2;color:var(--green2)}button.primary{background:var(--green);color:white}button.dark{background:#213c45;color:white}button.warn{background:#fff0df;color:#a65d16}button.stop{background:#fde9e9;color:var(--red)}button:disabled{opacity:.45;cursor:not-allowed}.actions{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px}.actions .wide{grid-column:1/-1}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.stat{padding:13px;background:#f5faf9;border-radius:12px}.stat b{display:block;font-size:21px}.stat span{font-size:12px;color:var(--muted)}.flow{display:flex;gap:7px;align-items:center;margin:14px 0;color:var(--muted)}.flow i{height:1px;flex:1;background:var(--line)}.log{height:365px;overflow:auto;background:#12262c;color:#d8eeee;border-radius:13px;padding:14px;font:12px/1.65 Consolas,monospace;white-space:pre-wrap}.notice{margin-top:10px;color:var(--muted);font-size:12px}.statusline{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.busy{color:var(--warn)}.ok{color:var(--green2)}@media(max-width:850px){.grid{grid-template-columns:1fr}.stats{grid-template-columns:1fr 1fr}.wrap{padding:14px}}
</style></head><body><div class="wrap">
<div class="hero"><div><h1>BOSS 自动化控制台</h1><p>搜索、串行沟通、回复检查与附件简历投递</p></div><div id="badge" class="pill">正在连接</div></div>
<div class="grid"><section class="card"><h2>搜索与沟通设置</h2><div class="fields">
<div class="wide"><label>搜索关键词（逗号或换行分隔）</label><textarea id="keywords"></textarea></div>
<div><label>每个关键词最多页数</label><input id="pages" type="number" min="1" max="50"></div><div><label>最低薪资 K</label><input id="salary" type="number" min="0" max="100"></div>
<div class="wide"><label>自动招呼语</label><textarea id="greeting"></textarea></div>
<div class="wide"><label>排除职位词（逗号分隔）</label><input id="exclude"></div><div class="wide"><label>公司黑名单（逗号分隔）</label><input id="blacklist"></div>
</div><div class="actions"><button onclick="saveConfig()">保存并同步后端</button><button class="dark" onclick="run('browser')">检查登录</button>
<button onclick="run('scan')">① 只搜索岗位</button><button onclick="run('communicate')">② 串行批量沟通</button>
<button onclick="run('check')">③ 只检查 HR 回复</button><button class="warn" onclick="run('resume')">④ 单次检查并自动投递</button>
<button class="dark wide" onclick="run('watch')">持续监控回复（随机 1–5 分钟检查并自动投递）</button>
<button class="primary wide" onclick="run('full')">一键完整流程：搜索 → 沟通 → 持续监控并投递</button><button class="stop wide" onclick="stopRun()">完成当前步骤后停止</button></div>
<p class="notice">自动投递不需要输入联系人，只处理未读回复；明确邀请或符合主动联系规则后才发送，并按岗位匹配通用 / AI / 数据简历。</p></section>
<section class="card"><div class="statusline"><h2>运行状态</h2><strong id="stage">空闲</strong></div><div class="stats">
<div class="stat"><b id="total">0</b><span>扫描任务</span></div><div class="stat"><b id="pending">0</b><span>待沟通</span></div><div class="stat"><b id="success">0</b><span>今日成功</span></div><div class="stat"><b id="quota">300</b><span>今日剩余额度</span></div></div>
<div class="flow"><span>搜索</span><i></i><span>串行沟通</span><i></i><span>回复检查</span><i></i><span>简历匹配</span></div><div id="log" class="log">等待操作…</div></section></div></div>
<script>
let initialized=false;
async function api(path,options={}){let r=await fetch(path,options);let j=await r.json();if(!r.ok)throw Error(j.error||'请求失败');return j}
function split(v){return v.split(/[，,\n]/).map(x=>x.trim()).filter(Boolean)}
async function saveConfig(silent=false){try{await api('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keywords:split(keywords.value),max_pages:+pages.value,min_salary:+salary.value,greeting:greeting.value.trim(),exclude:split(exclude.value),blacklist:split(blacklist.value)})});if(!silent)alert('配置已同步到后端');return true}catch(e){alert(e.message);return false}}
async function run(action){try{if(!await saveConfig(true))return;await api('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})})}catch(e){alert(e.message)}}
async function stopRun(){try{await api('/api/stop',{method:'POST'})}catch(e){alert(e.message)}}
async function poll(){try{let s=await api('/api/state');badge.textContent=s.running?'运行中':'系统就绪';badge.className='pill '+(s.running?'busy':'ok');stage.textContent=s.stage;total.textContent=s.total;pending.textContent=s.pending;success.textContent=s.success;quota.textContent=s.quota;let box=document.getElementById('log');let atBottom=box.scrollHeight-box.scrollTop-box.clientHeight<40;box.textContent=s.logs.join('\n')||'等待操作…';if(atBottom)box.scrollTop=box.scrollHeight;if(!initialized){keywords.value=s.config.keywords.join('\n');pages.value=s.config.max_pages;salary.value=s.config.min_salary;greeting.value=s.config.greeting;exclude.value=s.config.exclude.join(', ');blacklist.value=s.config.blacklist.join(', ');initialized=true}}catch(e){badge.textContent='连接失败'}setTimeout(poll,1200)}poll();
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

    def log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        with self.lock:
            self.logs.append(f"[{stamp}] {message.rstrip()}")

    def state(self) -> dict[str, Any]:
        config = load_config(self.config_path)
        tasks = load_tasks(config.search.output_file) if config.search.output_file.exists() else []
        store = ProgressStore(config.scheduler.progress_file)
        store.load()
        pending = store.pending(tasks)
        success = store.success_count_today()
        with self.lock:
            return {
                "running": self.running, "stage": self.stage, "logs": list(self.logs),
                "total": len(tasks), "pending": len(pending), "success": success,
                "quota": max(0, config.scheduler.daily_success_limit - success),
                "config": {"keywords": list(config.search.keywords),
                    "max_pages": config.search.max_pages_per_keyword,
                    "min_salary": config.search.min_salary_k, "greeting": config.search.greeting,
                    "exclude": list(config.search.exclude_title_keywords),
                    "blacklist": list(config.search.company_blacklist)},
            }

    def start(self, action: str) -> None:
        with self.lock:
            if self.running:
                raise RuntimeError("已有任务正在运行；搜索、沟通和检查必须串行")
            self.running = True
            self.stop_requested = False
        threading.Thread(target=self._worker, args=(action,), daemon=True).start()

    def stop(self) -> None:
        with self.lock:
            self.stop_requested = True
        self.log("已请求停止：当前步骤安全结束后，不再执行后续步骤。")

    def _command(self, args: list[str], label: str) -> bool:
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
        assert process.stdout is not None
        for line in process.stdout:
            self.log(line)
        code = process.wait()
        self.log(f"{label}结束，退出码 {code}")
        return code == 0

    def _worker(self, action: str) -> None:
        plans = {
            "browser": [(["browser-check"], "检查 Chrome 登录")],
            "scan": [(["scan"], "搜索岗位")],
            "communicate": [(["run"], "串行批量沟通")],
            "check": [(["chat-check"], "检查 HR 回复")],
            "resume": [(["chat-check", "--send-resume"], "自动匹配并投递简历")],
            "watch": [],
            "full": [(["scan"], "搜索岗位"), (["run"], "串行批量沟通")],
        }
        try:
            for args, label in plans[action]:
                with self.lock:
                    if self.stop_requested:
                        break
                if not self._command(args, label):
                    self.log("当前步骤失败，完整流程已停止。")
                    break
            if action in {"watch", "full"} and not self.stop_requested:
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
                self.stage = "已停止" if self.stop_requested else "空闲"


def _atomic_save_search(config_path: Path, payload: dict[str, Any]) -> None:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    search = raw.setdefault("search", {})
    keywords = payload.get("keywords")
    if not isinstance(keywords, list) or not keywords or not all(isinstance(x, str) and x.strip() for x in keywords):
        raise ValueError("至少填写一个搜索关键词")
    pages = int(payload.get("max_pages", 0))
    salary = int(payload.get("min_salary", 0))
    greeting = str(payload.get("greeting") or "").strip()
    if not 1 <= pages <= 50:
        raise ValueError("每个关键词页数必须在 1-50 之间")
    if not 0 <= salary <= 100:
        raise ValueError("最低薪资必须在 0-100K 之间")
    if not greeting:
        raise ValueError("招呼语不能为空")
    search.update(keywords=[x.strip() for x in keywords], max_pages_per_keyword=pages,
                  min_salary_k=salary, greeting=greeting,
                  exclude_title_keywords=[str(x).strip() for x in payload.get("exclude", []) if str(x).strip()],
                  company_blacklist=[str(x).strip() for x in payload.get("blacklist", []) if str(x).strip()])
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
                    if action not in {"browser", "scan", "communicate", "check", "resume", "watch", "full"}:
                        raise ValueError("未知操作")
                    controller.start(action)
                elif path == "/api/stop": controller.stop()
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
