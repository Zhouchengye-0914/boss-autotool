import tempfile
import threading
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
                "min_salary": 9, "workers": 3, "greeting": "您好，希望进一步沟通。",
                "exclude": ["销售"], "blacklist": ["示例公司"],
            })
            config = load_config(target)
            self.assertEqual(config.search.keywords, ("数据分析", "AI 产品"))
            self.assertEqual(config.search.max_pages_per_keyword, 3)
            self.assertEqual(config.search.min_salary_k, 9)
            self.assertEqual(config.search.company_blacklist, ("示例公司",))

    def test_empty_keywords_enable_recommendation_mode(self):
        source = Path(__file__).resolve().parents[1] / "config.yaml"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.yaml"
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            _atomic_save_search(target, {"keywords": [], "max_pages": 2,
                                         "min_salary": 8, "workers": 2,
                                         "greeting": "hello", "resume_general": "通用-",
                                         "resume_ai": "AI-", "resume_data": "数据-"})
            self.assertEqual(load_config(target).search.keywords, ())

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

    def test_config_save_leaves_no_fixed_temp_file(self):
        source = Path(__file__).resolve().parents[1] / "config.yaml"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.yaml"
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            _atomic_save_search(target, {"keywords": [], "max_pages": 1, "min_salary": 0,
                                         "workers": 1, "greeting": "您好"})
            self.assertFalse(target.with_suffix(".yaml.tmp").exists())
            self.assertEqual(load_config(target).search.greeting, "您好")

    def test_broken_client_encoding_is_rejected_without_changing_config(self):
        source = Path(__file__).resolve().parents[1] / "config.yaml"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.yaml"
            original = source.read_text(encoding="utf-8")
            target.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "编码已损坏"):
                _atomic_save_search(target, {"keywords": ["????"], "max_pages": 1,
                                             "min_salary": 0, "workers": 1, "greeting": "???"})
            self.assertEqual(original, target.read_text(encoding="utf-8"))

    def test_independent_modules_can_start_together(self):
        source = Path(__file__).resolve().parents[1] / "config.yaml"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.yaml"
            config.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            controller = JobController(root, config)
            release = threading.Event()
            controller._worker = lambda _action: release.wait(1)
            controller.start("scan")
            controller.start("watch")
            self.assertEqual({"scan", "watch"}, controller.active_actions)
            with self.assertRaisesRegex(RuntimeError, "同一功能模块"):
                controller.start("check")
            with self.assertRaisesRegex(RuntimeError, "独占"):
                controller.start("full")
            release.set()

    def test_abort_can_target_one_module(self):
        class FakeProcess:
            def __init__(self): self.terminated = False
            def poll(self): return None
            def terminate(self): self.terminated = True

        controller = JobController(Path.cwd(), Path("config.yaml"))
        scan, watch = FakeProcess(), FakeProcess()
        controller.active_actions.update({"scan", "watch"})
        controller.processes.update({"scan": scan, "watch-chat": watch})
        controller.abort("scan")
        self.assertTrue(scan.terminated)
        self.assertFalse(watch.terminated)
