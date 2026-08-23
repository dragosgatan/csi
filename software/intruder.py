"""Detect an intruder: sustained movement in a room the user said would be empty."""

import time

# thresholds mirror the ones calibrated in collapse.py on a real 56 s capture
# (quiet link p50 0.21, never above 0.65; amplified movement 0.78 and up).
# kept separate so tuning the intruder trip does not move the collapse detector.
TRIP = 0.70     # room score that counts as movement
DWELL = 1.5     # seconds of continuous movement before the alarm - kills one-packet spikes
STALE = 5.0     # seconds without packets before reading as offline


class IntruderWatch:
    """Sustained movement while armed, latched until the user clears it.

    Armed is the user's declaration that the space should be empty, so any
    movement is unexpected by definition - this cannot tell a person from a cat.
    """

    def __init__(self, trip=TRIP, dwell=DWELL, on_alarm=None):
        self.trip = trip
        self.dwell = dwell
        self.on_alarm = on_alarm  # called once on the rising edge, for the push
        self.active = False
        self.reset()

    def reset(self):
        """Clear the latch and the current movement run."""
        self._run = 0.0
        self._alarm = False
        self._alarm_at = None
        self._activity = 0.0
        self._last_update = None

    def arm(self):
        """User is leaving: start watching from a clean latch."""
        self.active = True
        self.reset()

    def disarm(self):
        """User is home: stop watching and clear any standing alarm."""
        self.active = False
        self.reset()

    def update(self, activity, now=None):
        """Feed the room's motion score, return the new state."""
        now = time.time() if now is None else now
        previous = self._last_update
        self._last_update = now
        self._activity = float(activity)
        elapsed = 0.0 if previous is None else max(0.0, now - previous)

        if not self.active or self._alarm:
            return self.state(now)  # latched: the push already went out

        if self._activity >= self.trip:
            self._run += elapsed
            if self._run >= self.dwell:
                self._alarm = True
                self._alarm_at = now
                if self.on_alarm is not None:
                    self.on_alarm(self.snapshot(now))
        else:
            self._run = 0.0

        return self.state(now)

    def trip_now(self, now=None):
        """Force the alarm, for testing push on a phone without a real intruder."""
        now = time.time() if now is None else now
        self.active = True
        self._last_update = now
        if not self._alarm:
            self._alarm = True
            self._alarm_at = now
            if self.on_alarm is not None:
                self.on_alarm(self.snapshot(now))
        return self.state(now)

    def state(self, now=None):
        now = time.time() if now is None else now
        if not self.active:
            return "off"
        if self._alarm:
            return "alarm"
        if self._last_update is None:
            return "waiting"
        # packets stopping while armed is itself suspicious (power or wifi cut)
        if now - self._last_update > STALE:
            return "offline"
        if self._activity >= self.trip:
            return "movement"
        return "armed"

    def snapshot(self, now=None):
        """JSON view for the dashboard and the phone."""
        now = time.time() if now is None else now
        state = self.state(now)
        return {
            "state": state,
            "alarm": state == "alarm",
            "active": self.active,
            "activity": self._activity,
            "alarm_at": self._alarm_at,
            "trip": self.trip,
            "dwell": self.dwell,
        }
