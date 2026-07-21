import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from boss_assistant.matching import match_job, recommend_titles
from boss_assistant.persistence import SHANGHAI
from boss_assistant.records import MessageRecord
from boss_assistant.talent_data import (
    ChatDatabase, CommunicationsDatabase, JobsDatabase, ProfileSnapshot, parse_job_taxonomy,
)


class TalentDataTests(unittest.TestCase):
    def profile(self):
        return ProfileSnapshot("fp", "2026-01-01T00:00:00+08:00", {
            "summary": "应届生，具备Python、SQL、数据分析和AI应用能力",
            "skills": "Power BI 机器学习 数据挖掘",
            "expectations": "数据分析 AI产品 杭州 上海",
        }, ("通用.pdf", "AI相关.pdf", "数据相关.pdf"))

    def test_job_md_taxonomy_and_profile_recommendations(self):
        path = Path(__file__).resolve().parents[1] / "data" / "job.md"
        items = parse_job_taxonomy(path)
        self.assertGreater(len(items), 50)
        suggestions = recommend_titles(self.profile(), items)
        self.assertIn("数据分析师", suggestions)
        self.assertIn("AI 产品经理", suggestions)

    def test_match_threshold_accepts_relevant_entry_job(self):
        result = match_job({"title": "数据分析师", "degree": "本科",
                            "experience": "应届生", "skills": ["Python", "SQL"]},
                           self.profile(), 58)
        self.assertTrue(result.eligible)
        self.assertGreaterEqual(result.score, 58)

    def test_jobs_database_persists_raw_and_score(self):
        with tempfile.TemporaryDirectory() as directory:
            db = JobsDatabase(Path(directory) / "jobs.db")
            db.initialize(); self.assertTrue(db.save_profile(self.profile()))
            db.upsert_job({"job_id": "j1", "url": "https://example.com/j1",
                           "title": "数据分析师", "raw": {"x": 1}}, 88, ["技能匹配"], True)
            self.assertEqual(db.latest_profile().fingerprint, "fp")

    def test_communication_and_chat_databases_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            communications = CommunicationsDatabase(root / "communications.db")
            communications.initialize()
            communications.record(
                task_id="t1", job_id="j1", job_url="https://example.com",
                job_title="数据分析师", company="公司", greeting="您好",
                source="deepseek", score=80, status="verified", attempts=1,
            )
            chat = ChatDatabase(root / "chat.db")
            chat.initialize()
            message = MessageRecord(
                "c1", "HR", "j1", "数据分析师", "公司", "inbound",
                "方便面试吗", datetime.now(SHANGHAI),
            )
            self.assertTrue(chat.record_message(message))
            self.assertTrue(chat.record_interview_alert("c1", message.fingerprint, message.text))
            self.assertEqual(len(chat.pending_interview_alerts()), 1)
            self.assertNotEqual(communications.path, chat.path)
