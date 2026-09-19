"""Water-pump control through the ESP32 USB serial link.

The relay is connected to ESP32 IO25. Raspberry Pi never drives the relay
directly; it sends PUMP_ON/PUMP_OFF through farm.node_serial. The ESP32
also enforces its own maximum runtime, so a Pi or dashboard failure cannot
leave the pump running indefinitely.
"""
import logging
import threading
import time

from . import config, node_serial

log = logging.getLogger("actuator")


class Pump:
    def __init__(self, pump_id: int, pin: int, link: node_serial.NodeSerial):
        self.id = pump_id
        self.pin = pin
        self.link = link
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.link.pump_running()

    @property
    def run_seconds(self) -> float:
        return self.link.pump_state_seconds() if self.running else 0.0

    def can_start(self):
        if self.running:
            return False, "already running"
        rested = self.link.pump_rest_seconds()
        if rested is not None and rested < config.PUMP_MIN_REST_S:
            return False, (
                f"resting {rested:.0f}s of {config.PUMP_MIN_REST_S}s minimum"
            )
        return True, "ok"

    def start(self, force: bool = False):
        with self._lock:
            allowed, reason = self.can_start()
            if not allowed and not force:
                log.info("pump %d start refused: %s", self.id, reason)
                return False, reason
            ok, reason = self.link.send_command("PUMP_ON")
            if ok:
                log.info("pump %d ON requested through ESP32", self.id)
                return True, "started"
            log.error("pump %d start failed: %s", self.id, reason)
            return False, reason

    def stop(self, reason: str = "commanded"):
        with self._lock:
            if not self.running:
                return False, "already stopped"
            ok, detail = self.link.send_command("PUMP_OFF")
            if ok:
                log.info("pump %d OFF requested (%s)", self.id, reason)
                return True, reason
            log.error("pump %d stop failed: %s", self.id, detail)
            return False, detail

    def enforce_max_runtime(self):
        if self.running and self.run_seconds > config.PUMP_MAX_RUN_S:
            self.stop(f"safety cutoff at {config.PUMP_MAX_RUN_S}s")
            return f"max runtime {config.PUMP_MAX_RUN_S}s exceeded"
        return None

    def close(self):
        if self.running:
            self.link.send_command("PUMP_OFF")


class Hardware:
    def __init__(self):
        self.link = node_serial.get_link()
        self.pumps = {
            pid: Pump(pid, pin, self.link)
            for pid, pin in config.PUMP_PINS.items()
        }

    def attach_button(self, handler):
        # The current wiring has no Raspberry Pi GPIO button. A button can
        # later be reported by the ESP32 without introducing a second owner.
        log.info("physical button disabled; use dashboard controls")

    def pump(self, pump_id: int = 1) -> Pump:
        return self.pumps[pump_id]

    def state(self) -> dict:
        return {
            pid: {
                "running": p.running,
                "pin": p.pin,
                "run_seconds": round(p.run_seconds, 1),
                "rest_seconds": (
                    round(p.link.pump_rest_seconds(), 1)
                    if p.link.pump_rest_seconds() is not None else None
                ),
            }
            for pid, p in self.pumps.items()
        }

    def all_stop(self, reason: str = "shutdown"):
        for pump in self.pumps.values():
            if pump.running:
                pump.stop(reason)

    def close(self):
        self.all_stop("shutdown")


_hardware = None


def get_hardware() -> Hardware:
    global _hardware
    if _hardware is None:
        _hardware = Hardware()
    return _hardware


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    link = node_serial.get_link()
    link.start()
    print("Waiting for ESP32 serial connection...")
    time.sleep(2)
    pump = get_hardware().pump(1)
    print("Requesting pump ON for 1.5 seconds (keep pump power disconnected).")
    ok, reason = pump.start(force=True)
    print(ok, reason)
    time.sleep(1.5)
    print(pump.stop("self-test"))
    link.stop()
