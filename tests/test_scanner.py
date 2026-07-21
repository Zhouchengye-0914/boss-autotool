import unittest
import tempfile
from pathlib import Path

from boss_assistant.config import load_config
from boss_assistant.scanner import BossJobScanner, parse_joblist_response, salary_meets_minimum
from boss_assistant.workflow import ScanCheckpoint


class ScannerTests(unittest.TestCase):
    def test_parses_nested_joblist_without_jsonpath_dependency(self):
        body = {"code": 0, "zpData": {"jobList": [{
            "encryptJobId": "abc", "jobName": "数据分析师",
            "salaryDesc": "10-15K", "brandName": "示例公司",
            "cityName": "杭州", "bossName": "招聘经理",
        }]}}
        jobs = parse_joblist_response(body, "数据分析")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["job_id"], "abc")
        self.assertEqual(jobs[0]["query"], "数据分析")

    def test_salary_filter_uses_lower_bound(self):
        self.assertTrue(salary_meets_minimum("8-12K", 8))
        self.assertFalse(salary_meets_minimum("6-9K", 8))
        self.assertTrue(salary_meets_minimum("200-250元/天", 8))

    def test_empty_listener_result_keeps_query_resumable(self):
        class Listen:
            def start(self, _target): pass
            def steps(self, timeout): return iter(())
        class Page:
            listen = Listen()
            def get(self, _url): pass
            def run_js(self, _script): pass

        config = load_config(Path(__file__).resolve().parents[1] / "config.yaml").search
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = ScanCheckpoint(Path(directory) / "scan.json")
            scanner = BossJobScanner(Page(), config, checkpoint=checkpoint,
                                     sleeper=lambda _: None, reporter=lambda _: None)
            scanner.scan()
            self.assertEqual("interrupted", checkpoint.data["status"])
            self.assertEqual([], checkpoint.data["completed_queries"])


if __name__ == "__main__":
    unittest.main()
