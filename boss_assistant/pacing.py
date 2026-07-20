from __future__ import annotations

import random
import time
from collections.abc import Callable

from .config import PacingConfig


class PacingController:
    def __init__(
        self,
        config: PacingConfig,
        *,
        rng: random.Random | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        reporter: Callable[[str], None] = print,
    ):
        self.config = config
        self.rng = rng or random.Random()
        self.sleeper = sleeper
        self.reporter = reporter
        self.run_successes = 0
        self._batch_due = False

    def _sleep(self, seconds: float, reason: str) -> None:
        self.reporter(f"{reason}：{seconds:.1f} 秒")
        self.sleeper(seconds)

    def wait_before_attempt(self) -> None:
        if self._batch_due:
            seconds = self.rng.uniform(
                self.config.batch_min_rest_seconds, self.config.batch_max_rest_seconds
            )
            self._sleep(seconds, "批次休息")
            self._batch_due = False
        seconds = self.rng.uniform(
            self.config.min_wait_seconds, self.config.max_wait_seconds
        )
        self._sleep(seconds, "任务前等待")
        if self.rng.random() < self.config.long_pause_probability:
            seconds = self.rng.uniform(
                self.config.long_pause_min_seconds, self.config.long_pause_max_seconds
            )
            self._sleep(seconds, "随机长停顿")

    def record_success(self) -> None:
        self.run_successes += 1
        if self.run_successes % self.config.batch_size == 0:
            self._batch_due = True

