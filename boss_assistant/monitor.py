from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable

from .persistence import SHANGHAI


class ReportLevel(str, Enum):
    STATUS = "STATUS"
    PROGRESS = "PROGRESS"
    CHAT = "CHAT"
    ATTENTION = "ATTENTION"
    SUMMARY = "SUMMARY"
    DAILY = "DAILY"


@dataclass(frozen=True)
class ReportEvent:
    level: ReportLevel
    message: str
    timestamp: datetime


class LayeredReporter:
    """分层输出运行事件；详细业务数据由 SQLite 和 CSV 持久化。"""

    def __init__(self, writer: Callable[[str], None] = print):
        self.writer = writer
        self.events: list[ReportEvent] = []

    def emit(self, level: ReportLevel, message: str) -> ReportEvent:
        event = ReportEvent(level, message, datetime.now(SHANGHAI))
        self.events.append(event)
        self.writer(f"【{level.value}】{message}")
        return event

    def status(self, message: str) -> ReportEvent:
        return self.emit(ReportLevel.STATUS, message)

    def progress(self, message: str) -> ReportEvent:
        return self.emit(ReportLevel.PROGRESS, message)

    def chat(self, message: str) -> ReportEvent:
        return self.emit(ReportLevel.CHAT, message)

    def attention(self, message: str) -> ReportEvent:
        return self.emit(ReportLevel.ATTENTION, message)

    def summary(self, message: str) -> ReportEvent:
        return self.emit(ReportLevel.SUMMARY, message)


@dataclass
class RunState:
    total: int = 0
    success: int = 0
    skipped: int = 0
    failed_attempts: int = 0
    remaining: int = 0
    daily_remaining: int = 0
    current_task: str = ""
    status: str = "初始化"
    started_at: float = field(default_factory=time.monotonic)


class ProgressMonitor:
    def __init__(self, state: RunState, interval: float, reporter=print):
        self.state = state
        self.interval = interval
        self.reporter = reporter
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def snapshot(self) -> str:
        elapsed = time.monotonic() - self.state.started_at
        return (
            f"进度：成功 {self.state.success}，跳过 {self.state.skipped}，"
            f"失败尝试 {self.state.failed_attempts}，剩余 {self.state.remaining}，"
            f"今日额度 {self.state.daily_remaining}，耗时 {elapsed / 3600:.2f} 小时，"
            f"状态 {self.state.status}，当前任务 {self.state.current_task or '-'}"
        )

    def start(self) -> None:
        def run() -> None:
            while not self._stop.wait(self.interval):
                self.reporter(self.snapshot())
        self._thread = threading.Thread(target=run, name="progress-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
