"""Serial link to the ESP32 node: sensor readings in, pump commands out.

This module owns the serial port and replaces the GPIO pump backend when
config.PUMP_BACKEND == "esp". It exposes get_hardware(), matching the
interface actuator.Hardware provides, so control.py and the dashboard do
not care which board drives the relay.

WHY THE PI STILL ENFORCES SAFETY
The ESP32 has its own watchdog (max runtime, link-loss cutoff) because a
Pi that has lost the cable cannot stop a pump. The Pi keeps its own
max-runtime and minimum-rest rules anyway: two independent layers, and
neither depends on the other being correct. The Pi's keepalive is what
the board's watchdog listens for -- stop sending and the pump stops.

Run:  python3 -m app.esp_link      (link self-test, no water needed)
"""
import json
import logging
import threading
import time

import serial

from . import config, database, validation

log = logging.getLogger("esp_link")

SOURCE = f"serial:{config.NODE_SERIAL_PORT}"


class EspLink:
    """Owns the serial port. One reader thread, locked writes."""

    def __init__(self):
        self._port = None
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.connected = False
        self.last_line_at = 0.0
        self.esp_pump_state = None     # what the BOARD last reported
        self.esp_last_reason = None
        self.last_error = None

    # -- lifecycle ------------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="esp_link")
        self._thread.start()

    def close(self):
        self._stop.set()
        try:
            self.pump(False)           # best effort: leave the relay off
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=3)
        if self._port:
            try:
                self._port.close()
            except Exception:
                pass

    def _open(self):
        self._port = serial.Serial(
            port=config.NODE_SERIAL_PORT,
            baudrate=config.NODE_SERIAL_BAUD,
            timeout=1,
        )
        self.connected = True
        self.last_error = None
        log.info("opened %s at %d baud",
                 config.NODE_SERIAL_PORT, config.NODE_SERIAL_BAUD)

    # -- reader ---------------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            try:
                if self._port is None:
                    self._open()
                line = self._port.readline()
                if line:
                    self.last_line_at = time.time()
                    self._handle(line)
            except serial.SerialException as exc:
                # Board unplugged or reset. Back off rather than spin.
                self.connected = False
                self.last_error = str(exc)
                log.error("serial error: %s -- retrying in 5s", exc)
                try:
                    if self._port:
                        self._port.close()
                except Exception:
                    pass
                self._port = None
                for _ in range(5):
                    if self._stop.is_set():
                        break
                    time.sleep(1)
            except Exception:
                log.exception("reader error")
                time.sleep(1)

    def _handle(self, raw: bytes):
        """One line from the board. Never raises: a bad line is recorded
        and stepped over, never allowed to stop the reader."""
        raw = raw.strip()
        if not raw:
            return

        # Status / pump-state lines carry no reading.
        if b'"sensor_value"' not in raw:
            try:
                msg = json.loads(raw.decode("utf-8", errors="replace"))
                if "pump" in msg:
                    self.esp_pump_state = msg["pump"]
                    self.esp_last_reason = msg.get("reason")
                    log.info("board reports pump %s (%s)",
                             msg["pump"], msg.get("reason"))
                else:
                    log.info("node status: %s", raw[:120])
            except Exception:
                log.info("node line: %s", raw[:120])
            return

        # A reading. The serial link is NOT privileged: same gates as MQTT.
        try:
            result = validation.validate_sensor_message(raw)
        except validation.Rejected as exc:
            database.record_rejection(SOURCE, str(exc), raw)
            return
        except Exception as exc:
            log.exception("validator error")
            database.record_rejection(SOURCE, f"handler error: {exc}", raw)
            return

        database.insert_reading(
            result["sensor_position"], result["sensor_value"], result["sensor_type"]
        )
        log.info("stored %s = %s", result["sensor_type"], result["sensor_value"])

    # -- writer ---------------------------------------------------------
    def send(self, obj: dict) -> bool:
        if self._port is None:
            return False
        payload = (json.dumps(obj) + "\n").encode("utf-8")
        try:
            with self._write_lock:
                self._port.write(payload)
            return True
        except Exception as exc:
            self.last_error = str(exc)
            log.error("write failed: %s", exc)
            return False

    def pump(self, on: bool) -> bool:
        return self.send({"cmd": "pump", "state": "on" if on else "off"})

    def status(self) -> dict:
        return {
            "connected": self.connected,
            "port": config.NODE_SERIAL_PORT,
            "board_pump_state": self.esp_pump_state,
            "board_last_reason": self.esp_last_reason,
            "seconds_since_line": (
                round(time.time() - self.last_line_at, 1) if self.last_line_at else None
            ),
            "error": self.last_error,
        }


class EspPump:
    """Same interface as actuator.Pump, but the relay lives on the ESP32.

    'running' is what the Pi believes and commands. The board's own view
    is reported separately in status() so a disagreement between the two
    is visible on the dashboard rather than hidden.
    """

    def __init__(self, pump_id: int, link: EspLink):
        self.id = pump_id
        self.link = link
        self.pin = config.ESP_RELAY_PIN
        self.started_at = None
        self.stopped_at = 0.0
        self._running = False
        self._lock = threading.Lock()
        self._last_keepalive = 0.0

    @property
    def running(self) -> bool:
        return self._running

    @property
    def run_seconds(self) -> float:
        return time.time() - self.started_at if self.started_at else 0.0

    def can_start(self):
        if self._running:
            return False, "already running"
        if not self.link.connected:
            return False, "ESP32 link down -- refusing to command a pump we cannot stop"
        rested = time.time() - self.stopped_at
        if rested < config.PUMP_MIN_REST_S:
            return False, f"resting {rested:.0f}s of {config.PUMP_MIN_REST_S}s minimum"
        return True, "ok"

    def start(self, force: bool = False):
        with self._lock:
            allowed, reason = self.can_start()
            if not allowed and not force:
                log.info("pump %d start refused: %s", self.id, reason)
                return False, reason
            if not self.link.pump(True):
                return False, "could not send command to ESP32"
            self._running = True
            self.started_at = time.time()
            self._last_keepalive = time.time()
            log.info("pump %d ON (esp32)", self.id)
            return True, "started"

    def stop(self, reason: str = "commanded"):
        with self._lock:
            if not self._running:
                return False, "already stopped"
            self.link.pump(False)      # send regardless; stop is never refused
            self._running = False
            self.started_at = None
            self.stopped_at = time.time()
            log.info("pump %d OFF (%s)", self.id, reason)
            return True, reason

    def enforce_max_runtime(self):
        """Called every second by the control loop. Two jobs: the Pi's own
        max-runtime cutoff, and the keepalive the board's watchdog needs.
        Stop sending these and the board shuts the pump off by itself."""
        if not self._running:
            return None

        if self.run_seconds > config.PUMP_MAX_RUN_S:
            self.stop(f"safety cutoff at {config.PUMP_MAX_RUN_S}s")
            return f"max runtime {config.PUMP_MAX_RUN_S}s exceeded"

        now = time.time()
        if now - self._last_keepalive >= config.ESP_KEEPALIVE_S:
            self.link.pump(True)
            self._last_keepalive = now
        return None

    def close(self):
        try:
            self.stop("shutdown")
        except Exception:
            pass


class EspHardware:
    """Drop-in replacement for actuator.Hardware, pump relay on the ESP32."""

    def __init__(self):
        self.link = EspLink()
        self.link.start()
        self.pumps = {1: EspPump(1, self.link)}
        self.button = None
        self._button_handler = None

    def attach_button(self, handler):
        """The physical button is still on the Pi's GPIO if you wired one.
        Absent hardware raises, and control.py logs it and carries on."""
        from gpiozero import Button
        self._button_handler = handler
        self.button = Button(config.BUTTON_PIN, pull_up=True, bounce_time=0.15)
        self.button.when_pressed = self._on_press
        log.info("button attached on GPIO%d", config.BUTTON_PIN)

    def _on_press(self):
        if self._button_handler:
            try:
                self._button_handler()
            except Exception:
                log.exception("button handler failed")

    def pump(self, pump_id: int = 1) -> EspPump:
        return self.pumps[pump_id]

    def state(self) -> dict:
        return {
            pid: {
                "running": p.running,
                "pin": p.pin,
                "backend": "esp32-serial",
                "run_seconds": round(p.run_seconds, 1),
                "rest_seconds": (
                    round(time.time() - p.stopped_at, 1) if p.stopped_at else None
                ),
                "link": self.link.status(),
            }
            for pid, p in self.pumps.items()
        }

    def all_stop(self, reason: str = "shutdown"):
        for p in self.pumps.values():
            p.stop(reason)

    def close(self):
        for p in self.pumps.values():
            p.close()
        if self.button:
            self.button.close()
        self.link.close()


_hardware = None


def get_hardware():
    """Returns the ESP32-backed hardware, or the GPIO one if configured."""
    global _hardware
    if config.PUMP_BACKEND != "esp":
        from . import actuator
        return actuator.get_hardware()
    if _hardware is None:
        _hardware = EspHardware()
    return _hardware


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    hw = get_hardware()
    print("Waiting 3s for the board to announce itself ...")
    time.sleep(3)
    print("link status:", hw.link.status())
    print("Pump ON for 3s -- listen for the relay click.")
    hw.pump(1).start(force=True)
    time.sleep(3)
    hw.pump(1).stop("self-test")
    time.sleep(1)
    print("link status:", hw.link.status())
    hw.close()
