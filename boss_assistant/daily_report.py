from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from .persistence import SHANGHAI


@dataclass
class DailyMetrics:
    date: str
    operation_attempts: int = 0
    communication_successes: int = 0
    application_successes: int = 0
    failed_attempts: int = 0
    skipped_tasks: int = 0
    stored_jobs: int = 0
    inbound_messages: int = 0
    explicit_resume_invitations: int = 0
    manual_reviews: int = 0


class DailyReportGenerator:
    def __init__(self, database_path: Path, result_csv: Path, reports_dir: Path):
        self.database_path = database_path
        self.result_csv = result_csv
        self.reports_dir = reports_dir

    def collect(self, day: str | None = None) -> DailyMetrics:
        day = day or datetime.now(SHANGHAI).date().isoformat()
        metrics = DailyMetrics(day)
        if self.result_csv.exists():
            with self.result_csv.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    timestamp = row.get("时间", "")
                    if not timestamp.startswith(day):
                        continue
                    metrics.operation_attempts += 1
                    result = row.get("结果", "")
                    operation = row.get("操作类型", "")
                    if result == "success":
                        if operation == "communication":
                            metrics.communication_successes += 1
                        elif operation == "application":
                            metrics.application_successes += 1
                    elif result == "failed":
                        metrics.failed_attempts += 1
                    elif result == "skipped":
                        metrics.skipped_tasks += 1
        if self.database_path.exists():
            with sqlite3.connect(self.database_path) as db:
                metrics.stored_jobs = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
                metrics.inbound_messages = db.execute(
                    "SELECT COUNT(*) FROM messages WHERE direction='inbound' AND observed_at LIKE ?",
                    (f"{day}%",),
                ).fetchone()[0]
                metrics.explicit_resume_invitations = db.execute(
                    "SELECT COUNT(*) FROM resume_invitations WHERE classification='explicit' AND created_at LIKE ?",
                    (f"{day}%",),
                ).fetchone()[0]
                metrics.manual_reviews = db.execute(
                    "SELECT COUNT(*) FROM resume_invitations WHERE classification='manual_review' AND created_at LIKE ?",
                    (f"{day}%",),
                ).fetchone()[0]
        return metrics

    def write(self, day: str | None = None) -> tuple[Path, Path]:
        metrics = self.collect(day)
        daily = self.reports_dir / "daily"
        daily.mkdir(parents=True, exist_ok=True)
        json_path = daily / f"{metrics.date}.json"
        md_path = daily / f"{metrics.date}.md"
        json_path.write_text(
            json.dumps(asdict(metrics), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        md_path.write_text(
            "\n".join(
                (
                    f"# BOSS 每日报告：{metrics.date}",
                    "",
                    "## 沟通执行",
                    "",
                    f"- 操作尝试：{metrics.operation_attempts}",
                    f"- 沟通成功记录：{metrics.communication_successes}",
                    f"- 投递成功记录：{metrics.application_successes}",
                    f"- 失败尝试：{metrics.failed_attempts}",
                    f"- 跳过任务：{metrics.skipped_tasks}",
                    "",
                    "## 聊天与简历邀请",
                    "",
                    f"- 已保存岗位：{metrics.stored_jobs}",
                    f"- HR 入站消息：{metrics.inbound_messages}",
                    f"- 明确简历邀请：{metrics.explicit_resume_invitations}",
                    f"- 待人工判断：{metrics.manual_reviews}",
                    "",
                    "> 该报告按审计记录统计；测试日志与生产日志应使用不同配置路径。",
                    "",
                )
            ),
            encoding="utf-8",
        )
        return md_path, json_path

