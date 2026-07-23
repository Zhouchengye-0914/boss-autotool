from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .config import AppConfig
from .models import JobTask, ResultStatus, TaskResult
from .monitor import ProgressMonitor, RunState
from .output import CsvOutput
from .pacing import PacingController
from .persistence import ProgressStore


class TaskScheduler:
    def __init__(
        self,
        config: AppConfig,
        store: ProgressStore,
        pacing: PacingController,
        output: CsvOutput,
        executor: Callable[[JobTask, int], TaskResult],
        before_task: Callable[[], Any] | None = None,
        after_task: Callable[[JobTask, TaskResult], Any] | None = None,
        verify_success: Callable[[JobTask, TaskResult], TaskResult] | None = None,
        on_attempt_result: Callable[[JobTask, TaskResult], Any] | None = None,
    ):
        self.config = config
        self.store = store
        self.pacing = pacing
        self.output = output
        self.executor = executor
        self.before_task = before_task
        self.after_task = after_task
        self.verify_success = verify_success
        self.on_attempt_result = on_attempt_result

    def run(self, tasks: list[JobTask]) -> RunState:
        pending = self.store.pending(tasks)
        used = self.store.success_count_today()
        state = RunState(
            total=len(tasks), remaining=len(pending),
            daily_remaining=max(0, self.config.scheduler.daily_success_limit - used),
        )
        monitor = ProgressMonitor(
            state, self.config.output.progress_report_interval_seconds
        )
        monitor.start()
        try:
            for task in pending:
                if self.store.success_count_today() >= self.config.scheduler.daily_success_limit:
                    state.status = "已达到每日成功上限"
                    break
                state.current_task = task.task_id
                if self.before_task is not None:
                    self.before_task()
                attempts = self.store.attempts(task.task_id)
                while attempts < self.config.scheduler.max_retries:
                    state.status = "等待执行"
                    self.pacing.wait_before_attempt()
                    attempts += 1
                    state.status = "页面操作"
                    result = self.executor(task, attempts)
                    result.attempt = attempts
                    if result.status is ResultStatus.SUCCESS and self.verify_success is not None:
                        result = self.verify_success(task, result)
                        result.attempt = attempts
                    if self.on_attempt_result is not None:
                        self.on_attempt_result(task, result)
                    if result.status is ResultStatus.SUCCESS:
                        self.store.record(task, "success", attempts, result.reason)
                        self.output.result(task, result)
                        self.pacing.record_success()
                        state.success += 1
                        state.remaining -= 1
                        state.daily_remaining -= 1
                        if self.after_task is not None:
                            self.after_task(task, result)
                        break
                    if result.status is ResultStatus.SKIPPED or not result.retryable:
                        self.store.record(task, "skipped", attempts, result.reason)
                        self.output.result(task, result)
                        self.output.error(task, result, attempts)
                        state.skipped += 1
                        state.remaining -= 1
                        if self.after_task is not None:
                            self.after_task(task, result)
                        break
                    self.store.record(task, "failed", attempts, result.reason)
                    self.output.result(task, result)
                    state.failed_attempts += 1
                    if attempts >= self.config.scheduler.max_retries:
                        result.status = ResultStatus.SKIPPED
                        self.store.record(task, "skipped", attempts, result.reason)
                        self.output.error(task, result, attempts)
                        state.skipped += 1
                        state.remaining -= 1
                        if self.after_task is not None:
                            self.after_task(task, result)
                print(monitor.snapshot())
            state.status = state.status if "上限" in state.status else "运行完成"
            return state
        finally:
            monitor.stop()
