"""Detect a possible collapse: sustained movement, then prolonged stillness."""

import time

# Calibrated on a real 56 s capture with no event: a quiet link scored p50 0.21
# and never passed 0.65, while amplified movement reached 0.78 and above.
MOVE = 0.70         # sustained movement
STILL = 0.35        # motionless
ACTIVE_MIN = 2.0    # seconds of movement before stillness counts
HOLD = 20.0         # seconds of stillness before the alarm
STALE = 5.0         # seconds without packets before reading as offline
QUIET = 0.25        # score of an undisturbed link


def link_contrast(score):
    """Rescale a link score so an undisturbed link reads as zero."""
    return max(0.0, min(1.0, (float(score) - QUIET) / (1.0 - QUIET)))


class CollapseWatch:
    """Movement, then prolonged stillness.

    Cannot tell a collapse from someone leaving the room; that needs a presence
    signal such as breathing, which these links do not carry.
    """

    def __init__(self, move=MOVE, still=STILL, active_min=ACTIVE_MIN, hold=HOLD):
        self.move = move
        self.still = still
        self.active_min = active_min
        self.hold = hold
        self.reset()

    def reset(self):
        """Forget the current episode."""
        self._run = 0.0
        self._still_since = None
        self._armed = False
        self._alarm = False
        self._activity = 0.0
        self._last_update = None

    def update(self, activity, now=None):
        """Feed the room's motion score, return the new state."""
        now = time.time() if now is None else now
        previous = self._last_update
        self._last_update = now
        self._activity = float(activity)
        elapsed = 0.0 if previous is None else max(0.0, now - previous)

        if self._activity >= self.move:
            self._run += elapsed
            self._still_since = None
            if self._run >= self.active_min:
                self._armed = True
                self._alarm = False
        else:
            self._run = 0.0
            if self._activity < self.still and self._still_since is None:
                self._still_since = now
            if (self._armed and self._still_since is not None
                    and now - self._still_since >= self.hold):
                self._alarm = True

        return self.state(now)

    def still_for(self, now=None):
        """Seconds of continuous stillness."""
        if self._still_since is None:
            return 0.0
        now = time.time() if now is None else now
        return max(0.0, now - self._still_since)

    def state(self, now=None):
        now = time.time() if now is None else now
        if self._last_update is None:
            return "waiting"
        if now - self._last_update > STALE:
            return "offline"
        if self._alarm:
            return "motionless"
        if self._armed and self._still_since is not None:
            return "settling"
        if self._activity >= self.move:
            return "movement"
        return "quiet"

    def snapshot(self, now=None):
        """JSON view for the dashboard."""
        now = time.time() if now is None else now
        state = self.state(now)
        return {
            "state": state,
            "alarm": state == "motionless",
            "armed": self._armed,
            "activity": self._activity,
            "still_for": self.still_for(now) if self._still_since else 0.0,
            "hold": self.hold,
            "move": self.move,
            "still": self.still,
            "quiet": QUIET,
        }
