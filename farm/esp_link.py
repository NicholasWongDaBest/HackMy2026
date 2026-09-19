"""Serial link to the ESP32 node: sensor readings in, pump commands out.

This module owns the serial port and replaces the GPIO pump backend when
config.PUMP_BACKEND == "esp". It exposes get_hardware(), matching the
interface actuator.Hardware provides, so control.py and the dashboard do
not care which board drives the relay.

WHY THE PI STILL ENFORCES SAFETY
The ESP32 has its own 10-second maximum-runtime cutoff because a Pi that
has lost the cable cannot stop a pump. The Pi keeps its own max-runtime
and minimum-rest rules as a second independent safety layer.

Run:  python3 -m farm.esp_link      (link self-test, no water needed)
"""
import json
import logging
import os
import threading
import time

import serial

from . import config, database, validation

try:
    import fcntl
except ImportError:  # Windows development; the production target is Linux.
    fcntl = None

log = logging.getLogger("esp_link")

SOURCE = f"serial:{config.NODE_SERIAL_PORT}"


class SerialOwnershipError(RuntimeError):
    """Another process already owns the ESP32 serial device."""


class EspLink:
    """Owns the serial port. One reader thread, locked writes."""

    def __init__(self):
        self._port = None
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._owner_lock = None
        self.connected = False
        self.last_line_at = 0.0
        self.esp_pump_state = None     # what the BOARD last reported
        self.esp_last_reason = None
        self.last_error = None

    # -- lifecycle ------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
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
        self._close_port()

    def _acquire_owner_lock(self):
        if fcntl is None or self._owner_lock is not None:
            return
        lock = open(config.NODE_SERIAL_LOCK, "a+", encoding="ascii")
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock.close()
            raise SerialOwnershipError(
                "ESP32 serial link is already owned by another process"
            ) from exc
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()))
        lock.flush()
        self._owner_lock = lock

    def _release_owner_lock(self):
        if self._owner_lock is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self._owner_lock.fileno(), fcntl.LOCK_UN)
            self._owner_lock.close()
        finally:
            self._owner_lock = None

    def _close_port(self):
        try:
            if self._port:
                self._port.close()
        except Exception:
            pass
        self._port = None
        self.connected = False
        self._release_owner_lock()

    def _open(self):
        if not config.NODE_SERIAL_PORT:
            raise SerialOwnershipError(
                "NODE_SERIAL_PORT is not configured; use a /dev/serial/by-id/... path"
            )
        self._acquire_owner_lock()
        try:
            self._port = serial.Serial(
                port=config.NODE_SERIAL_PORT,
                baudrate=config.NODE_SERIAL_BAUD,
                timeout=1,
            )
        except Exception:
            self._release_owner_lock()
            raise
        self.connected = True
        self.last_error = None
        log.info("opened %s at %d baud",
                 config.NODE_SERIAL_PORT, config.NODE_SERIAL_BAUD)
        # A reconnect always begins from the safest known state.
        self.pump(False)

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
                self._close_port()
                for _ in range(5):
                    if self._stop.is_set():
                        break
                    time.sleep(1)
            except Exception as exc:
                self.last_error = str(exc)
                log.exception("reader error")
                self._close_port()
                self._stop.wait(5)

        self._close_port()

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
        state = "on" if on else "off"
        sent = self.send({"cmd": "pump", "state": state})
        if sent:
            # Optimistic state for an immediate dashboard response. The
            # ESP32's status line confirms or corrects it moments later.
            self.esp_pump_state = state
            self.esp_last_reason = "command_sent"
        return sent

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

    @property
    def running(self) -> bool:
        reported = self.link.esp_pump_state
        if reported == "off" and self._running:
            self._running = False
            self.started_at = None
            self.stopped_at = time.time()
        elif reported == "on" and not self._running:
            self._running = True
            self.started_at = time.time()
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
            log.info("pump %d ON (esp32)", self.id)
            return True, "started"

    def stop(self, reason: str = "commanded"):
        with self._lock:
            was_running = self.running
            if not self.link.pump(False):
                return False, "could not send stop command to ESP32"
            self._running = False
            self.started_at = None
            self.stopped_at = time.time()
            log.info("pump %d OFF (%s)", self.id, reason)
            return True, reason if was_running else "already stopped; stop command sent"

    def enforce_max_runtime(self):
        """Apply the Pi-side cutoff and observe the ESP32-side cutoff."""
        if not self.running:
            return None

        if self.run_seconds > config.PUMP_MAX_RUN_S:
            self.stop(f"safety cutoff at {config.PUMP_MAX_RUN_S}s")
            return f"max runtime {config.PUMP_MAX_RUN_S}s exceeded"

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
