from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .models import JobTask, TaskResult
from .persistence import SHANGHAI


class CsvOutput:
    RESULT_HEADERS = (
        "时间", "任务ID", "职位名称", "公司", "职位URL/ID", "操作类型",
        "尝试次数", "结果", "失败原因", "截图路径",
    )
    ERROR_HEADERS = (
        "时间", "任务ID", "职位URL/ID", "职位名称", "公司",
        "总尝试次数", "最终失败原因", "最后截图路径",
    )

    def __init__(self, result_path: Path, error_path: Path):
        self.result_path = result_path
        self.error_path = error_path

    def _append(self, path: Path, headers: tuple[str, ...], row: list[object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not path.exists() or path.stat().st_size == 0
        with path.open("a", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            if new_file:
                writer.writerow(headers)
            writer.writerow(row)
            handle.flush()

    def result(self, task: JobTask, result: TaskResult) -> None:
        self._append(
            self.result_path,
            self.RESULT_HEADERS,
            [
                datetime.now(SHANGHAI).isoformat(), task.task_id, result.job_name,
                result.company, task.job_url or task.job_id, task.operation_type.value,
                result.attempt, result.status.value, result.reason, result.screenshot_path,
            ],
        )

    def error(self, task: JobTask, result: TaskResult, attempts: int) -> None:
        self._append(
            self.error_path,
            self.ERROR_HEADERS,
            [
                datetime.now(SHANGHAI).isoformat(), task.task_id, task.job_url or task.job_id,
                result.job_name, result.company, attempts, result.reason, result.screenshot_path,
            ],
        )
