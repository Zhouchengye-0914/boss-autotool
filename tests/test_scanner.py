import unittest

from boss_assistant.scanner import parse_joblist_response, salary_meets_minimum


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


if __name__ == "__main__":
    unittest.main()
