"""Compatibility entry point for the ESP32 serial reader.

The bidirectional implementation now lives in :mod:`farm.esp_link` so
sensor input and pump output cannot accidentally use separate serial
objects. A Linux advisory lock also prevents this command and the Flask
application from opening the device at the same time.

Normally run only ``python3 -m farm.app``. This module is retained as a
diagnostic reader for deployments that previously invoked it directly.
"""
import logging
import signal
import threading

from .esp_link import EspLink


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    link = EspLink()
    stopping = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    link.start()
    try:
        while not stopping.wait(1):
            pass
    finally:
        link.close()


if __name__ == "__main__":
    main()
