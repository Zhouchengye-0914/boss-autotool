import random
import unittest

from boss_assistant.config import PacingConfig
from boss_assistant.pacing import PacingController


class PacingTests(unittest.TestCase):
    def config(self):
        return PacingConfig(3, 15, 2, 30, 90, 1.0, 60, 180)

    def test_wait_ranges_and_batch(self):
        sleeps = []
        pacing = PacingController(
            self.config(), rng=random.Random(7), sleeper=sleeps.append, reporter=lambda _: None
        )
        pacing.wait_before_attempt()
        self.assertEqual(len(sleeps), 2)
        self.assertTrue(3 <= sleeps[0] <= 15)
        self.assertTrue(60 <= sleeps[1] <= 180)
        pacing.record_success()
        pacing.record_success()
        pacing.wait_before_attempt()
        self.assertTrue(30 <= sleeps[2] <= 90)


if __name__ == "__main__":
    unittest.main()

