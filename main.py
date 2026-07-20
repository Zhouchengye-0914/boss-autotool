from __future__ import annotations

import argparse
import importlib.metadata
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from boss_assistant.actions import BossTaskExecutor
from boss_assistant.browser import create_browser, open_login_page
from boss_assistant.config import ConfigError, load_config
from boss_assistant.output import CsvOutput
from boss_assistant.pacing import PacingController
from boss_assistant.persistence import ProgressError, ProgressStore, load_tasks
from boss_assistant.scheduler import TaskScheduler
from boss_assistant.chat_monitor import ChatMonitor, CHAT_URL
from boss_assistant.records import RecordStore
from boss_assistant.monitor import LayeredReporter
from boss_assistant.daily_report import DailyReportGenerator
from boss_assistant.scanner import BossJobScanner, jobs_to_tasks, save_tasks
from boss_assistant.ui import run_ui

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.yaml"
FREEZE_FILE = ROOT / "environment-freeze.txt"
REQUIRED_PYTHON = (3, 10, 1)
PROJECT_DEPENDENCIES = {"DrissionPage": "4.1.1.4", "PyYAML": "6.0.2"}


def current_freeze() -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return completed.stdout.replace("\r\n", "\n").strip() + "\n"


def environment_check() -> bool:
    problems: list[str] = []
    current_python = sys.version_info[:3]
    if current_python != REQUIRED_PYTHON:
        problems.append(
            f"Python 需要 {'.'.join(map(str, REQUIRED_PYTHON))}，当前为 "
            f"{'.'.join(map(str, current_python))}"
        )
    for package, expected_version in PROJECT_DEPENDENCIES.items():
        try:
            current_version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            problems.append(f"缺少项目依赖 {package}=={expected_version}")
            continue
        if current_version != expected_version:
            problems.append(f"{package} 需要 {expected_version}，当前为 {current_version}")
    if problems:
        print("项目环境检查失败：")
        for problem in problems:
            print(f"- {problem}")
        return False
    print("项目环境检查通过：Python、DrissionPage 和 PyYAML 版本符合基线。")
    try:
        expected = FREEZE_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
        if expected != current_freeze():
            print("提示：完整 Python 环境存在其他包变化，但不影响本项目启动。")
    except (OSError, subprocess.SubprocessError):
        print("提示：完整依赖审计未完成，但项目依赖检查已通过。")
    return True


def dry_run(config_path: Path, tasks_path: Path | None) -> int:
    config = load_config(config_path)
    source = tasks_path or config.search.output_file
    if not source.exists():
        print(f"dry-run：尚无扫描任务文件 {source}；请先执行 scan，或显式传入 --tasks。")
        return 0
    tasks = load_tasks(source)
    store = ProgressStore(config.scheduler.progress_file)
    store.load()
    pending = store.pending(tasks)
    remaining_quota = config.scheduler.daily_success_limit - store.success_count_today()
    print(f"dry-run：任务 {len(tasks)}，待执行 {len(pending)}，今日剩余额度 {remaining_quota}")
    for index, task in enumerate(pending, start=1):
        print(f"{index}. {task.task_id} | {task.operation_type.value} | {task.job_url}")
    print("dry-run 未启动 Chrome、未休眠、未写入断点。")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="BOSS 直聘 Chrome 自动化助手")
    result.add_argument(
        "command", nargs="?",
        choices=["ui", "validate", "browser-check", "chat-check", "scan", "run", "status", "environment-check"],
    )
    result.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    result.add_argument("--tasks", type=Path)
    result.add_argument("--keyword", action="append", help="临时覆盖搜索关键词，可重复传入")
    result.add_argument("--max-pages", type=int, help="临时覆盖每个关键词扫描页数")
    result.add_argument(
        "--send-resume", action="store_true",
        help="仅与 chat-check 一起使用，允许处理一条未读会话中的简历发送",
    )
    result.add_argument("--contact", default="", help="chat-check 仅处理联系人名称包含此文本的会话")
    result.add_argument("--max-conversations", type=int, help="chat-check 本次最多打开的未读会话数")
    result.add_argument("--dry-run", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "ui":
            return run_ui(ROOT, args.config.resolve())
        if args.command == "environment-check":
            return 0 if environment_check() else 1
        if args.dry_run:
            return dry_run(args.config, args.tasks)
        config = load_config(args.config)
        tasks_path = args.tasks
        tasks = load_tasks(tasks_path) if tasks_path else []
        if args.command == "run" and not tasks_path:
            if not config.search.output_file.exists():
                raise ConfigError(
                    f"没有扫描结果 {config.search.output_file}；请先执行 scan，或使用 --tasks"
                )
            tasks = load_tasks(config.search.output_file)
        store = ProgressStore(config.scheduler.progress_file)
        store.load()
        if args.command == "validate" or args.command is None:
            suffix = f"，已加载 {len(tasks)} 个显式任务" if tasks_path else "，运行时将使用 joblist 搜索"
            print(f"配置有效{suffix}。")
            return 0
        if args.command == "status":
            if not tasks and config.search.output_file.exists():
                tasks = load_tasks(config.search.output_file)
            pending = store.pending(tasks)
            print(f"任务总数 {len(tasks)}，剩余 {len(pending)}，今日成功 {store.success_count_today()}")
            return 0
        if not environment_check():
            print("本项目所需依赖不符合基线，拒绝启动真实浏览器。")
            return 2
        session = create_browser(config.browser)
        try:
            open_login_page(session)
            if args.command == "browser-check":
                print("Chrome 已启动，正在等待手动登录完成……")
                BossTaskExecutor(session.page, config).wait_for_login()
                print("登录状态检查通过。")
                return 0
            jobs_tab = session.page.latest_tab
            if args.command == "scan":
                BossTaskExecutor(jobs_tab, config).wait_for_login()
                search_config = config.search
                if args.keyword:
                    search_config = replace(search_config, keywords=tuple(args.keyword))
                if args.max_pages is not None:
                    if args.max_pages <= 0:
                        raise ConfigError("--max-pages 必须大于 0")
                    search_config = replace(search_config, max_pages_per_keyword=args.max_pages)
                scanner = BossJobScanner(jobs_tab, search_config)
                jobs = scanner.scan()
                tasks = jobs_to_tasks(jobs, config)
                save_tasks(config.search.output_file, tasks)
                print(f"[SEARCH] 已保存 {len(tasks)} 条任务：{config.search.output_file}")
                return 0
            if args.command == "run":
                placeholders = [
                    task for task in tasks
                    if "EXAMPLE" in task.job_url.upper() or "EXAMPLE" in task.job_id.upper()
                ]
                if placeholders:
                    raise ConfigError("真实运行拒绝 EXAMPLE 占位任务；请先执行 scan 或传入真实任务文件")
                if not tasks:
                    print("搜索后没有可执行岗位，结束运行。")
                    return 0
            reporter = LayeredReporter()
            record_store = RecordStore(config.storage.database_path)
            record_store.initialize()
            for task in tasks:
                record_store.upsert_job(task)

            executor = BossTaskExecutor(
                jobs_tab, config, tab_factory=session.page.new_tab
            )
            chat_monitor = None
            if config.chat and config.chat.enabled:
                chat_tab = session.page.new_tab(CHAT_URL)
                chat_monitor = ChatMonitor(
                    chat_tab, config.chat, record_store, reporter, config.resume
                )
                reporter.status("已建立一个固定聊天标签页；聊天检查与批量沟通共用主线程串行执行。")
            if args.command == "chat-check":
                if chat_monitor is None:
                    reporter.attention("聊天监控在配置中处于关闭状态。")
                    return 1
                result = chat_monitor.check(
                    force=True, allow_refresh=True, allow_resume_send=args.send_resume,
                    target_contact=args.contact,
                    max_conversations=args.max_conversations,
                )
                reporter.summary(
                    f"单次聊天检查结束：未读会话 {result.unread_conversations}，"
                    f"新增消息 {result.new_messages}，明确简历邀请 {result.explicit_invitations}，"
                    f"待人工判断 {result.manual_reviews}。"
                )
                return 0

            def before_task():
                if chat_monitor is not None:
                    chat_monitor.check(force=False, allow_refresh=True)

            def after_task(task, result):
                record_store.update_job_snapshot(task, **executor.last_job_snapshot)
                if chat_monitor is None or not config.chat.check_after_each_greeting:
                    return
                if result.status.value == "success":
                    reporter.status(f"任务 {task.task_id} 已完成，检查聊天列表同步状态。")
                    chat_monitor.check(force=True, allow_refresh=False)

            scheduler = TaskScheduler(
                config,
                store,
                PacingController(config.pacing),
                CsvOutput(config.output.result_csv, config.output.error_csv),
                executor.execute,
                before_task=before_task,
                after_task=after_task,
            )
            final_state = scheduler.run(tasks)
            report_md, _ = DailyReportGenerator(
                config.storage.database_path,
                config.output.result_csv,
                config.storage.reports_dir,
            ).write()
            reporter.summary(
                f"运行结束：成功 {final_state.success}，跳过 {final_state.skipped}，"
                f"失败尝试 {final_state.failed_attempts}，剩余 {final_state.remaining}；"
                f"每日报告：{report_md}"
            )
            return 0
        finally:
            session.quit()
    except (ConfigError, ProgressError, OSError, subprocess.SubprocessError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
