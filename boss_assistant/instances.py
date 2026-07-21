from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from .config import AppConfig, ConfigError


def isolated_config(
    config: AppConfig, instance: str, port_offset: int = 0,
    worker_index: int = 0, worker_count: int = 1,
) -> AppConfig:
    """隔离浏览器与运行文件；业务三库保持共享，以便统一统计和幂等判断。"""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", instance).strip("-")
    if not safe:
        raise ConfigError("instance 必须包含字母、数字、下划线或短横线")
    if not 0 <= port_offset <= 1000:
        raise ConfigError("port_offset 必须在 0-1000 之间")
    if worker_count < 1 or not 0 <= worker_index < worker_count:
        raise ConfigError("worker_index/worker_count 无效")
    base = config.project_root / "data" / "instances" / safe
    log_base = config.project_root / "logs" / "instances" / safe
    daily_base = config.scheduler.daily_success_limit // worker_count
    daily_limit = daily_base + (1 if worker_index < config.scheduler.daily_success_limit % worker_count else 0)
    browser = replace(
        config.browser,
        profile_path=base / "browser_profile",
        state_file=base / "browser_state.json",
        debug_port=config.browser.debug_port + port_offset,
    )
    scheduler = replace(
        config.scheduler,
        daily_success_limit=max(1, daily_limit),
        progress_file=base / "progress.json",
    )
    output = replace(
        config.output,
        result_csv=log_base / "operation_results.csv",
        error_csv=log_base / "error_log.csv",
        screenshots_dir=base / "screenshots",
    )
    storage = replace(
        config.storage,
        database_path=base / "boss_assistant.db",
        reports_dir=base / "reports",
    )
    return replace(config, browser=browser, scheduler=scheduler, output=output, storage=storage)
