import unittest

from boss_assistant.models import JobTask, OperationType


class JobTaskTests(unittest.TestCase):
    def test_builds_url_and_stable_id(self):
        raw = {
            "job_id": "abc123",
            "greeting": "你好",
            "resume_name": "简历.pdf",
            "operation_type": "communication",
        }
        first = JobTask.from_dict(raw)
        second = JobTask.from_dict(raw)
        self.assertEqual(first.task_id, second.task_id)
        self.assertEqual(first.job_url, "https://www.zhipin.com/job_detail/abc123.html")
        self.assertIs(first.operation_type, OperationType.COMMUNICATION)

    def test_rejects_missing_identity(self):
        with self.assertRaisesRegex(ValueError, "至少提供一个"):
            JobTask.from_dict({"greeting": "你好", "resume_name": "简历.pdf"})


if __name__ == "__main__":
    unittest.main()

