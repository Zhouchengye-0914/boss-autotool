from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import JobTask
from .persistence import SHANGHAI


@dataclass(frozen=True)
class MessageRecord:
    conversation_id: str
    contact_name: str
    job_id: str
    job_title: str
    company: str
    direction: str
    text: str
    observed_at: datetime

    @property
    def fingerprint(self) -> str:
        raw = "|".join(
            (self.conversation_id, self.direction, self.text, self.observed_at.strftime("%Y-%m-%d"))
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class RecordStore:
    """SQLite 审计库。仅保存职位和沟通业务数据，不保存登录凭据。"""

    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    task_id TEXT PRIMARY KEY,
                    job_id TEXT, job_url TEXT, job_title TEXT, company TEXT,
                    category TEXT, jd TEXT, resume_name TEXT,
                    first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    fingerprint TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL, contact_name TEXT,
                    job_id TEXT, job_title TEXT, company TEXT,
                    direction TEXT NOT NULL, text TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS resume_invitations (
                    fingerprint TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL, classification TEXT NOT NULL,
                    matched_keyword TEXT, status TEXT NOT NULL,
                    resume_name TEXT, created_at TEXT NOT NULL,
                    FOREIGN KEY(fingerprint) REFERENCES messages(fingerprint)
                );
                CREATE TABLE IF NOT EXISTS chat_checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    checked_at TEXT NOT NULL, unread_count INTEGER NOT NULL,
                    new_messages INTEGER NOT NULL, invitations INTEGER NOT NULL,
                    note TEXT
                );
                CREATE TABLE IF NOT EXISTS resume_deliveries (
                    conversation_id TEXT PRIMARY KEY, job_title TEXT, company TEXT,
                    resume_key TEXT NOT NULL, resume_name TEXT, status TEXT NOT NULL,
                    reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def upsert_job(self, task: JobTask) -> None:
        now = datetime.now(SHANGHAI).isoformat()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO jobs(task_id, job_id, job_url, job_title, company, category, jd,
                                 resume_name, first_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    job_id=excluded.job_id, job_url=excluded.job_url,
                    job_title=excluded.job_title, company=excluded.company,
                    category=excluded.category, jd=excluded.jd,
                    resume_name=excluded.resume_name, updated_at=excluded.updated_at
                """,
                (task.task_id, task.job_id, task.job_url, task.job_title, task.company,
                 task.job_category, task.job_description, task.resume_name, now, now),
            )

    def add_message(self, message: MessageRecord) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO messages
                (fingerprint, conversation_id, contact_name, job_id, job_title, company,
                 direction, text, observed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message.fingerprint, message.conversation_id, message.contact_name,
                 message.job_id, message.job_title, message.company, message.direction,
                 message.text, message.observed_at.isoformat()),
            )
            return cursor.rowcount == 1

    def update_job_snapshot(
        self, task: JobTask, *, job_title: str = "", company: str = "", job_description: str = ""
    ) -> None:
        self.upsert_job(task)
        with self._connect() as db:
            db.execute(
                """
                UPDATE jobs SET
                    job_title=CASE WHEN ? != '' THEN ? ELSE job_title END,
                    company=CASE WHEN ? != '' THEN ? ELSE company END,
                    jd=CASE WHEN ? != '' THEN ? ELSE jd END,
                    updated_at=?
                WHERE task_id=?
                """,
                (job_title, job_title, company, company, job_description, job_description,
                 datetime.now(SHANGHAI).isoformat(), task.task_id),
            )

    def add_invitation(
        self, message: MessageRecord, classification: str, keyword: str, resume_name: str = ""
    ) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO resume_invitations
                (fingerprint, conversation_id, classification, matched_keyword, status,
                 resume_name, created_at) VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (message.fingerprint, message.conversation_id, classification, keyword,
                 resume_name, datetime.now(SHANGHAI).isoformat()),
            )
            return cursor.rowcount == 1

    def record_chat_check(self, unread: int, new_messages: int, invitations: int, note: str = "") -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO chat_checks(checked_at, unread_count, new_messages, invitations, note) VALUES (?, ?, ?, ?, ?)",
                (datetime.now(SHANGHAI).isoformat(), unread, new_messages, invitations, note),
            )

    def resume_sent(self, conversation_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT status FROM resume_deliveries WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            return bool(row and row[0] == "success")

    def record_resume_delivery(
        self, conversation_id: str, job_title: str, company: str, resume_key: str,
        resume_name: str, status: str, reason: str = "",
    ) -> None:
        now = datetime.now(SHANGHAI).isoformat()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO resume_deliveries
                (conversation_id, job_title, company, resume_key, resume_name, status, reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    resume_key=excluded.resume_key, resume_name=excluded.resume_name,
                    status=excluded.status, reason=excluded.reason, updated_at=excluded.updated_at
                """,
                (conversation_id, job_title, company, resume_key, resume_name,
                 status, reason, now, now),
            )
