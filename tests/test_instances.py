import unittest
from pathlib import Path

from boss_assistant.config import load_config
from boss_assistant.instances import isolated_config


class InstanceConfigTests(unittest.TestCase):
    def test_instance_paths_ports_and_quota_are_isolated(self):
        root = Path(__file__).resolve().parents[1]
        config = load_config(root / "config.yaml")
        first = isolated_config(config, "worker-01", 1, 0, 2)
        second = isolated_config(config, "worker-02", 2, 1, 2)
        self.assertNotEqual(first.browser.profile_path, second.browser.profile_path)
        self.assertNotEqual(first.browser.debug_port, second.browser.debug_port)
        self.assertNotEqual(first.scheduler.progress_file, second.scheduler.progress_file)
        self.assertNotEqual(first.storage.database_path, second.storage.database_path)
        self.assertEqual(
            first.scheduler.daily_success_limit + second.scheduler.daily_success_limit,
            config.scheduler.daily_success_limit,
        )
