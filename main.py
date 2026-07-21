from __future__ import annotations

import argparse
import hashlib
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
from boss_assistant.monitor import LayeredReporter
from boss_assistant.daily_report import DailyReportGenerator
from boss_assistant.scanner import BossJobScanner, jobs_to_tasks, save_tasks
from boss_assistant.ui import run_ui
from boss_assistant.instances import isolated_config
from boss_assistant.talent_data import JobsDatabase, ProfileReader, parse_job_taxonomy
from boss_assistant.talent_data import CommunicationsDatabase, ChatDatabase
from boss_assistant.matching import match_job, recommend_titles
from boss_assistant.deepseek import DeepSeekError, DeepSeekResumeMatcher
from boss_assistant.workflow import ScanCheckpoint

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.yaml"
FREEZE_FILE = ROOT / "environment-freeze.txt"
REQUIRED_PYTHON = (3, 10, 1)
PROJECT_DEPENDENCIES = {"DrissionPage": "4.1.1.4", "PyYAML": "6.0.2"}
RESUME_URL = "https://www.zhipin.com/web/geek/resume"


def capture_profile(session, config, jobs_db: JobsDatabase):
    tab = session.page.new_tab(RESUME_URL)
    try:
        tab.wait(3)
        snapshot = ProfileReader().capture(tab)
        if not snapshot.sections:
            print("[PROFILE] 未读取到在线简历字段，继续使用数据库中的最近快照。")
            return jobs_db.latest_profile()
        changed = jobs_db.save_profile(snapshot)
        print(f"[PROFILE] 在线简历快照已{'更新' if changed else '确认未变化'}。")
        return snapshot
    finally:
        try: tab.close()
        except Exception: pass


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
        choices=["ui", "validate", "browser-check", "profile-sync", "chat-check", "scan", "run", "status", "environment-check"],
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
    result.add_argument("--instance", default="", help="独立运行实例名称，用于隔离浏览器和运行数据")
    result.add_argument("--port-offset", type=int, default=0, help="实例调试端口相对配置端口的偏移")
    result.add_argument("--worker-index", type=int, default=0)
    result.add_argument("--worker-count", type=int, default=1)
    result.add_argument("--daily-limit", type=int, help="为独立实例覆盖每日成功上限")
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
        if args.instance:
            config = isolated_config(
                config, args.instance, args.port_offset, args.worker_index, args.worker_count
            )
        if args.daily_limit is not None:
            if args.daily_limit <= 0:
                raise ConfigError("--daily-limit 必须大于 0")
            config = replace(
                config,
                scheduler=replace(config.scheduler, daily_success_limit=args.daily_limit),
            )
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
            jobs_db = JobsDatabase(config.storage.jobs_database_path)
            jobs_db.initialize()
            communications_db = CommunicationsDatabase(config.storage.communications_database_path)
            communications_db.initialize()
            chat_db = ChatDatabase(config.storage.chat_database_path)
            chat_db.initialize()
            chat_db.migrate_legacy(config.storage.database_path)
            taxonomy_path = config.project_root / "data" / "job.md"
            if taxonomy_path.exists():
                jobs_db.replace_taxonomy(parse_job_taxonomy(taxonomy_path))
            profile = capture_profile(session, config, jobs_db)
            if args.command == "profile-sync":
                print("在线简历同步完成。" if profile else "在线简历同步失败。")
                return 0 if profile else 1
            if args.command == "scan":
                BossTaskExecutor(jobs_tab, config).wait_for_login()
                search_config = config.search
                if args.keyword:
                    search_config = replace(search_config, keywords=tuple(args.keyword))
                if args.max_pages is not None:
                    if args.max_pages <= 0:
                        raise ConfigError("--max-pages 必须大于 0")
                    search_config = replace(search_config, max_pages_per_keyword=args.max_pages)
                scanner = BossJobScanner(
                    jobs_tab, search_config,
                    checkpoint=ScanCheckpoint(config.project_root / "data" / "scan_checkpoint.json"),
                )
                jobs = scanner.scan()
                eligible_jobs = []
                for job in scanner.last_raw_jobs:
                    matched = match_job(job, profile, search_config.match_threshold) if profile else None
                    score = matched.score if matched else 0.0
                    reasons = list(matched.reasons) if matched else ["缺少在线简历快照"]
                    eligible = bool(matched and matched.eligible and job in jobs)
                    jobs_db.upsert_job(job, score, reasons, eligible)
                    if eligible:
                        job["match_score"] = score
                        eligible_jobs.append(job)
                tasks = jobs_to_tasks(eligible_jobs, config)
                if profile and not search_config.keywords:
                    suggestions = recommend_titles(
                        profile, parse_job_taxonomy(taxonomy_path), search_config.recommendation_limit
                    ) if taxonomy_path.exists() else []
                    print("[PROFILE] 推荐搜索职位：" + "、".join(suggestions))
                if profile and config.resume.deepseek.enabled:
                    assistant = DeepSeekResumeMatcher(config.resume.deepseek)
                    personalized = list(tasks)
                    save_tasks(config.search.output_file, personalized)
                    safe_profile = "\n".join(
                        text for name, text in profile.sections.items() if name != "personal"
                    )
                    for index, task in enumerate(tasks):
                        source = "\n".join(("greeting-v1", profile.fingerprint,
                                            config.resume.deepseek.model,
                                            task.task_id, task.job_title, task.company,
                                            task.job_description, task.job_category))
                        cache_key = hashlib.sha256(source.encode("utf-8")).hexdigest()
                        try:
                            greeting = jobs_db.cached_greeting(cache_key)
                            if greeting:
                                print(f"[AI] {index + 1}/{len(tasks)} 使用缓存：{task.job_title}")
                            else:
                                greeting = assistant.greeting(
                                    safe_profile, "\n".join((task.job_title, task.company,
                                                            task.job_description, task.job_category))
                                )
                                if greeting:
                                    jobs_db.save_greeting(cache_key, task.task_id, profile.fingerprint,
                                                          greeting, config.resume.deepseek.model)
                                print(f"[AI] {index + 1}/{len(tasks)} 已生成：{task.job_title}")
                            personalized[index] = replace(task, greeting=greeting or task.greeting)
                        except DeepSeekError as exc:
                            print(f"[AI] {task.task_id} 招呼语生成失败，使用默认文案：{exc}")
                        save_tasks(config.search.output_file, personalized)
                    tasks = personalized
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
            executor = BossTaskExecutor(
                jobs_tab, config, tab_factory=session.page.new_tab
            )
            chat_monitor = None
            if config.chat and config.chat.enabled:
                chat_tab = session.page.new_tab(CHAT_URL)
                chat_monitor = ChatMonitor(
                    chat_tab, config.chat, chat_db, reporter, config.resume,
                    chat_db=chat_db,
                    profile_text=("\n".join(
                        value for key, value in profile.sections.items() if key != "personal"
                    ) if profile else ""),
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
                    chat_monitor.check(
                        force=False, allow_refresh=True, allow_resume_send=False
                    )

            def after_task(task, result):
                record_store.update_job_snapshot(task, **executor.last_job_snapshot)
                if chat_monitor is None or not config.chat.check_after_each_greeting:
                    return
                if result.status.value == "success":
                    reporter.status(f"任务 {task.task_id} 已完成，检查聊天列表同步状态。")
                    chat_monitor.check(
                        force=True, allow_refresh=False, allow_resume_send=False
                    )

            def verify_success(task, result):
                if chat_monitor is None or task.operation_type.value != "communication":
                    return result
                confirmed, reason = chat_monitor.verify_greeting_sent(task)
                if confirmed:
                    result.reason = reason
                    return result
                return type(result)(
                    status=type(result.status).FAILED,
                    job_name=result.job_name,
                    company=result.company,
                    reason=reason,
                    attempt=result.attempt,
                    retryable=True,
                )

            def record_communication(task, result):
                status = "verified" if result.status.value == "success" else result.status.value
                communications_db.record(
                    task_id=task.task_id, job_id=task.job_id, job_url=task.job_url,
                    job_title=result.job_name or task.job_title,
                    company=result.company or task.company, greeting=task.greeting,
                    source="deepseek" if task.greeting != config.search.greeting else "template",
                    score=task.match_score, status=status, attempts=result.attempt,
                    reason=result.reason,
                )

            scheduler = TaskScheduler(
                config,
                store,
                PacingController(config.pacing),
                CsvOutput(config.output.result_csv, config.output.error_csv),
                executor.execute,
                before_task=before_task,
                after_task=after_task,
                verify_success=verify_success,
                on_attempt_result=record_communication,
            )
            final_state = scheduler.run(tasks)
            report_md, _ = DailyReportGenerator(
                config.storage.database_path,
                config.output.result_csv,
                config.storage.reports_dir,
                jobs_database_path=config.storage.jobs_database_path,
                chat_database_path=config.storage.chat_database_path,
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
