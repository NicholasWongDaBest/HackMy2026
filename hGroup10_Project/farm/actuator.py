"""Pump and button hardware.

The relay module supplied in the kit is ACTIVE LOW -- pulling the input
pin low energises the coil. gpiozero's active_high=False expresses that,
so everywhere else in the codebase on() means "pump running" and nobody
has to remember the inversion.

Safety rules enforced here, not in the caller:
  * a pump that has run for PUMP_MAX_RUN_S is stopped regardless of what
    the automation wants -- a probe stuck at 0% must not flood the tray
  * a pump must rest PUMP_MIN_REST_S between runs
  * GPIO is released on exit so a crash cannot leave a pump energised

Run:  python3 -m farm.actuator      (relay self-test, no water needed)
"""
import logging
import threading
import time

from gpiozero import Button, OutputDevice

from . import config

log = logging.getLogger("actuator")


class Pump:
    def __init__(self, pump_id: int, pin: int):
        self.id = pump_id
        self.pin = pin
        self.device = OutputDevice(
            pin,
            active_high=config.RELAY_ACTIVE_HIGH,
            initial_value=False,
        )
        self.started_at = None
        self.stopped_at = 0.0
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.device.value == 1

    @property
    def run_seconds(self) -> float:
        return time.time() - self.started_at if self.started_at else 0.0

    def can_start(self):
        """(allowed, reason). Reason is shown on the dashboard so a judge
        can see why a start was refused rather than guessing."""
        if self.running:
            return False, "already running"
        rested = time.time() - self.stopped_at
        if rested < config.PUMP_MIN_REST_S:
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
            self.device.on()
            self.started_at = time.time()
            log.info("pump %d ON", self.id)
            return True, "started"

    def stop(self, reason: str = "commanded"):
        with self._lock:
            if not self.running:
                return False, "already stopped"
            self.device.off()
            self.started_at = None
            self.stopped_at = time.time()
            log.info("pump %d OFF (%s)", self.id, reason)
            return True, reason

    def enforce_max_runtime(self):
        """Called from the control loop every tick. Returns a reason string
        if it had to intervene."""
        if self.running and self.run_seconds > config.PUMP_MAX_RUN_S:
            self.stop(f"safety cutoff at {config.PUMP_MAX_RUN_S}s")
            return f"max runtime {config.PUMP_MAX_RUN_S}s exceeded"
        return None

    def close(self):
        try:
            self.device.off()
            self.device.close()
        except Exception:
            pass


class Hardware:
    """Single owner of every GPIO pin in the system.

    Both the automation loop and the web dashboard act through this one
    object inside one process. Two processes cannot share a GPIO line, so
    this is deliberately a singleton rather than something each module
    instantiates for itself.
    """

    def __init__(self):
        self.pumps = {pid: Pump(pid, pin) for pid, pin in config.PUMP_PINS.items()}
        self.button = None
        self._button_handler = None

    def attach_button(self, handler):
        """Wire the physical push button to a callback. Pull-up is internal,
        so the button just shorts the pin to ground -- no resistor needed."""
        self._button_handler = handler
        self.button = Button(config.BUTTON_PIN, pull_up=True, bounce_time=0.15)
        self.button.when_pressed = self._on_press
        log.info("button attached on GPIO%d", config.BUTTON_PIN)

    def _on_press(self):
        log.info("physical button pressed")
        if self._button_handler:
            try:
                self._button_handler()
            except Exception:
                log.exception("button handler failed")

    def pump(self, pump_id: int = 1) -> Pump:
        return self.pumps[pump_id]

    def state(self) -> dict:
        return {
            pid: {
                "running": p.running,
                "pin": p.pin,
                "run_seconds": round(p.run_seconds, 1),
                "rest_seconds": round(time.time() - p.stopped_at, 1) if p.stopped_at else None,
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


_hardware = None


def get_hardware() -> Hardware:
    global _hardware
    if _hardware is None:
        _hardware = Hardware()
    return _hardware


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    hw = get_hardware()
    print("Relay self-test -- listen for the click, no water required.")
    for pid in hw.pumps:
        print(f"pump {pid} on GPIO{hw.pump(pid).pin} ...")
        hw.pump(pid).start(force=True)
        time.sleep(1.5)
        hw.pump(pid).stop("self-test")
        time.sleep(0.5)
    print("done")
    hw.close()
