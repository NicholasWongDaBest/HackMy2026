"""Thread-safe health state for physical sensor sources.

The controller writes this state while Flask reads it for the dashboard.
Health is tracked per physical source, not per displayed measurand: removing
the zone-1 3-in-1 Modbus probe makes moisture, temperature and EC unavailable
together.
"""
import threading
import time


class SensorHealth:
    """Health and irrigation eligibility for one physical sensor source."""

    def __init__(self, source_id: str, zone: str, affected_sensors,
                 clock=time.time):
        self.source_id = source_id
        self.zone = zone
        self.affected_sensors = tuple(affected_sensors)
        self._clock = clock
        self._lock = threading.Lock()
        self._state = "starting"
        self._last_success_at = None
        self._failure_since = None
        self._error = None

    def mark_success(self, at=None):
        """Record a complete valid read and return the state transition."""
        at = self._clock() if at is None else at
        with self._lock:
            previous = self._state
            self._state = "online"
            self._last_success_at = at
            self._failure_since = None
            self._error = None
            if previous == "starting":
                return "online"
            if previous != "online":
                return "recovered"
            return None

    def mark_failure(self, state: str, error, at=None):
        """Record an offline/invalid/error state without duplicate events."""
        if state not in {"offline", "invalid", "error"}:
            raise ValueError(f"unsupported sensor health state '{state}'")

        at = self._clock() if at is None else at
        error = str(error)
        with self._lock:
            previous = self._state
            transition = state if previous != state else None
            if previous == "online" or self._failure_since is None:
                self._failure_since = at
            self._state = state
            self._error = error
            return transition

    def can_irrigate(self, zone: str):
        """Return whether this source permits irrigation for *zone*."""
        with self._lock:
            if zone != self.zone:
                return True, "sensor source does not govern this zone"
            if self._state == "online":
                return True, "sensor online"
            if self._state == "starting":
                return False, "soil sensor has not produced a valid reading yet"
            if self._state == "offline":
                return False, "soil sensor communication is offline"
            if self._state == "invalid":
                return False, "soil sensor returned an invalid reading"
            return False, "soil sensor health check failed"

    def snapshot(self, now=None) -> dict:
        now = self._clock() if now is None else now
        with self._lock:
            allowed = self._state == "online"
            return {
                "source_id": self.source_id,
                "zone": self.zone,
                "state": self._state,
                "affected_sensors": list(self.affected_sensors),
                "last_success_at": self._last_success_at,
                "seconds_since_success": (
                    round(now - self._last_success_at, 1)
                    if self._last_success_at is not None else None
                ),
                "failure_since": self._failure_since,
                "failure_seconds": (
                    round(now - self._failure_since, 1)
                    if self._failure_since is not None else None
                ),
                "error": self._error,
                "can_irrigate": allowed,
            }
