import tempfile
import unittest
from pathlib import Path

from boss_assistant.config import load_config
from boss_assistant.ui import JobController, _atomic_save_search


class UiConfigTests(unittest.TestCase):
    def test_search_settings_are_saved_and_validated(self):
        source = Path(__file__).resolve().parents[1] / "config.yaml"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.yaml"
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            _atomic_save_search(target, {
                "keywords": ["数据分析", "AI 产品"], "max_pages": 3,
                "min_salary": 9, "greeting": "您好，希望进一步沟通。",
                "exclude": ["销售"], "blacklist": ["示例公司"],
            })
            config = load_config(target)
            self.assertEqual(config.search.keywords, ("数据分析", "AI 产品"))
            self.assertEqual(config.search.max_pages_per_keyword, 3)
            self.assertEqual(config.search.min_salary_k, 9)
            self.assertEqual(config.search.company_blacklist, ("示例公司",))

    def test_empty_keywords_are_rejected(self):
        source = Path(__file__).resolve().parents[1] / "config.yaml"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.yaml"
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaises(ValueError):
                _atomic_save_search(target, {"keywords": [], "max_pages": 2,
                                             "min_salary": 8, "greeting": "hello"})

    def test_abort_terminates_active_child(self):
        class FakeProcess:
            def __init__(self): self.terminated = False
            def poll(self): return None
            def terminate(self): self.terminated = True

        controller = JobController(Path.cwd(), Path("config.yaml"))
        process = FakeProcess()
        controller.process = process
        controller.abort()
        self.assertTrue(process.terminated)
        self.assertTrue(controller.stop_requested)
