import csv
import tempfile
import unittest
from pathlib import Path

from boss_assistant.daily_report import DailyReportGenerator
from boss_assistant.records import RecordStore


class DailyReportTests(unittest.TestCase):
    def test_generates_layered_daily_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "records.db"
            RecordStore(database).initialize()
            result_csv = root / "results.csv"
            with result_csv.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(("时间", "操作类型", "结果"))
                writer.writerow(("2026-07-20T08:00:00+08:00", "communication", "success"))
                writer.writerow(("2026-07-20T08:01:00+08:00", "communication", "failed"))
            generator = DailyReportGenerator(database, result_csv, root / "reports")
            metrics = generator.collect("2026-07-20")
            self.assertEqual(metrics.operation_attempts, 2)
            self.assertEqual(metrics.communication_successes, 1)
            self.assertEqual(metrics.failed_attempts, 1)
            md_path, json_path = generator.write("2026-07-20")
            self.assertTrue(md_path.exists())
            self.assertTrue(json_path.exists())


if __name__ == "__main__":
    unittest.main()
