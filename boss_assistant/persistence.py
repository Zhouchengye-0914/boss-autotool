from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .models import JobTask

SHANGHAI = ZoneInfo("Asia/Shanghai")


class ProgressError(RuntimeError):
    pass


def load_tasks(path: Path) -> list[JobTask]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProgressError(f"无法读取任务文件 {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise ProgressError("任务文件根节点必须是数组")
    tasks: list[JobTask] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        try:
            task = JobTask.from_dict(item)
        except ValueError as exc:
            raise ProgressError(f"第 {index} 个任务无效: {exc}") from exc
        if task.task_id in seen:
            print(f"警告：忽略重复任务 {task.task_id}")
            continue
        seen.add(task.task_id)
        tasks.append(task)
    return tasks


class ProgressStore:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {"schema_version": 1, "tasks": {}}

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProgressError(
                f"断点文件已损坏，已保留原文件，请人工处理 {self.path}: {exc}"
            ) from exc
        if not isinstance(loaded, dict) or not isinstance(loaded.get("tasks"), dict):
            raise ProgressError(f"断点文件结构无效: {self.path}")
        self.data = loaded

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def record(self, task: JobTask, status: str, attempts: int, reason: str = "") -> None:
        self.data["tasks"][task.task_id] = {
            "status": status,
            "attempts": attempts,
            "updated_at": datetime.now(SHANGHAI).isoformat(),
            "reason": reason,
            "job_url": task.job_url,
        }
        self.save()

    def get(self, task_id: str) -> dict[str, Any]:
        return dict(self.data["tasks"].get(task_id, {}))

    def is_terminal(self, task_id: str) -> bool:
        return self.get(task_id).get("status") in {"success", "skipped"}

    def attempts(self, task_id: str) -> int:
        return int(self.get(task_id).get("attempts", 0))

    def success_count_today(self, now: datetime | None = None) -> int:
        today = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI).date()
        count = 0
        for state in self.data["tasks"].values():
            if state.get("status") != "success":
                continue
            try:
                updated = datetime.fromisoformat(state["updated_at"]).astimezone(SHANGHAI)
            except (KeyError, TypeError, ValueError):
                continue
            count += updated.date() == today
        return count

    def pending(self, tasks: Iterable[JobTask]) -> list[JobTask]:
        return [task for task in tasks if not self.is_terminal(task.task_id)]

