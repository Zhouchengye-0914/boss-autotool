from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .persistence import SHANGHAI


ACTIVE_PHASES = {"scanning", "communicating", "monitoring"}


@dataclass
class WorkflowState:
    schema_version: int = 1
    action: str = ""
    phase: str = "idle"
    started_at: str = ""
    updated_at: str = ""
    last_error: str = ""
    resumable: bool = False


class WorkflowStateStore:
    """原子保存 UI 工作流状态，用于进程被关闭后的恢复提示。"""

    def __init__(self, path: Path):
        self.path = path

    def load(self, *, recover_interrupted: bool = False) -> WorkflowState:
        if not self.path.exists():
            return WorkflowState()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            state = WorkflowState(**{key: raw.get(key, value) for key, value in asdict(WorkflowState()).items()})
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError(f"工作流断点损坏，已保留原文件：{self.path}: {exc}") from exc
        if recover_interrupted and state.phase in ACTIVE_PHASES:
            state.phase = "interrupted"
            state.resumable = True
            state.last_error = "上次运行未正常结束，可从已有搜索/沟通断点继续"
            self.save(state)
        return state

    def update(self, action: str, phase: str, *, error: str = "", resumable: bool = False) -> WorkflowState:
        previous = self.load()
        now = datetime.now(SHANGHAI).isoformat()
        state = WorkflowState(
            action=action or previous.action,
            phase=phase,
            started_at=previous.started_at if previous.action == action and previous.started_at else now,
            updated_at=now,
            last_error=error,
            resumable=resumable,
        )
        self.save(state)
        return state

    def save(self, state: WorkflowState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(asdict(state), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()


class ScanCheckpoint:
    """保存搜索结果和完成的关键词；中断的关键词重扫并按 job_id 去重。"""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {
            "schema_version": 1, "status": "idle", "queries": [],
            "completed_queries": [], "current_query": "", "current_page": 0, "jobs": {},
        }

    def load(self, queries: tuple[str, ...]) -> None:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"搜索断点损坏，已保留原文件：{self.path}: {exc}") from exc
            if raw.get("queries") == list(queries) and isinstance(raw.get("jobs"), dict):
                self.data = raw
                return
        self.data["queries"] = list(queries)
        self.save()

    def save_page(self, query: str, page: int, jobs: list[dict[str, Any]]) -> None:
        self.data.update(status="scanning", current_query=query, current_page=page)
        for job in jobs:
            self.data["jobs"][job["job_id"]] = job
        self.save()

    def complete_query(self, query: str) -> None:
        if query not in self.data["completed_queries"]:
            self.data["completed_queries"].append(query)
        self.save()

    def complete(self) -> None:
        self.data.update(status="completed", current_query="", current_page=0)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()
