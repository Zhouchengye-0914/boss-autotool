import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from boss_assistant.chat_monitor import ResumeInvitationClassifier
from boss_assistant.models import JobTask, OperationType
from boss_assistant.persistence import SHANGHAI
from boss_assistant.records import MessageRecord, RecordStore


class InvitationClassifierTests(unittest.TestCase):
    def setUp(self):
        self.classifier = ResumeInvitationClassifier()

    def test_explicit_resume_request(self):
        decision = self.classifier.classify("方便发一份附件简历吗？")
        self.assertEqual(decision.classification, "explicit")

    def test_generic_reply_is_not_invitation(self):
        decision = self.classifier.classify("你好，可以进一步聊聊岗位情况")
        self.assertEqual(decision.classification, "none")

    def test_ambiguous_resume_mention_requires_review(self):
        decision = self.classifier.classify("我先看看你的简历")
        self.assertEqual(decision.classification, "manual_review")


class RecordStoreTests(unittest.TestCase):
    def test_jobs_and_messages_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RecordStore(Path(tmp) / "records.db")
            store.initialize()
            task = JobTask(
                "one", "https://example.com/job", "job-1", "你好", "数据分析.pdf",
                OperationType.COMMUNICATION, "数据分析师", "示例公司", "data_analysis", "SQL Python",
            )
            store.upsert_job(task)
            message = MessageRecord(
                "chat-1", "招聘经理", "job-1", "数据分析师", "示例公司",
                "inbound", "请发一份简历", datetime.now(SHANGHAI),
            )
            self.assertTrue(store.add_message(message))
            self.assertFalse(store.add_message(message))
            self.assertTrue(store.add_invitation(message, "explicit", "发一份简历", task.resume_name))
            self.assertFalse(store.add_invitation(message, "explicit", "发一份简历", task.resume_name))


if __name__ == "__main__":
    unittest.main()
