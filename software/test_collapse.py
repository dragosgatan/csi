import unittest

from collapse import ACTIVE_MIN, HOLD, MOVE, STALE, STILL, CollapseWatch


def feed(watch, activity, seconds, start, step=0.1):
    """Push a steady activity level for a stretch of simulated time."""
    ticks = int(seconds / step)
    now = start
    for _ in range(ticks):
        now += step
        watch.update(activity, now=now)
    return now


class CollapseWatchTests(unittest.TestCase):
    def setUp(self):
        self.watch = CollapseWatch()

    def test_starts_waiting(self):
        self.assertEqual(self.watch.state(now=0.0), "waiting")
        self.assertFalse(self.watch.snapshot(now=0.0)["alarm"])

    def test_quiet_room_never_alarms(self):
        now = feed(self.watch, STILL / 2, 300.0, start=1000.0)
        self.assertEqual(self.watch.state(now=now), "quiet")
        self.assertFalse(self.watch.snapshot(now=now)["alarm"])

    def test_movement_is_reported(self):
        now = feed(self.watch, MOVE + 0.1, ACTIVE_MIN + 1.0, start=1000.0)
        self.assertEqual(self.watch.state(now=now), "movement")

    def test_brief_movement_does_not_arm(self):
        now = feed(self.watch, MOVE + 0.1, ACTIVE_MIN / 2, start=1000.0)
        now = feed(self.watch, 0.0, HOLD + 10.0, start=now)
        self.assertFalse(self.watch.snapshot(now=now)["armed"])
        self.assertNotEqual(self.watch.state(now=now), "motionless")

    def test_sustained_movement_then_stillness_alarms(self):
        now = feed(self.watch, MOVE + 0.1, ACTIVE_MIN + 1.0, start=1000.0)
        now = feed(self.watch, 0.0, HOLD - 5.0, start=now)
        self.assertEqual(self.watch.state(now=now), "settling")

        now = feed(self.watch, 0.0, 6.0, start=now)
        self.assertEqual(self.watch.state(now=now), "motionless")
        self.assertTrue(self.watch.snapshot(now=now)["alarm"])

    def test_movement_again_clears_the_alarm(self):
        now = feed(self.watch, MOVE + 0.1, ACTIVE_MIN + 1.0, start=1000.0)
        now = feed(self.watch, 0.0, HOLD + 2.0, start=now)
        self.assertTrue(self.watch.snapshot(now=now)["alarm"])

        now = feed(self.watch, MOVE + 0.1, ACTIVE_MIN + 1.0, start=now)
        self.assertFalse(self.watch.snapshot(now=now)["alarm"])
        self.assertEqual(self.watch.state(now=now), "movement")

    def test_a_single_blip_does_not_clear_the_alarm(self):
        now = feed(self.watch, MOVE + 0.1, ACTIVE_MIN + 1.0, start=1000.0)
        now = feed(self.watch, 0.0, HOLD + 2.0, start=now)
        now += 0.1
        self.watch.update(MOVE + 0.5, now=now)
        self.assertTrue(self.watch.snapshot(now=now)["alarm"])

    def test_still_for_counts_up(self):
        now = feed(self.watch, MOVE + 0.1, ACTIVE_MIN + 1.0, start=1000.0)
        now = feed(self.watch, 0.0, 4.0, start=now)
        self.assertAlmostEqual(self.watch.still_for(now=now), 4.0, delta=0.3)

    def test_goes_offline_when_packets_stop(self):
        now = feed(self.watch, 0.0, 1.0, start=1000.0)
        self.assertEqual(self.watch.state(now=now + STALE + 1.0), "offline")

    def test_reset_clears_the_episode(self):
        now = feed(self.watch, MOVE + 0.1, ACTIVE_MIN + 1.0, start=1000.0)
        now = feed(self.watch, 0.0, HOLD + 2.0, start=now)
        self.assertTrue(self.watch.snapshot(now=now)["alarm"])

        self.watch.reset()
        self.assertEqual(self.watch.state(now=now), "waiting")
        self.assertFalse(self.watch.snapshot(now=now)["armed"])

    def test_snapshot_exposes_thresholds(self):
        snapshot = self.watch.snapshot(now=0.0)
        self.assertEqual(snapshot["move"], MOVE)
        self.assertEqual(snapshot["still"], STILL)
        self.assertEqual(snapshot["hold"], HOLD)


if __name__ == "__main__":
    unittest.main()
