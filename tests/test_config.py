import tempfile
import unittest
from pathlib import Path

from boss_assistant.config import ConfigError, load_config


VALID = """
browser:
  executable_path: chrome.exe
  profile_path: profile
  state_file: state.json
  debug_port: 9223
  page_load_timeout: 30
  element_timeout: 10
  login_check_interval: 5
  user_agents: [ua]
scheduler:
  daily_success_limit: 300
  max_retries: 3
  tasks_file: tasks.json
  progress_file: progress.json
pacing:
  min_wait_seconds: 3
  max_wait_seconds: 15
  batch_size: 20
  batch_min_rest_seconds: 30
  batch_max_rest_seconds: 90
  long_pause_probability: 0.1
  long_pause_min_seconds: 60
  long_pause_max_seconds: 180
output:
  result_csv: result.csv
  error_csv: error.csv
  screenshots_dir: screenshots
  progress_report_interval_seconds: 3600
"""


class ConfigTests(unittest.TestCase):
    def test_loads_defaults_from_yaml_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(VALID, encoding="utf-8")
            config = load_config(path)
            self.assertEqual(config.scheduler.daily_success_limit, 300)
            self.assertEqual(config.browser.debug_port, 9223)

    def test_rejects_invalid_probability(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(VALID.replace("long_pause_probability: 0.1", "long_pause_probability: 2"), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()

