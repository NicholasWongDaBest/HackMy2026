"""Single bidirectional USB link to the ESP32 sensor/pump controller.

The same serial connection carries newline-delimited sensor JSON from the
ESP32 and PUMP_ON/PUMP_OFF commands back to it. Keeping one owner avoids
the failure where a reader and the dashboard both open /dev/ttyUSB0.
"""
import json
import logging
import signal
import threading
import time

import serial

from . import config, database, validation

log = logging.getLogger("node_serial")


class NodeSerialError(RuntimeError):
    """The ESP32 link has no usable reading or cannot accept a command."""


class NodeSerial:
    def __init__(self):
        self.port = None
        self._thread = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._latest = {}
        self._latest_at = 0.0
        self._pump_running = False
        self._pump_changed_at = time.time()
        self._pump_ever_on = False
        self.last_error = None

    @property
    def source(self) -> str:
        return f"serial:{config.NODE_SERIAL_PORT}"

    def _open_port(self) -> serial.Serial:
        return serial.Serial(
            port=config.NODE_SERIAL_PORT,
            baudrate=config.NODE_SERIAL_BAUD,
            timeout=1,
            write_timeout=1,
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="esp32-serial"
        )
        self._thread.start()

    def stop(self) -> None:
        try:
            self.send_command("PUMP_OFF")
        except Exception:
            pass
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._close_port()

    def _close_port(self) -> None:
        with self._write_lock:
            try:
                if self.port:
                    self.port.close()
            except Exception:
                pass
            self.port = None

    def _set_pump_state(self, running: bool) -> None:
        with self._state_lock:
            if self._pump_running != running:
                self._pump_changed_at = time.time()
            self._pump_running = running
            if running:
                self._pump_ever_on = True

    def pump_running(self) -> bool:
        with self._state_lock:
            return self._pump_running

    def pump_state_seconds(self) -> float:
        with self._state_lock:
            return max(0.0, time.time() - self._pump_changed_at)

    def pump_rest_seconds(self):
        with self._state_lock:
            if self._pump_running or not self._pump_ever_on:
                return None
            return max(0.0, time.time() - self._pump_changed_at)

    def snapshot(self) -> tuple:
        with self._state_lock:
            if not self._latest:
                detail = self.last_error or "waiting for the first ESP32 reading"
                raise NodeSerialError(detail)
            return dict(self._latest), self._latest_at

    def send_command(self, command: str) -> tuple:
        command = command.strip().upper()
        if command not in {"PUMP_ON", "PUMP_OFF", "PUMP_STATUS"}:
            return False, f"unsupported ESP32 command '{command}'"

        with self._write_lock:
            if self.port is None or not self.port.is_open:
                return False, f"ESP32 serial port {config.NODE_SERIAL_PORT} is not connected"
            try:
                self.port.write((command + "\n").encode("ascii"))
                self.port.flush()
            except serial.SerialException as exc:
                self.last_error = str(exc)
                return False, f"serial write failed: {exc}"

        # Make the web response immediate. The ESP32 status event confirms
        # or corrects this optimistic state a moment later.
        if command == "PUMP_ON":
            self._set_pump_state(True)
        elif command == "PUMP_OFF":
            self._set_pump_state(False)
        log.info("sent %s to ESP32", command)
        return True, "command sent"

    def _store_sensor(self, raw: bytes) -> None:
        try:
            result = validation.validate_sensor_message(raw)
        except validation.Rejected as exc:
            database.record_rejection(self.source, str(exc), raw)
            return

        database.insert_reading(
            result["sensor_position"],
            result["sensor_value"],
            result["sensor_type"],
        )
        with self._state_lock:
            self._latest[result["sensor_type"]] = result["sensor_value"]
            self._latest_at = time.time()
            self.last_error = None
        log.info(
            "stored %s = %s (%s)",
            result["sensor_type"],
            result["sensor_value"],
            result["sensor_position"],
        )

    def handle_line(self, raw: bytes) -> None:
        raw = raw.strip()
        if not raw:
            return

        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            database.record_rejection(self.source, f"malformed serial JSON: {exc}", raw)
            return

        if "sensor_value" in message:
            self._store_sensor(raw)
            return

        if message.get("type") == "pump":
            state = message.get("state")
            if state in {"on", "off"}:
                self._set_pump_state(state == "on")
                log.info("ESP32 reports pump %s (%s)", state, message.get("reason", ""))
            return

        if message.get("type") == "error" or "error" in message:
            self.last_error = str(message.get("message") or message.get("error"))
            log.warning("ESP32 error: %s", self.last_error)
            return

        log.info("ESP32 status: %s", message)

    def _run(self) -> None:
        while not self._stop.is_set():
            if self.port is None:
                try:
                    with self._write_lock:
                        self.port = self._open_port()
                    self.last_error = None
                    log.info(
                        "opened %s at %d baud",
                        config.NODE_SERIAL_PORT,
                        config.NODE_SERIAL_BAUD,
                    )
                except (OSError, serial.SerialException) as exc:
                    self.last_error = str(exc)
                    log.error("cannot open ESP32 serial port: %s", exc)
                    self._stop.wait(5)
                    continue

            try:
                line = self.port.readline()
                if line:
                    self.handle_line(line)
            except serial.SerialException as exc:
                self.last_error = str(exc)
                log.error("ESP32 serial error: %s; retrying", exc)
                self._close_port()
                self._stop.wait(2)
            except Exception as exc:
                self.last_error = str(exc)
                log.exception("ESP32 line handler failed")
                self._stop.wait(1)

        self._close_port()


_link = None


def get_link() -> NodeSerial:
    global _link
    if _link is None:
        _link = NodeSerial()
    return _link


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    link = get_link()
    link.start()
    stopping = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    while not stopping.wait(1):
        pass
    link.stop()


if __name__ == "__main__":
    main()
