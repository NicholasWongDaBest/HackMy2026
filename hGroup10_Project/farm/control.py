"""The control loop: poll -> store -> decide -> act -> log.

Runs as a background thread inside the Flask app. The dashboard and the
automation both use the singleton in farm/esp_link.py, so one process
owns the ESP32 serial connection and all relay commands are serialized.

The automation rule, stated plainly so it can be defended to a judge:

    IF   moisture < MOISTURE_ON_BELOW      -> start pump
    IF   moisture > MOISTURE_OFF_ABOVE     -> stop pump
    ELSE                                    -> hold current state

    The gap between those two thresholds is hysteresis. Without it the
    pump chatters on and off around a single setpoint.

    Overriding everything, in farm/esp_link.py and the ESP32 firmware:
      * pump runs at most PUMP_MAX_RUN_S
      * pump rests at least PUMP_MIN_REST_S between runs
      * a reading older than READING_STALE_S is not acted on at all

Scheduled automation decisions write to automation_log; fast health-only
checks are logged only when the sensor changes state.
"""
import logging
import threading
import time

from . import config, database, esp_link, sensor_health, sensors

log = logging.getLogger("control")


class Controller:
    def __init__(self):
        self.hw = esp_link.get_hardware()
        self.sensor_health = sensor_health.SensorHealth(
            source_id=(
                f"modbus:{config.SENSOR_POSITION}:slave-{config.RS485_SLAVE}"
            ),
            zone=config.SENSOR_POSITION,
            affected_sensors=config.SENSOR_REGISTERS.keys(),
        )
        self.latest = {}
        self.latest_at = 0.0
        self.last_error = None
        self.last_decision = None
        self._last_health_transition = None
        self._thread = None
        self._stop = threading.Event()
        self._manual_until = 0.0

    # -- readings -------------------------------------------------------
    def poll_once(self, store: bool = True) -> dict:
        """Read the RS485 probe and store one row per measurand.

        The probe is the decision source: it reports calibrated moisture,
        temperature and EC, so the number the automation fires on needs no
        scaling factor anyone would have to justify to a judge. Raises on
        failure -- a failed read must never become a stored number.

        The ESP32 link independently receives, validates and stores its
        canopy readings. They appear on the dashboard from MySQL and are
        never fed into this RS485 soil-moisture decision.
        """
        readings = sensors.read_all()
        self.latest = readings
        self.latest_at = time.time()
        self._last_health_transition = self.sensor_health.mark_success(
            at=self.latest_at
        )
        self.last_error = None

        if store:
            try:
                for sensor_type, value in readings.items():
                    database.insert_reading(
                        config.SENSOR_POSITION, value, sensor_type
                    )
            except Exception:
                # A database problem must not be mistaken for a removed
                # sensor or stop fresh readings from protecting the pump.
                log.exception("could not store probe readings")
            else:
                log.info("stored %d probe readings: %s", len(readings), readings)
        elif self._last_health_transition:
            log.info("probe state changed to online: %s", readings)

        return readings

    def _handle_sensor_failure(self, exc: Exception) -> str | None:
        data_error_type = getattr(sensors, "SensorDataError", ())
        state = "invalid" if isinstance(exc, data_error_type) else "offline"
        transition = self.sensor_health.mark_failure(state, exc)
        self._last_health_transition = transition
        self.last_error = str(exc)
        if transition:
            log.error("probe state changed to %s: %s", state, exc)
        else:
            log.debug("probe remains %s: %s", state, exc)
        return transition

    def _handle_unexpected_sensor_failure(self, exc: Exception) -> str | None:
        transition = self.sensor_health.mark_failure("error", exc)
        self._last_health_transition = transition
        self.last_error = str(exc)
        return transition

    # -- decision -------------------------------------------------------
    def decide(self) -> tuple:
        """Returns (decision, reason, source). Pure logic: it reads state
        and returns a verdict, it does not touch the relay."""
        pump = self.hw.pump(1)

        cutoff = pump.enforce_max_runtime()
        if cutoff:
            return "pump_off", cutoff, "safety"

        allowed, health_reason = self.sensor_health.can_irrigate(
            config.SENSOR_POSITION
        )
        if not allowed:
            if pump.running:
                return "pump_off", f"{health_reason} -- failing safe", "safety"
            return "hold", f"{health_reason} -- irrigation blocked", "safety"

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

        Pressing ON sends a command immediately. The ESP32 still owns the
        independent 10-second cutoff; repeated commands cannot silently
        extend a run that is already in progress.

        Nothing is needed to stop the automation fighting the button:
        after any stop, PUMP_MIN_REST_S already blocks an automatic
        restart, and while the pump is running the automation's only
        options are "hold" or "stop".
        """
        pump = self.hw.pump(1)
        if action == "on":
            allowed, health_reason = self.sensor_health.can_irrigate(
                config.SENSOR_POSITION
            )
            if not allowed:
                reason = f"manual start refused: {health_reason}"
                self.act("hold", reason, "safety")
                return False, reason
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
    def tick(self, store: bool = True):
        poll_ok = False
        transition = None
        try:
            self.poll_once(store=store)
            poll_ok = True
            transition = self._last_health_transition
        except sensors.SensorError as exc:
            transition = self._handle_sensor_failure(exc)
        except Exception as exc:
            transition = self._handle_unexpected_sensor_failure(exc)
            log.exception("poll failed")

        allowed, _ = self.sensor_health.can_irrigate(config.SENSOR_POSITION)
        must_enforce_safety = not allowed and self.hw.pump(1).running
        if not (store or transition or must_enforce_safety):
            return poll_ok

        try:
            decision, reason, source = self.decide()
            self.act(decision, reason, source)
        except Exception:
            log.exception("decision failed -- failing safe, stopping pump")
            self.hw.all_stop("controller error")
        return poll_ok

    def _run(self):
        log.info(
            "control loop started: health every %.1fs, store every %ds, "
            "on<%.1f%% off>%.1f%%, max run %ds, min rest %ds",
            config.SENSOR_HEALTH_CHECK_S, config.POLL_INTERVAL_S,
            config.MOISTURE_ON_BELOW,
            config.MOISTURE_OFF_ABOVE, config.PUMP_MAX_RUN_S,
            config.PUMP_MIN_REST_S,
        )
        next_check = 0.0
        next_store = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_check:
                store = now >= next_store
                self.tick(store=store)
                next_check = now + max(0.1, config.SENSOR_HEALTH_CHECK_S)
                if store:
                    next_store = now + max(1, config.POLL_INTERVAL_S)

            # Wake at least once per second so max runtime remains prompt.
            self.hw.pump(1).enforce_max_runtime()
            wait_s = min(1.0, max(0.05, next_check - time.monotonic()))
            self._stop.wait(wait_s)
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
            "sensor_health": self.sensor_health.snapshot(),
            "pumps": self.hw.state(),
            "last_decision": self.last_decision,
            "manual_override_s": max(0, round(self._manual_until - time.time())),
            "thresholds": {
                "on_below": config.MOISTURE_ON_BELOW,
                "off_above": config.MOISTURE_OFF_ABOVE,
                "max_run_s": config.PUMP_MAX_RUN_S,
                "min_rest_s": config.PUMP_MIN_REST_S,
                "poll_interval_s": config.POLL_INTERVAL_S,
                "health_check_s": config.SENSOR_HEALTH_CHECK_S,
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
