# BOSS Job Assistant

基于 DrissionPage `ChromiumPage` 的本地 Chrome 任务调度工具，支持手动登录、断点续传、随机节奏、失败重试、异常截图和 CSV 结果记录。

## 统一启动入口

推荐使用 `启动.py`。不带参数时会打开只监听本机的 Web 控制台，不会自动执行沟通：

```powershell
cd D:\projects\boss-job-assistant
D:\Python3.10.1\python.exe .\启动.py
D:\Python3.10.1\python.exe .\启动.py ui
D:\Python3.10.1\python.exe .\启动.py validate
D:\Python3.10.1\python.exe .\启动.py --dry-run
D:\Python3.10.1\python.exe .\启动.py browser-check
D:\Python3.10.1\python.exe .\启动.py chat-check
D:\Python3.10.1\python.exe .\启动.py scan
D:\Python3.10.1\python.exe .\启动.py scan --keyword 数据分析 --max-pages 1
D:\Python3.10.1\python.exe .\启动.py run --tasks .\data\tasks.json
```

控制台地址为 `http://127.0.0.1:8765`。界面按“概览、搜索与匹配、沟通与 AI、数据与恢复”分区。独立沟通实例可以与主浏览器模块并行；搜索和聊天监听共用主 Chrome，会自动互斥，避免两个 DrissionPage 进程同时控制相同标签页。各模块分别保存恢复状态，完整流程仍是独占模式。

搜索词允许为空：空关键词会使用 BOSS 当前账号的个性化职位推荐流。控制台的“同步在线简历并更新推荐词”会只读抓取在线简历，按内容指纹保存版本，并结合 `data/job.md` 生成可一键填入的职位词。简历更新后重新同步即可，不需要改代码。

岗位是否通过阈值由本地可解释评分判断，当前默认阈值为 58；DeepSeek 不负责第一层筛选，而是在岗位通过阈值后根据在线简历和 JD 生成个性化招呼语，并在简历类型无法唯一判断时辅助决策。控制台“沟通与 AI”页会显示实际任务中的招呼语预览及其来源。

界面提供两种停止方式：“当前步骤结束后停止”不会打断正在操作的职位；“立即中止当前任务”会终止当前后端子进程，但保留已经完成的原子断点。每次串行沟通在记为成功之前，都会刷新固定聊天页并确认招呼语已经进入己方消息气泡；空输入框但没有对应消息时按失败重试处理。

沟通阶段支持 1–4 个独立进程并行。每个实例使用独立 Chrome 用户目录、调试端口、任务分片、断点、CSV 和截图，实例内部仍保持串行随机节奏；岗位、沟通和聊天业务数据统一写入中心三库，便于日报和幂等判断。首次使用多实例时，在“沟通与 AI”中点击“初始化实例登录”。并行沟通实例不会自动发送简历，所有回复监控和附件投递由唯一监控实例执行，避免重复发送。

## 本地数据与 AI 安全

- `data/jobs.db`：职位分类、在线简历快照、完整职位 URL/原始字段、匹配分数、理由和阈值结果。
- `data/communications.db`：定制招呼语、生成来源、尝试次数、发送与固定聊天页复核状态。
- `data/chat.db`：会话、消息指纹、AI 决策草稿、发送状态和面试人工接管提醒。
- 联系方式字段不会提交给 DeepSeek；招呼语不超过 70 字，自动回复不超过 60 字。
- 面试时间、地点、视频/电话邀约以及面试弹窗永远不自动确认，控制台会显示红色人工接管提醒。
- 自动回复生成后会刷新固定聊天页并再次比较最后消息指纹。若手机端已经回复、HR 发来新消息或最后消息已经变成己方消息，旧草稿会取消，防止多端冲突。
- 三份附件使用 `general / ai / data` 语义配置并按文件名片段动态查找，不依赖弹窗中的固定位置；可直接在控制台修改。
- 个人简历名称和 UI 修改项写入本地 `config.local.yaml`；该文件被 Git 忽略。仓库中的 `config.yaml` 只保存匿名公共默认值。
- 扫描任务、候选岗位和小批量测试任务属于运行数据，均保留在本机且不再进入 Git。
- DeepSeek 招呼语按简历指纹、模型和岗位内容缓存，并逐条落盘；中断恢复时不会重复请求已缓存岗位。

`启动.py` 只是安全入口，全部参数直接交给 `main.py`，不会维护第二套业务逻辑。原 `main.py` 命令继续兼容。

`scan` 使用与 `boss-tool` 相同的 `joblist` 网络监听方式，按 `config.yaml` 中的关键词逐页滚动采集并写入 `data/tasks.scanned.json`，不会沟通，并持续显示页数、累计岗位和耗时。
搜索断点会记录配置签名，并读取 joblist 的 `hasMore`：明确到达末页或配置页数时标记完成，监听超时则保留为可恢复状态。

`run` 与搜索完全分离：不传 `--tasks` 时只读取最近一次的 `data/tasks.scanned.json`；该文件不存在时直接停止并提示先运行 `scan`，不会自动搜索。传入 `--tasks` 时只执行指定文件。包含 `EXAMPLE` 的占位任务会被真实运行拒绝。

一次性允许聊天检查处理简历发送：

```powershell
python 启动.py chat-check --send-resume
```

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

- `data/progress.json` 和 `data/instances/*/progress.json`：沟通任务逐条断点。
- `data/scan_checkpoint.json`：搜索页断点；当前关键词中断后安全重扫并按职位 ID 去重。
- `data/workflow_state.json`：完整流程阶段断点；异常关闭后首页显示“继续上次任务”。
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
