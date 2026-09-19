"""ESP32 sensor node reader (USB serial).

The ESP32 emits newline-delimited JSON over USB. This worker reads those
lines, puts every one through the SAME validator that guards the MQTT
path, and stores what passes.

That is the point: the serial link is not privileged. A board with
corrupt firmware, a noisy cable or a judge with a USB-serial adapter is
just another untrusted source. Rejections land in rejected_messages with
a reason, exactly like a hostile broadcast.

Run:  python3 -m farm.node_serial
"""
import logging
import signal
import time

import serial

from . import config, database, validation

log = logging.getLogger("node_serial")

SOURCE = f"serial:{config.NODE_SERIAL_PORT}"


def open_port() -> serial.Serial:
    return serial.Serial(
        port=config.NODE_SERIAL_PORT,
        baudrate=config.NODE_SERIAL_BAUD,
        timeout=2,
    )


def handle_line(raw: bytes) -> None:
    """One line from the board. Never raises -- a bad line must not stop
    the reader, it must be recorded and stepped over."""
    raw = raw.strip()
    if not raw:
        return

    # Status/heartbeat lines carry no reading and are not errors.
    if b'"sensor_value"' not in raw:
        log.info("node status: %s", raw[:120].decode("utf-8", errors="replace"))
        return

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
    log.info(
        "stored %s = %s (%s)",
        result["sensor_type"], result["sensor_value"], result["sensor_position"],
    )


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    running = {"on": True}
    signal.signal(signal.SIGINT, lambda *_: running.update(on=False))
    signal.signal(signal.SIGTERM, lambda *_: running.update(on=False))

    port = None
    while running["on"]:
        try:
            if port is None:
                port = open_port()
                log.info(
                    "opened %s at %d baud",
                    config.NODE_SERIAL_PORT, config.NODE_SERIAL_BAUD,
                )
            line = port.readline()
            if line:
                handle_line(line)
        except serial.SerialException as exc:
            # Board unplugged or reset. Do not spin: back off and retry,
            # so a knocked cable costs us a few seconds, not the run.
            log.error("serial error on %s: %s -- retrying in 5s",
                      config.NODE_SERIAL_PORT, exc)
            try:
                if port:
                    port.close()
            except Exception:
                pass
            port = None
            for _ in range(5):
                if not running["on"]:
                    break
                time.sleep(1)
        except Exception:
            log.exception("unexpected reader error")
            time.sleep(1)

    if port:
        port.close()
    log.info("stopped")


if __name__ == "__main__":
    main()
