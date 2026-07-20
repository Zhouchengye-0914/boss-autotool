# BOSS Job Assistant

基于 DrissionPage `ChromiumPage` 的本地 Chrome 任务调度工具，支持手动登录、断点续传、随机节奏、失败重试、异常截图和 CSV 结果记录。

## 统一启动入口

推荐使用 `启动.py`。不带参数时只显示当前状态，不会打开 Chrome 或执行沟通：

```powershell
cd D:\projects\boss-job-assistant
D:\Python3.10.1\python.exe .\启动.py
D:\Python3.10.1\python.exe .\启动.py validate
D:\Python3.10.1\python.exe .\启动.py --dry-run
D:\Python3.10.1\python.exe .\启动.py browser-check
D:\Python3.10.1\python.exe .\启动.py chat-check
D:\Python3.10.1\python.exe .\启动.py scan
D:\Python3.10.1\python.exe .\启动.py scan --keyword 数据分析 --max-pages 1
D:\Python3.10.1\python.exe .\启动.py run --tasks .\data\tasks.json
```

`启动.py` 只是安全入口，全部参数直接交给 `main.py`，不会维护第二套业务逻辑。原 `main.py` 命令继续兼容。

`scan` 使用与 `boss-tool` 相同的 `joblist` 网络监听方式，按 `config.yaml` 中的关键词逐页滚动采集并写入 `data/tasks.scanned.json`，不会沟通。`run` 不传 `--tasks` 时会先执行同样的搜索，再把筛选结果交给串行调度器；传入 `--tasks` 时才执行指定文件。包含 `EXAMPLE` 的占位任务会被真实运行拒绝。

## 开始前

1. 阅读 `环境配置基线.md`，不得改变本项目所需依赖版本。
2. 优先使用 `scan` 生成真实任务；示例任务禁止用于真实运行。
3. 先运行验证和 dry-run：

```powershell
cd D:\projects\boss-job-assistant
D:\Python3.10.1\python.exe main.py validate
D:\Python3.10.1\python.exe main.py --dry-run
D:\Python3.10.1\python.exe main.py environment-check
```

## Chrome 登录

```powershell
D:\Python3.10.1\python.exe main.py browser-check
D:\Python3.10.1\python.exe main.py chat-check
```

首次启动会创建 `data/browser_profiles/chrome`。请在该窗口中手动登录 BOSS 直聘。程序不会保存账号或密码。

## 真实运行

```powershell
D:\Python3.10.1\python.exe main.py run --tasks D:\path\to\tasks.json
```

真实运行会点击页面并发送沟通或投递。首次验证应只使用一条任务。验证码和安全验证必须手动处理。

## 任务格式

```json
[
  {
    "task_id": "job-001",
    "job_url": "https://www.zhipin.com/job_detail/职位ID.html",
    "job_id": "职位ID",
    "greeting": "您好，我对这个职位很感兴趣。",
    "resume_name": "默认简历.pdf",
    "operation_type": "communication"
  }
]
```

`operation_type` 可为 `communication` 或 `application`。成功和最终跳过任务会在重启后跳过；仅成功任务占每日额度。

## 输出

- `data/progress.json`：断点状态。
- `logs/operation_results.csv`：每次尝试结果。
- `logs/error_log.csv`：最终跳过任务。
- `screenshots/`：页面异常截图。
- `data/boss_assistant.db`：职位、公司、聊天消息、未读检查和简历邀请审计库。
- `reports/`：后续每日分层汇报目录。

## 固定聊天窗口

真实运行只创建一个固定聊天标签页。所有浏览器动作保持单线程串行：每条沟通完成后轻量检查红色未读数字；平时按配置中的 60–300 秒随机间隔检查，页面超过陈旧阈值时才刷新。普通回复、明确简历邀请和待人工判断消息分别记录。

沟通操作参考 `boss-tool`：每个岗位使用临时详情标签页，定位聊天输入区后优先回车发送，页面未清空时回退到发送按钮，完成后关闭临时标签。固定聊天标签页不会被关闭。

`resume_delivery.options` 必须配置三份附件简历。`display_name` 已知时优先按名称唯一匹配；当前名称未知时使用 `option_index` 0、1、2。HR 主动建立会话或明确邀请简历后，程序根据岗位关键词选择简历并点击“发简历”。每个会话成功发送一次后会通过 SQLite 幂等记录避免重复发送。

DeepSeek 接口默认关闭。启用时只从环境变量读取密钥，不把密钥写入 YAML：

```powershell
$env:DEEPSEEK_API_KEY = "你的密钥"
# 然后把 config.yaml 中 resume_delivery.deepseek.enabled 改为 true
```

本地关键词能唯一匹配时不会调用 API；只有无法唯一匹配时才调用配置的 OpenAI 兼容接口。`chat-check` 始终禁止自动发送附件，只做检查；自动附件发送只在正式 `run` 调度中启用。

实测的页面入口、选择器、沟通按钮副本和在线简历结构见
[`docs/BOSS前端结构说明.md`](docs/BOSS前端结构说明.md)。
