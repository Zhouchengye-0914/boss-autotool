import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from boss_assistant.models import JobTask, OperationType
from boss_assistant.persistence import ProgressError, ProgressStore


class ProgressTests(unittest.TestCase):
    def task(self):
        return JobTask("one", "https://example.com/job", "", "你好", "简历.pdf", OperationType.COMMUNICATION)

    def test_atomic_round_trip_and_daily_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "progress.json"
            store = ProgressStore(path)
            store.record(self.task(), "success", 1)
            other = ProgressStore(path)
            other.load()
            self.assertTrue(other.is_terminal("one"))
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            self.assertEqual(other.success_count_today(now), 1)

    def test_corrupt_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "progress.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ProgressError):
                ProgressStore(path).load()
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")


if __name__ == "__main__":
    unittest.main()

