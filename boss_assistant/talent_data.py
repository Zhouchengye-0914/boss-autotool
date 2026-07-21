from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .persistence import SHANGHAI


@dataclass(frozen=True)
class JobTaxonomyItem:
    code: int
    major: str
    category: str
    title: str


@dataclass(frozen=True)
class ProfileSnapshot:
    fingerprint: str
    captured_at: str
    sections: dict[str, str]
    attachment_names: tuple[str, ...]

    @property
    def full_text(self) -> str:
        return "\n".join(self.sections.values())


def parse_job_taxonomy(path: Path) -> list[JobTaxonomyItem]:
    items: list[JobTaxonomyItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = [part.strip() for part in line.split("\t")]
        if len(parts) != 4 or not parts[0].isdigit():
            continue
        items.append(JobTaxonomyItem(int(parts[0]), parts[1], parts[2], parts[3]))
    return items


class ProfileReader:
    SELECTORS = {
        "personal": "css:.resume-userinfo",
        "summary": "css:.resume-summary",
        "expectations": "css:.resume-purpose",
        "work": "css:.resume-history",
        "projects": "css:.resume-project",
        "education": "css:.resume-education",
        "certificates": "css:.resume-certification",
        "organizations": "css:.resume-clubExp",
        "volunteer": "css:.resume-volunteer",
        "skills": "css:.resume-professional-skill",
    }

    def capture(self, page: Any) -> ProfileSnapshot:
        sections: dict[str, str] = {}
        for name, locator in self.SELECTORS.items():
            try:
                element = page.ele(locator, timeout=1)
                text = (element.text or "").strip() if element else ""
            except Exception:
                text = ""
            if text:
                sections[name] = re.sub(r"\n编辑(?:删除)?(?=\n|$)", "", text)
        attachments: list[str] = []
        try:
            for element in page.eles("css:.resume-attachment [class*='name']", timeout=1):
                text = (element.text or "").strip()
                if text and text not in attachments:
                    attachments.append(text)
        except Exception:
            pass
        if not attachments:
            try:
                box = page.ele("css:.resume-attachment", timeout=1)
                text = box.text or "" if box else ""
                attachments = re.findall(r"[^\n]+\.(?:pdf|docx?|png|jpg)", text, re.I)
            except Exception:
                pass
        normalized = json.dumps({"sections": sections, "attachments": attachments},
                                ensure_ascii=False, sort_keys=True)
        fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return ProfileSnapshot(fingerprint, datetime.now(SHANGHAI).isoformat(),
                               sections, tuple(attachments))


class JobsDatabase:
    def __init__(self, path: Path): self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS taxonomy(
                code INTEGER PRIMARY KEY, major TEXT NOT NULL, category TEXT NOT NULL,
                title TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profile_snapshots(
                fingerprint TEXT PRIMARY KEY, captured_at TEXT NOT NULL,
                sections_json TEXT NOT NULL, attachments_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs(
                job_id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT, company TEXT,
                salary TEXT, degree TEXT, experience TEXT, city TEXT, district TEXT,
                boss_name TEXT, boss_title TEXT, industry TEXT, company_size TEXT,
                financing TEXT, skills TEXT, job_description TEXT, source_query TEXT,
                raw_json TEXT NOT NULL, match_score REAL, match_reasons TEXT,
                eligible INTEGER NOT NULL DEFAULT 0, first_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_jobs_eligible_score ON jobs(eligible, match_score DESC);
            CREATE TABLE IF NOT EXISTS greeting_cache(
                cache_key TEXT PRIMARY KEY, task_id TEXT NOT NULL, profile_fingerprint TEXT NOT NULL,
                greeting TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """)

    def replace_taxonomy(self, items: list[JobTaxonomyItem]) -> None:
        now = datetime.now(SHANGHAI).isoformat()
        with sqlite3.connect(self.path) as db:
            db.executemany("""
                INSERT INTO taxonomy(code,major,category,title,updated_at) VALUES(?,?,?,?,?)
                ON CONFLICT(code) DO UPDATE SET major=excluded.major,category=excluded.category,
                title=excluded.title,updated_at=excluded.updated_at
            """, [(x.code, x.major, x.category, x.title, now) for x in items])

    def save_profile(self, snapshot: ProfileSnapshot) -> bool:
        with sqlite3.connect(self.path) as db:
            cursor = db.execute("""
                INSERT OR IGNORE INTO profile_snapshots
                (fingerprint,captured_at,sections_json,attachments_json) VALUES(?,?,?,?)
            """, (snapshot.fingerprint, snapshot.captured_at,
                  json.dumps(snapshot.sections, ensure_ascii=False),
                  json.dumps(snapshot.attachment_names, ensure_ascii=False)))
            return cursor.rowcount == 1

    def latest_profile(self) -> ProfileSnapshot | None:
        with sqlite3.connect(self.path) as db:
            row = db.execute("""SELECT fingerprint,captured_at,sections_json,attachments_json
                FROM profile_snapshots ORDER BY captured_at DESC LIMIT 1""").fetchone()
        if not row: return None
        return ProfileSnapshot(row[0], row[1], json.loads(row[2]), tuple(json.loads(row[3])))

    def upsert_job(self, job: dict[str, Any], score: float, reasons: list[str], eligible: bool) -> None:
        now = datetime.now(SHANGHAI).isoformat()
        values = (
            job["job_id"], job["url"], job.get("title", ""), job.get("company", ""),
            job.get("salary", ""), job.get("degree", ""), job.get("experience", ""),
            job.get("city", ""), job.get("district", ""), job.get("boss_name", ""),
            job.get("boss_title", ""), job.get("industry", ""), job.get("company_size", ""),
            job.get("financing", ""), json.dumps(job.get("skills", []), ensure_ascii=False),
            job.get("job_description", ""), job.get("query", ""),
            json.dumps(job.get("raw", job), ensure_ascii=False), score,
            json.dumps(reasons, ensure_ascii=False), int(eligible), now, now,
        )
        with sqlite3.connect(self.path) as db:
            db.execute("""
                INSERT INTO jobs(job_id,url,title,company,salary,degree,experience,city,district,
                boss_name,boss_title,industry,company_size,financing,skills,job_description,
                source_query,raw_json,match_score,match_reasons,eligible,first_seen_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_id) DO UPDATE SET url=excluded.url,title=excluded.title,
                company=excluded.company,salary=excluded.salary,degree=excluded.degree,
                experience=excluded.experience,city=excluded.city,district=excluded.district,
                boss_name=excluded.boss_name,boss_title=excluded.boss_title,
                industry=excluded.industry,company_size=excluded.company_size,
                financing=excluded.financing,skills=excluded.skills,
                job_description=excluded.job_description,source_query=excluded.source_query,
                raw_json=excluded.raw_json,match_score=excluded.match_score,
                match_reasons=excluded.match_reasons,eligible=excluded.eligible,updated_at=excluded.updated_at
            """, values)

    def cached_greeting(self, cache_key: str) -> str:
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT greeting FROM greeting_cache WHERE cache_key=?", (cache_key,)
            ).fetchone()
        return str(row[0]) if row else ""

    def save_greeting(self, cache_key: str, task_id: str, profile_fingerprint: str,
                      greeting: str, model: str) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                """INSERT OR REPLACE INTO greeting_cache
                (cache_key,task_id,profile_fingerprint,greeting,model,created_at)
                VALUES(?,?,?,?,?,?)""",
                (cache_key, task_id, profile_fingerprint, greeting, model,
                 datetime.now(SHANGHAI).isoformat()),
            )


class CommunicationsDatabase:
    def __init__(self, path: Path): self.path = path
    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS communications(
                task_id TEXT PRIMARY KEY, job_id TEXT, job_url TEXT, job_title TEXT, company TEXT,
                greeting TEXT, greeting_source TEXT, match_score REAL, status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, failure_reason TEXT, sent_at TEXT,
                verified_at TEXT, conversation_id TEXT, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS communication_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, event_type TEXT NOT NULL,
                detail TEXT, created_at TEXT NOT NULL
            );
            """)

    def record(self, *, task_id: str, job_id: str, job_url: str, job_title: str,
               company: str, greeting: str, source: str, score: float, status: str,
               attempts: int, reason: str = "", conversation_id: str = "") -> None:
        now = datetime.now(SHANGHAI).isoformat()
        sent_at = now if status in {"sent", "verified"} else None
        verified_at = now if status == "verified" else None
        with sqlite3.connect(self.path) as db:
            db.execute("""
            INSERT INTO communications(task_id,job_id,job_url,job_title,company,greeting,
            greeting_source,match_score,status,attempts,failure_reason,sent_at,verified_at,
            conversation_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(task_id) DO UPDATE SET greeting=excluded.greeting,
            greeting_source=excluded.greeting_source,match_score=excluded.match_score,
            status=excluded.status,attempts=excluded.attempts,failure_reason=excluded.failure_reason,
            sent_at=COALESCE(excluded.sent_at,communications.sent_at),
            verified_at=COALESCE(excluded.verified_at,communications.verified_at),
            conversation_id=excluded.conversation_id,updated_at=excluded.updated_at
            """, (task_id,job_id,job_url,job_title,company,greeting,source,score,status,
                  attempts,reason,sent_at,verified_at,conversation_id,now))
            db.execute("INSERT INTO communication_events(task_id,event_type,detail,created_at) VALUES(?,?,?,?)",
                       (task_id,status,reason,now))


class ChatDatabase:
    def __init__(self, path: Path): self.path = path
    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS conversations(
                conversation_id TEXT PRIMARY KEY, contact_name TEXT, job_title TEXT, company TEXT,
                last_message_fingerprint TEXT, last_direction TEXT, last_observed_at TEXT,
                automation_state TEXT NOT NULL DEFAULT 'active', updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages(
                fingerprint TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, direction TEXT NOT NULL,
                text TEXT NOT NULL, observed_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'web'
            );
            CREATE TABLE IF NOT EXISTS decisions(
                id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
                based_on_fingerprint TEXT NOT NULL, decision TEXT NOT NULL, draft TEXT,
                status TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS interview_alerts(
                id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
                message_fingerprint TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'pending_user',
                detail TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS resume_invitations(
                fingerprint TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                classification TEXT NOT NULL, matched_keyword TEXT, status TEXT NOT NULL,
                resume_name TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_checks(
                id INTEGER PRIMARY KEY AUTOINCREMENT, checked_at TEXT NOT NULL,
                unread_count INTEGER NOT NULL, new_messages INTEGER NOT NULL,
                invitations INTEGER NOT NULL, note TEXT
            );
            CREATE TABLE IF NOT EXISTS resume_deliveries(
                conversation_id TEXT PRIMARY KEY, job_title TEXT, company TEXT,
                resume_key TEXT NOT NULL, resume_name TEXT, status TEXT NOT NULL,
                reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            """)

    def migrate_legacy(self, legacy_path: Path) -> None:
        """幂等导入旧审计库，保留历史简历投递状态，避免迁移后重复发送。"""
        if not legacy_path.exists() or legacy_path.resolve() == self.path.resolve():
            return
        with sqlite3.connect(legacy_path) as legacy, sqlite3.connect(self.path) as db:
            tables = {row[0] for row in legacy.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "messages" in tables:
                for row in legacy.execute("""SELECT fingerprint,conversation_id,contact_name,
                        job_title,company,direction,text,observed_at FROM messages"""):
                    db.execute("""INSERT OR IGNORE INTO messages
                        (fingerprint,conversation_id,direction,text,observed_at,source)
                        VALUES(?,?,?,?,?,'legacy')""", (row[0], row[1], row[5], row[6], row[7]))
                    db.execute("""INSERT OR IGNORE INTO conversations
                        (conversation_id,contact_name,job_title,company,last_message_fingerprint,
                         last_direction,last_observed_at,automation_state,updated_at)
                        VALUES(?,?,?,?,?,?,?,'active',?)""",
                        (row[1], row[2], row[3], row[4], row[0], row[5], row[7], row[7]))
            if "resume_invitations" in tables:
                db.executemany("""INSERT OR IGNORE INTO resume_invitations
                    (fingerprint,conversation_id,classification,matched_keyword,status,
                     resume_name,created_at) VALUES(?,?,?,?,?,?,?)""",
                    legacy.execute("""SELECT fingerprint,conversation_id,classification,
                        matched_keyword,status,resume_name,created_at FROM resume_invitations""").fetchall())
            if "resume_deliveries" in tables:
                db.executemany("""INSERT OR IGNORE INTO resume_deliveries
                    (conversation_id,job_title,company,resume_key,resume_name,status,reason,
                     created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                    legacy.execute("""SELECT conversation_id,job_title,company,resume_key,
                        resume_name,status,reason,created_at,updated_at FROM resume_deliveries""").fetchall())

    def record_message(self, message: Any) -> bool:
        now = datetime.now(SHANGHAI).isoformat()
        fingerprint = str(message.fingerprint)
        with sqlite3.connect(self.path) as db:
            cursor = db.execute("""INSERT OR IGNORE INTO messages
                (fingerprint,conversation_id,direction,text,observed_at,source)
                VALUES(?,?,?,?,?,'web')""",
                (fingerprint, message.conversation_id, message.direction,
                 message.text, message.observed_at.isoformat()))
            db.execute("""INSERT INTO conversations
                (conversation_id,contact_name,job_title,company,last_message_fingerprint,
                 last_direction,last_observed_at,automation_state,updated_at)
                VALUES(?,?,?,?,?,?,?,'active',?)
                ON CONFLICT(conversation_id) DO UPDATE SET contact_name=excluded.contact_name,
                job_title=excluded.job_title,company=excluded.company,
                last_message_fingerprint=excluded.last_message_fingerprint,
                last_direction=excluded.last_direction,last_observed_at=excluded.last_observed_at,
                updated_at=excluded.updated_at""",
                (message.conversation_id, message.contact_name, message.job_title,
                 message.company, fingerprint, message.direction,
                 message.observed_at.isoformat(), now))
            return cursor.rowcount == 1

    def add_message(self, message: Any) -> bool:
        return self.record_message(message)

    def add_invitation(self, message: Any, classification: str, keyword: str,
                       resume_name: str = "") -> bool:
        with sqlite3.connect(self.path) as db:
            cursor = db.execute("""INSERT OR IGNORE INTO resume_invitations
                (fingerprint,conversation_id,classification,matched_keyword,status,resume_name,created_at)
                VALUES(?,?,?,?, 'pending',?,?)""",
                (message.fingerprint, message.conversation_id, classification, keyword,
                 resume_name, datetime.now(SHANGHAI).isoformat()))
            return cursor.rowcount == 1

    def record_chat_check(self, unread: int, new_messages: int, invitations: int,
                          note: str = "") -> None:
        with sqlite3.connect(self.path) as db:
            db.execute("""INSERT INTO chat_checks
                (checked_at,unread_count,new_messages,invitations,note) VALUES(?,?,?,?,?)""",
                (datetime.now(SHANGHAI).isoformat(), unread, new_messages, invitations, note))

    def resume_sent(self, conversation_id: str) -> bool:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT status FROM resume_deliveries WHERE conversation_id=?",
                             (conversation_id,)).fetchone()
        return bool(row and row[0] == "success")

    def record_resume_delivery(self, conversation_id: str, job_title: str, company: str,
                               resume_key: str, resume_name: str, status: str,
                               reason: str = "") -> None:
        now = datetime.now(SHANGHAI).isoformat()
        with sqlite3.connect(self.path) as db:
            db.execute("""INSERT INTO resume_deliveries
                (conversation_id,job_title,company,resume_key,resume_name,status,reason,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET
                resume_key=excluded.resume_key,resume_name=excluded.resume_name,
                status=excluded.status,reason=excluded.reason,updated_at=excluded.updated_at""",
                (conversation_id, job_title, company, resume_key, resume_name, status,
                 reason, now, now))

    def last_fingerprint(self, conversation_id: str) -> str:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT last_message_fingerprint FROM conversations WHERE conversation_id=?",
                             (conversation_id,)).fetchone()
        return str(row[0]) if row and row[0] else ""

    def record_decision(self, conversation_id: str, based_on: str, decision: str,
                        draft: str, status: str, reason: str = "") -> None:
        with sqlite3.connect(self.path) as db:
            db.execute("""INSERT INTO decisions(conversation_id,based_on_fingerprint,decision,
                draft,status,reason,created_at) VALUES(?,?,?,?,?,?,?)""",
                (conversation_id, based_on, decision, draft, status, reason,
                 datetime.now(SHANGHAI).isoformat()))

    def record_interview_alert(self, conversation_id: str, fingerprint: str, detail: str) -> bool:
        with sqlite3.connect(self.path) as db:
            cursor = db.execute("""INSERT OR IGNORE INTO interview_alerts
                (conversation_id,message_fingerprint,status,detail,created_at)
                VALUES(?,?,'pending_user',?,?)""",
                (conversation_id, fingerprint, detail, datetime.now(SHANGHAI).isoformat()))
            if cursor.rowcount:
                db.execute("UPDATE conversations SET automation_state='manual_takeover' WHERE conversation_id=?",
                           (conversation_id,))
            return cursor.rowcount == 1

    def pending_interview_alerts(self) -> list[dict[str, str]]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("""SELECT conversation_id,detail,created_at FROM interview_alerts
                WHERE status='pending_user' ORDER BY created_at DESC""").fetchall()
        return [{"conversation_id": row[0], "detail": row[1], "created_at": row[2]}
                for row in rows]
