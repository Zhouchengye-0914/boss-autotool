import tempfile
import unittest
from pathlib import Path

from boss_assistant.config import (
    AppConfig, BrowserConfig, OutputConfig, PacingConfig, SchedulerConfig,
)
from boss_assistant.models import JobTask, OperationType, ResultStatus, TaskResult
from boss_assistant.output import CsvOutput
from boss_assistant.pacing import PacingController
from boss_assistant.persistence import ProgressStore
from boss_assistant.scheduler import TaskScheduler


class SchedulerTests(unittest.TestCase):
    def make_config(self, root):
        return AppConfig(
            root,
            BrowserConfig(root / "chrome", root / "profile", root / "state", 9223, 30, 10, 5, ("ua",)),
            SchedulerConfig(300, 3, root / "tasks.json", root / "progress.json"),
            PacingConfig(0, 0, 20, 0, 0, 0, 0, 0),
            OutputConfig(root / "result.csv", root / "error.csv", root / "shots", 99999),
        )

    def test_three_failures_become_terminal_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            task = JobTask("one", "https://example.com/job", "", "你好", "简历.pdf", OperationType.COMMUNICATION)
            store = ProgressStore(config.scheduler.progress_file)
            pacing = PacingController(config.pacing, sleeper=lambda _: None, reporter=lambda _: None)

            def fail(_task, attempt):
                return TaskResult(ResultStatus.FAILED, reason="temporary", attempt=attempt)

            scheduler = TaskScheduler(config, store, pacing, CsvOutput(config.output.result_csv, config.output.error_csv), fail)
            state = scheduler.run([task])
            self.assertEqual(state.skipped, 1)
            self.assertEqual(state.failed_attempts, 3)
            self.assertTrue(store.is_terminal("one"))
            self.assertTrue(config.output.error_csv.exists())

    def test_success_uses_daily_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            task = JobTask("one", "https://example.com/job", "", "你好", "简历.pdf", OperationType.COMMUNICATION)
            store = ProgressStore(config.scheduler.progress_file)
            pacing = PacingController(config.pacing, sleeper=lambda _: None, reporter=lambda _: None)
            scheduler = TaskScheduler(
                config, store, pacing,
                CsvOutput(config.output.result_csv, config.output.error_csv),
                lambda _task, attempt: TaskResult(ResultStatus.SUCCESS, attempt=attempt),
            )
            state = scheduler.run([task])
            self.assertEqual(state.success, 1)
            self.assertEqual(store.success_count_today(), 1)

    def test_unconfirmed_success_is_retried_before_persisting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            task = JobTask("one", "https://example.com/job", "", "你好", "简历.pdf", OperationType.COMMUNICATION)
            store = ProgressStore(config.scheduler.progress_file)
            pacing = PacingController(config.pacing, sleeper=lambda _: None, reporter=lambda _: None)
            checks = []

            def verify(_task, result):
                checks.append(True)
                if len(checks) == 1:
                    return TaskResult(ResultStatus.FAILED, reason="固定聊天页未找到消息")
                return result

            scheduler = TaskScheduler(
                config, store, pacing,
                CsvOutput(config.output.result_csv, config.output.error_csv),
                lambda _task, attempt: TaskResult(ResultStatus.SUCCESS, attempt=attempt),
                verify_success=verify,
            )
            state = scheduler.run([task])
            self.assertEqual(len(checks), 2)
            self.assertEqual(state.success, 1)
            self.assertEqual(state.failed_attempts, 1)
            self.assertEqual(store.success_count_today(), 1)


if __name__ == "__main__":
    unittest.main()
