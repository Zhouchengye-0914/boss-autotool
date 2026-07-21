import json
import tempfile
import unittest
from pathlib import Path

from boss_assistant.workflow import ScanCheckpoint, WorkflowStateStore


class WorkflowStateTests(unittest.TestCase):
    def test_active_workflow_becomes_resumable_after_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            store = WorkflowStateStore(Path(temp) / "workflow.json")
            store.update("full", "scanning", resumable=True)
            state = WorkflowStateStore(store.path).load(recover_interrupted=True)
            self.assertEqual("interrupted", state.phase)
            self.assertEqual("full", state.action)
            self.assertTrue(state.resumable)

    def test_completed_workflow_is_not_resumable(self):
        with tempfile.TemporaryDirectory() as temp:
            store = WorkflowStateStore(Path(temp) / "workflow.json")
            store.update("scan", "completed")
            self.assertFalse(store.load(recover_interrupted=True).resumable)


class ScanCheckpointTests(unittest.TestCase):
    def test_checkpoint_restores_jobs_and_completed_queries(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scan.json"
            first = ScanCheckpoint(path); first.load(("AI", "数据"))
            first.save_page("AI", 1, [{"job_id": "one", "title": "AI"}])
            first.complete_query("AI")
            second = ScanCheckpoint(path); second.load(("AI", "数据"))
            self.assertIn("one", second.data["jobs"])
            self.assertIn("AI", second.data["completed_queries"])

    def test_changed_queries_start_a_new_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scan.json"
            first = ScanCheckpoint(path); first.load(("AI",)); first.save_page("AI", 1, [{"job_id": "one"}])
            second = ScanCheckpoint(path); second.load(("运营",))
            self.assertEqual({}, second.data["jobs"])


if __name__ == "__main__":
    unittest.main()
