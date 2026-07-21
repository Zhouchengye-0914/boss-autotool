from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from urllib.parse import urlparse


class OperationType(str, Enum):
    COMMUNICATION = "communication"
    APPLICATION = "application"


class ResultStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    PAUSED = "paused"


@dataclass(frozen=True)
class JobTask:
    task_id: str
    job_url: str
    job_id: str
    greeting: str
    resume_name: str
    operation_type: OperationType
    job_title: str = ""
    company: str = ""
    job_category: str = ""
    job_description: str = ""
    match_score: float = 0.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "JobTask":
        if not isinstance(raw, dict):
            raise ValueError("任务必须是对象")
        job_id = str(raw.get("job_id") or "").strip()
        job_url = str(raw.get("job_url") or "").strip()
        if not job_url and job_id:
            job_url = f"https://www.zhipin.com/job_detail/{job_id}.html"
        if not job_url and not job_id:
            raise ValueError("job_url 与 job_id 至少提供一个")
        if job_url:
            parsed = urlparse(job_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"非法职位 URL: {job_url}")
        greeting = str(raw.get("greeting") or "").strip()
        resume_name = str(raw.get("resume_name") or "").strip()
        if not greeting:
            raise ValueError("greeting 不能为空")
        if not resume_name:
            raise ValueError("resume_name 不能为空")
        try:
            operation = OperationType(str(raw.get("operation_type") or "communication"))
        except ValueError as exc:
            raise ValueError("operation_type 必须是 communication 或 application") from exc
        task_id = str(raw.get("task_id") or "").strip()
        if not task_id:
            identity = f"{job_id}|{job_url}|{operation.value}|{resume_name}"
            task_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        return cls(
            task_id, job_url, job_id, greeting, resume_name, operation,
            str(raw.get("job_title") or raw.get("title") or "").strip(),
            str(raw.get("company") or "").strip(),
            str(raw.get("job_category") or raw.get("category") or "").strip(),
            str(raw.get("job_description") or raw.get("jd") or "").strip(),
            float(raw.get("match_score") or 0),
        )


@dataclass
class TaskResult:
    status: ResultStatus
    job_name: str = ""
    company: str = ""
    reason: str = ""
    attempt: int = 1
    screenshot_path: str = ""
    timestamp: datetime | None = None
    retryable: bool = True
