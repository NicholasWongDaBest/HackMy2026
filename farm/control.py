"""The control loop: poll -> store -> decide -> act -> log.

Runs as a background thread inside the Flask app so that exactly one
process owns the GPIO lines. The dashboard's manual button and the
automation both act through this module, which is why the physical
button, the web button and the automation can never fight over the relay.

The automation rule, stated plainly so it can be defended to a judge:

    IF   moisture < MOISTURE_ON_BELOW      -> start pump
    IF   moisture > MOISTURE_OFF_ABOVE     -> stop pump
    ELSE                                    -> hold current state

    The gap between those two thresholds is hysteresis. Without it the
    pump chatters on and off around a single setpoint.

    Overriding everything, in farm/actuator.py:
      * pump runs at most PUMP_MAX_RUN_S
      * pump rests at least PUMP_MIN_REST_S between runs
      * a reading older than READING_STALE_S is not acted on at all

Every pass writes one row to automation_log with the readings it saw.
"""
import logging
import threading
import time

from . import actuator, config, database, node_serial, sensors

log = logging.getLogger("control")


class Controller:
    def __init__(self):
        self.hw = actuator.get_hardware()
        self.latest = {}
        self.latest_at = 0.0
        # The ESP32's own channels, kept for display only. They never
        # take part in the irrigation decision.
        self.node_latest = {}
        self.node_latest_at = 0.0
        self.node_error = None
        self.last_error = None
        self.last_decision = None
        self._thread = None
        self._stop = threading.Event()
        self._manual_until = 0.0

    # -- readings -------------------------------------------------------
    def poll_once(self) -> dict:
        """Read the RS485 probe and store one row per measurand.

        The probe is the decision source: it reports calibrated moisture,
        temperature and EC, so the number the automation fires on needs no
        scaling factor anyone would have to justify to a judge. Raises on
        failure -- a failed read must never become a stored number.

        The ESP32's channels are collected separately. Its serial reader
        already validates and stores each row as it arrives, so they are
        only snapshotted here for the dashboard, never inserted twice and
        never fed into decide().
        """
        readings = sensors.read_all()
        for sensor_type, value in readings.items():
            database.insert_reading(config.SENSOR_POSITION, value, sensor_type)
        self.latest = readings
        self.latest_at = time.time()
        self.last_error = None
        log.info("stored %d probe readings: %s", len(readings), readings)

        try:
            self.node_latest, self.node_latest_at = self.link.snapshot()
            self.node_error = None
        except node_serial.NodeSerialError as exc:
            # The node being quiet is not a reason to stop irrigating:
            # the probe is what the decision depends on.
            self.node_latest, self.node_latest_at = {}, 0.0
            self.node_error = str(exc)

        return readings

    # -- decision -------------------------------------------------------
    def decide(self) -> tuple:
        """Returns (decision, reason, source). Pure logic: it reads state
        and returns a verdict, it does not touch the relay."""
        pump = self.hw.pump(1)

        cutoff = pump.enforce_max_runtime()
        if cutoff:
            return "pump_off", cutoff, "safety"

        if not self.latest:
            return "hold", "no sensor reading yet", "auto"

        age = time.time() - self.latest_at
        if age > config.READING_STALE_S:
            if pump.running:
                return "pump_off", f"reading stale ({age:.0f}s) -- failing safe", "safety"
            return "hold", f"reading stale ({age:.0f}s) -- not irrigating blind", "safety"

        moisture = self.latest.get("moisture")
        if moisture is None:
            return "hold", "no moisture channel in reading", "auto"

        if moisture < config.MOISTURE_ON_BELOW:
            if pump.running:
                return "hold", (
                    f"moisture {moisture}% still below "
                    f"{config.MOISTURE_ON_BELOW}% -- pump already running"
                ), "auto"
            allowed, why = pump.can_start()
            if not allowed:
                return "hold", f"want to irrigate but {why}", "auto"
            return "pump_on", (
                f"moisture {moisture}% below threshold {config.MOISTURE_ON_BELOW}%"
            ), "auto"

        if moisture > config.MOISTURE_OFF_ABOVE:
            if pump.running:
                return "pump_off", (
                    f"moisture {moisture}% above target {config.MOISTURE_OFF_ABOVE}%"
                ), "auto"
            return "hold", (
                f"moisture {moisture}% above target -- nothing to do"
            ), "auto"

        return "hold", (
            f"moisture {moisture}% inside hysteresis band "
            f"{config.MOISTURE_ON_BELOW}-{config.MOISTURE_OFF_ABOVE}%"
        ), "auto"

    def act(self, decision: str, reason: str, source: str) -> None:
        pump = self.hw.pump(1)
        if decision == "pump_on":
            pump.start()
        elif decision == "pump_off":
            pump.stop(reason)

        self.last_decision = {
            "decision": decision, "reason": reason, "source": source,
            "at": time.time(),
        }
        try:
            database.log_decision(decision, reason, source, self.latest, pump.running)
        except Exception:
            log.exception("could not write automation_log")

    # -- manual override ------------------------------------------------
    def manual(self, action: str) -> tuple:
        """The dashboard's ON/OFF buttons. Deliberately no override timer.

        Pressing ON re-sends the command even when the pump is already
        running, which restarts the board's safety window. So pressing ON
        again is how you irrigate for longer -- previously it silently
        extended a countdown that nothing visible explained.

        Nothing is needed to stop the automation fighting the button:
        after any stop, PUMP_MIN_REST_S already blocks an automatic
        restart, and while the pump is running the automation's only
        options are "hold" or "stop".
        """
        pump = self.hw.pump(1)
        if action == "on":
            ok, reason = pump.start(force=True)
        elif action == "off":
            ok, reason = pump.stop("manual stop")
        elif action == "toggle":
            return self.manual("off" if pump.running else "on")
        else:
            return False, f"unknown action '{action}'"

        database.log_decision(
            f"pump_{action}", f"manual: {reason}", "manual",
            self.latest, pump.running,
        )
        return ok, reason

    def resume_auto(self):
        self._manual_until = 0.0

    # -- loop -----------------------------------------------------------
    def tick(self):
        try:
            self.poll_once()
        except sensors.SensorError as exc:
            self.last_error = str(exc)
            log.error("probe read failed: %s", exc)
        except Exception as exc:
            self.last_error = str(exc)
            log.exception("poll failed")

        try:
            decision, reason, source = self.decide()
            self.act(decision, reason, source)
        except Exception:
            log.exception("decision failed -- failing safe, stopping pump")
            self.hw.all_stop("controller error")

    def _run(self):
        log.info(
            "control loop started: poll every %ds, on<%.1f%% off>%.1f%%, "
            "max run %ds, min rest %ds",
            config.POLL_INTERVAL_S, config.MOISTURE_ON_BELOW,
            config.MOISTURE_OFF_ABOVE, config.PUMP_MAX_RUN_S,
            config.PUMP_MIN_REST_S,
        )
        while not self._stop.is_set():
            self.tick()
            # Wake every second so the max-runtime cutoff is enforced
            # promptly rather than up to a full poll interval late.
            for _ in range(config.POLL_INTERVAL_S):
                if self._stop.is_set():
                    break
                self.hw.pump(1).enforce_max_runtime()
                time.sleep(1)
        self.hw.all_stop("loop stopped")

    def start(self):
        try:
            self.hw.attach_button(lambda: self.manual("toggle"))
        except Exception as exc:
            log.warning("no physical button attached: %s", exc)
        self._thread = threading.Thread(target=self._run, daemon=True, name="control")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.hw.close()

    # -- for the dashboard ----------------------------------------------
    def status(self) -> dict:
        return {
            "readings": self.latest,
            "reading_age_s": round(time.time() - self.latest_at, 1) if self.latest_at else None,
            "sensor_error": self.last_error,
            "node_readings": self.node_latest,
            "node_age_s": (
                round(time.time() - self.node_latest_at, 1)
                if self.node_latest_at else None
            ),
            "node_error": self.node_error,
            "pumps": self.hw.state(),
            "last_decision": self.last_decision,
            "manual_override_s": max(0, round(self._manual_until - time.time())),
            "thresholds": {
                "on_below": config.MOISTURE_ON_BELOW,
                "off_above": config.MOISTURE_OFF_ABOVE,
                "max_run_s": config.PUMP_MAX_RUN_S,
                "min_rest_s": config.PUMP_MIN_REST_S,
                "poll_interval_s": config.POLL_INTERVAL_S,
            },
        }


_controller = None


def get_controller() -> Controller:
    global _controller
    if _controller is None:
        _controller = Controller()
    return _controller


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    c = get_controller()
    c.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        c.stop()
