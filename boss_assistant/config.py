from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BrowserConfig:
    executable_path: Path
    profile_path: Path
    state_file: Path
    debug_port: int
    page_load_timeout: float
    element_timeout: float
    login_check_interval: float
    user_agents: tuple[str, ...]


@dataclass(frozen=True)
class SchedulerConfig:
    daily_success_limit: int
    max_retries: int
    tasks_file: Path
    progress_file: Path


@dataclass(frozen=True)
class PacingConfig:
    min_wait_seconds: float
    max_wait_seconds: float
    batch_size: int
    batch_min_rest_seconds: float
    batch_max_rest_seconds: float
    long_pause_probability: float
    long_pause_min_seconds: float
    long_pause_max_seconds: float


@dataclass(frozen=True)
class OutputConfig:
    result_csv: Path
    error_csv: Path
    screenshots_dir: Path
    progress_report_interval_seconds: float


@dataclass(frozen=True)
class ChatConfig:
    enabled: bool
    min_poll_seconds: float
    max_poll_seconds: float
    refresh_if_stale_seconds: float
    check_after_each_greeting: bool
    max_conversations_per_cycle: int


@dataclass(frozen=True)
class StorageConfig:
    database_path: Path
    reports_dir: Path
    jobs_database_path: Path
    communications_database_path: Path
    chat_database_path: Path


@dataclass(frozen=True)
class ResumeOptionConfig:
    key: str
    display_name: str
    option_index: int
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class DeepSeekConfig:
    enabled: bool
    endpoint: str
    model: str
    api_key_env: str
    timeout_seconds: float


@dataclass(frozen=True)
class ResumeConfig:
    auto_send_on_proactive_contact: bool
    auto_send_on_explicit_invitation: bool
    options: tuple[ResumeOptionConfig, ...]
    deepseek: DeepSeekConfig
    conversation_preferences: str


@dataclass(frozen=True)
class SearchConfig:
    city_code: str
    keywords: tuple[str, ...]
    max_pages_per_keyword: int
    listen_timeout_seconds: float
    scroll_min_seconds: float
    scroll_max_seconds: float
    min_salary_k: int
    exclude_title_keywords: tuple[str, ...]
    company_blacklist: tuple[str, ...]
    greeting: str
    output_file: Path
    match_threshold: float
    recommendation_limit: int


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    browser: BrowserConfig
    scheduler: SchedulerConfig
    pacing: PacingConfig
    output: OutputConfig
    chat: ChatConfig | None = None
    storage: StorageConfig | None = None
    resume: ResumeConfig | None = None
    search: SearchConfig | None = None


def _path(root: Path, value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} 必须是非空路径")
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def _number(data: dict[str, Any], key: str, *, positive: bool = False) -> float:
    value = data.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"{key} 必须是数字")
    if positive and value <= 0:
        raise ConfigError(f"{key} 必须大于 0")
    if not positive and value < 0:
        raise ConfigError(f"{key} 不能小于 0")
    return float(value)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"无法读取配置文件 {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("配置文件根节点必须是对象")

    root = config_path.parent
    browser = raw.get("browser", {})
    scheduler = raw.get("scheduler", {})
    pacing = raw.get("pacing", {})
    output = raw.get("output", {})
    chat = raw.get("chat_monitor", {
        "enabled": False,
        "min_poll_seconds": 60,
        "max_poll_seconds": 300,
        "refresh_if_stale_seconds": 180,
        "check_after_each_greeting": True,
        "max_conversations_per_cycle": 10,
    })
    storage = raw.get("storage", {
        "database_path": "./data/boss_assistant.db",
        "reports_dir": "./reports",
        "jobs_database_path": "./data/jobs.db",
        "communications_database_path": "./data/communications.db",
        "chat_database_path": "./data/chat.db",
    })
    resume = raw.get("resume_delivery", {
        "auto_send_on_proactive_contact": False,
        "auto_send_on_explicit_invitation": False,
        "options": [
            {"key": "general", "display_name": "", "option_index": 0, "keywords": ["数据运营"]},
            {"key": "ai", "display_name": "", "option_index": 1, "keywords": ["AI"]},
            {"key": "data", "display_name": "", "option_index": 2, "keywords": ["数据分析"]},
        ],
        "deepseek": {"enabled": False},
        "conversation_preferences": "",
    })
    search = raw.get("search", {
        "city_code": "101210100", "keywords": ["数据分析"],
        "max_pages_per_keyword": 5, "listen_timeout_seconds": 15,
        "scroll_min_seconds": 5, "scroll_max_seconds": 10,
        "min_salary_k": 8, "exclude_title_keywords": [], "company_blacklist": [],
        "greeting": "您好，我对该岗位很感兴趣，希望进一步沟通。",
        "output_file": "./data/tasks.scanned.json",
        "match_threshold": 58,
        "recommendation_limit": 12,
    })
    if not all(isinstance(v, dict) for v in (browser, scheduler, pacing, output, chat, storage, resume, search)):
        raise ConfigError("browser/scheduler/pacing/output 必须是对象")

    user_agents = browser.get("user_agents")
    if not isinstance(user_agents, list) or not user_agents or not all(
        isinstance(item, str) and item.strip() for item in user_agents
    ):
        raise ConfigError("browser.user_agents 必须是非空字符串列表")

    debug_port = int(_number(browser, "debug_port", positive=True))
    if not 1 <= debug_port <= 65535:
        raise ConfigError("debug_port 必须在 1-65535 之间")

    normal_min = _number(pacing, "min_wait_seconds")
    normal_max = _number(pacing, "max_wait_seconds")
    batch_min = _number(pacing, "batch_min_rest_seconds")
    batch_max = _number(pacing, "batch_max_rest_seconds")
    long_min = _number(pacing, "long_pause_min_seconds")
    long_max = _number(pacing, "long_pause_max_seconds")
    if normal_max < normal_min or batch_max < batch_min or long_max < long_min:
        raise ConfigError("所有最大等待时间必须大于或等于对应最小值")
    probability = _number(pacing, "long_pause_probability")
    if probability > 1:
        raise ConfigError("long_pause_probability 必须在 0-1 之间")

    chat_min = _number(chat, "min_poll_seconds", positive=True)
    chat_max = _number(chat, "max_poll_seconds", positive=True)
    if chat_max < chat_min:
        raise ConfigError("chat_monitor.max_poll_seconds 必须大于等于 min_poll_seconds")

    resume_options_raw = resume.get("options", [])
    if not isinstance(resume_options_raw, list) or len(resume_options_raw) != 3:
        raise ConfigError("resume_delivery.options 必须恰好配置三份简历")
    resume_options: list[ResumeOptionConfig] = []
    for index, item in enumerate(resume_options_raw):
        if not isinstance(item, dict):
            raise ConfigError("每个简历选项必须是对象")
        keywords = item.get("keywords", [])
        if not isinstance(keywords, list) or not all(isinstance(x, str) for x in keywords):
            raise ConfigError("简历 keywords 必须是字符串列表")
        resume_options.append(ResumeOptionConfig(
            key=str(item.get("key") or f"resume_{index + 1}"),
            display_name=str(item.get("display_name") or ""),
            option_index=int(item.get("option_index", index)),
            keywords=tuple(keywords),
        ))
    deepseek_raw = resume.get("deepseek", {})
    if not isinstance(deepseek_raw, dict):
        raise ConfigError("resume_delivery.deepseek 必须是对象")
    search_keywords = search.get("keywords", [])
    if not isinstance(search_keywords, list) or not all(
        isinstance(item, str) and item.strip() for item in search_keywords
    ):
        raise ConfigError("search.keywords 必须是字符串列表，可为空")
    scroll_min = _number(search, "scroll_min_seconds")
    scroll_max = _number(search, "scroll_max_seconds")
    if scroll_max < scroll_min:
        raise ConfigError("search.scroll_max_seconds 必须大于等于 scroll_min_seconds")

    return AppConfig(
        project_root=root,
        browser=BrowserConfig(
            executable_path=_path(root, browser.get("executable_path"), "executable_path"),
            profile_path=_path(root, browser.get("profile_path"), "profile_path"),
            state_file=_path(root, browser.get("state_file"), "state_file"),
            debug_port=debug_port,
            page_load_timeout=_number(browser, "page_load_timeout", positive=True),
            element_timeout=_number(browser, "element_timeout", positive=True),
            login_check_interval=_number(browser, "login_check_interval", positive=True),
            user_agents=tuple(user_agents),
        ),
        scheduler=SchedulerConfig(
            daily_success_limit=int(_number(scheduler, "daily_success_limit", positive=True)),
            max_retries=int(_number(scheduler, "max_retries", positive=True)),
            tasks_file=_path(root, scheduler.get("tasks_file"), "tasks_file"),
            progress_file=_path(root, scheduler.get("progress_file"), "progress_file"),
        ),
        pacing=PacingConfig(
            min_wait_seconds=normal_min,
            max_wait_seconds=normal_max,
            batch_size=int(_number(pacing, "batch_size", positive=True)),
            batch_min_rest_seconds=batch_min,
            batch_max_rest_seconds=batch_max,
            long_pause_probability=probability,
            long_pause_min_seconds=long_min,
            long_pause_max_seconds=long_max,
        ),
        output=OutputConfig(
            result_csv=_path(root, output.get("result_csv"), "result_csv"),
            error_csv=_path(root, output.get("error_csv"), "error_csv"),
            screenshots_dir=_path(root, output.get("screenshots_dir"), "screenshots_dir"),
            progress_report_interval_seconds=_number(
                output, "progress_report_interval_seconds", positive=True
            ),
        ),
        chat=ChatConfig(
            enabled=bool(chat.get("enabled", True)),
            min_poll_seconds=chat_min,
            max_poll_seconds=chat_max,
            refresh_if_stale_seconds=_number(chat, "refresh_if_stale_seconds", positive=True),
            check_after_each_greeting=bool(chat.get("check_after_each_greeting", True)),
            max_conversations_per_cycle=int(
                _number(chat, "max_conversations_per_cycle", positive=True)
            ),
        ),
        storage=StorageConfig(
            database_path=_path(root, storage.get("database_path"), "database_path"),
            reports_dir=_path(root, storage.get("reports_dir"), "reports_dir"),
            jobs_database_path=_path(
                root, storage.get("jobs_database_path", "./data/jobs.db"), "jobs_database_path"
            ),
            communications_database_path=_path(
                root, storage.get("communications_database_path", "./data/communications.db"),
                "communications_database_path",
            ),
            chat_database_path=_path(
                root, storage.get("chat_database_path", "./data/chat.db"), "chat_database_path"
            ),
        ),
        resume=ResumeConfig(
            auto_send_on_proactive_contact=bool(resume.get("auto_send_on_proactive_contact", True)),
            auto_send_on_explicit_invitation=bool(resume.get("auto_send_on_explicit_invitation", True)),
            options=tuple(resume_options),
        deepseek=DeepSeekConfig(
                enabled=bool(deepseek_raw.get("enabled", False)),
                endpoint=str(deepseek_raw.get("endpoint") or "https://api.deepseek.com/chat/completions"),
                model=str(deepseek_raw.get("model") or "deepseek-chat"),
                api_key_env=str(deepseek_raw.get("api_key_env") or "DEEPSEEK_API_KEY"),
                timeout_seconds=float(deepseek_raw.get("timeout_seconds", 20)),
            ),
            conversation_preferences=str(resume.get("conversation_preferences") or "").strip(),
        ),
        search=SearchConfig(
            city_code=str(search.get("city_code") or "101210100"),
            keywords=tuple(item.strip() for item in search_keywords),
            max_pages_per_keyword=int(_number(search, "max_pages_per_keyword", positive=True)),
            listen_timeout_seconds=_number(search, "listen_timeout_seconds", positive=True),
            scroll_min_seconds=scroll_min,
            scroll_max_seconds=scroll_max,
            min_salary_k=int(_number(search, "min_salary_k")),
            exclude_title_keywords=tuple(str(x) for x in search.get("exclude_title_keywords", [])),
            company_blacklist=tuple(str(x) for x in search.get("company_blacklist", [])),
            greeting=str(search.get("greeting") or "").strip(),
            output_file=_path(root, search.get("output_file"), "search.output_file"),
            match_threshold=_number(search, "match_threshold"),
            recommendation_limit=int(_number(search, "recommendation_limit", positive=True)),
        ),
    )
