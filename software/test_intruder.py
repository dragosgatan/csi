import unittest

from intruder import DWELL, STALE, TRIP, IntruderWatch


def feed(watch, activity, seconds, start, step=0.1):
    """Push a steady activity level for a stretch of simulated time."""
    ticks = int(seconds / step)
    now = start
    for _ in range(ticks):
        now += step
        watch.update(activity, now=now)
    return now


class IntruderWatchTests(unittest.TestCase):
    def setUp(self):
        self.watch = IntruderWatch()

    def test_disarmed_ignores_movement(self):
        now = feed(self.watch, TRIP + 0.2, DWELL * 10, start=1000.0)
        self.assertEqual(self.watch.state(now=now), "off")
        self.assertFalse(self.watch.snapshot(now=now)["alarm"])

    def test_quiet_armed_room_never_alarms(self):
        self.watch.arm()
        now = feed(self.watch, TRIP / 2, 300.0, start=1000.0)
        self.assertEqual(self.watch.state(now=now), "armed")

    def test_sustained_movement_alarms(self):
        self.watch.arm()
        now = feed(self.watch, TRIP + 0.2, DWELL + 0.5, start=1000.0)
        self.assertEqual(self.watch.state(now=now), "alarm")

    def test_brief_spike_does_not_alarm(self):
        self.watch.arm()
        now = feed(self.watch, TRIP + 0.2, DWELL / 3, start=1000.0)
        now = feed(self.watch, 0.0, 10.0, start=now)
        self.assertEqual(self.watch.state(now=now), "armed")

    def test_alarm_latches_after_movement_stops(self):
        self.watch.arm()
        now = feed(self.watch, TRIP + 0.2, DWELL + 0.5, start=1000.0)
        now = feed(self.watch, 0.0, 60.0, start=now)
        self.assertEqual(self.watch.state(now=now), "alarm")

    def test_alarm_fires_callback_once(self):
        calls = []
        watch = IntruderWatch(on_alarm=calls.append)
        watch.arm()
        feed(watch, TRIP + 0.2, DWELL * 5, start=1000.0)
        self.assertEqual(len(calls), 1)

    def test_disarm_clears_the_latch(self):
        self.watch.arm()
        now = feed(self.watch, TRIP + 0.2, DWELL + 0.5, start=1000.0)
        self.watch.disarm()
        self.assertEqual(self.watch.state(now=now), "off")

    def test_silence_while_armed_reads_offline(self):
        self.watch.arm()
        now = feed(self.watch, 0.0, 5.0, start=1000.0)
        self.assertEqual(self.watch.state(now=now + STALE + 1.0), "offline")


    def test_trip_now_alarms_and_pushes_once(self):
        calls = []
        watch = IntruderWatch(on_alarm=calls.append)
        watch.trip_now(now=1000.0)
        watch.trip_now(now=1001.0)
        self.assertEqual(watch.state(now=1000.5), "alarm")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
