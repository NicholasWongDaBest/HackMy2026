#!/usr/bin/env python3
"""Manual serial utility for isolated Challenge 4 dual-pump bring-up.

This tool does not import the production controller or allocation policy. It
opens the selected serial device only from ``main()`` and never sends an ON
command without a second, pump-specific confirmation from the operator.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Protocol, Sequence


VALID_PUMP_IDS = (1, 2)
VALID_STATES = ("on", "off")
DEFAULT_BAUD = 9600


class SerialPort(Protocol):
    """Small pyserial-compatible surface used by commands and unit tests."""

    @property
    def in_waiting(self) -> int: ...

    def write(self, data: bytes) -> int: ...

    def flush(self) -> None: ...

    def readline(self) -> bytes: ...

    def close(self) -> None: ...


def build_pump_command(pump_id: int, state: str) -> bytes:
    """Return one deterministic newline-delimited pump command."""

    if isinstance(pump_id, bool) or pump_id not in VALID_PUMP_IDS:
        raise ValueError("pump_id must be integer 1 or 2")
    if not isinstance(state, str) or state.lower() not in VALID_STATES:
        raise ValueError("state must be 'on' or 'off'")

    payload = {"cmd": "pump", "pump": pump_id, "state": state.lower()}
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


def build_all_off_commands() -> tuple[bytes, bytes]:
    """Return independent OFF commands in deterministic Pump 1/Pump 2 order."""

    return (
        build_pump_command(1, "off"),
        build_pump_command(2, "off"),
    )


def send_pump_command(port: SerialPort, pump_id: int, state: str) -> None:
    command = build_pump_command(pump_id, state)
    port.write(command)
    port.flush()


def send_all_off(port: SerialPort) -> None:
    """Send OFF to each independent channel; never emits an ON command."""

    for command in build_all_off_commands():
        port.write(command)
        port.flush()


def collect_status_lines(
    port: SerialPort,
    *,
    wait_seconds: float = 1.0,
) -> list[str]:
    """Collect currently arriving serial lines for a bounded interval."""

    lines: list[str] = []
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while time.monotonic() < deadline:
        if port.in_waiting:
            raw = port.readline()
            if raw:
                lines.append(raw.decode("utf-8", errors="replace").strip())
                continue
        time.sleep(0.05)
    return lines


def format_status_line(line: str) -> str:
    """Format valid JSON readably while preserving non-JSON diagnostics."""

    try:
        payload: Any = json.loads(line)
    except json.JSONDecodeError:
        return f"[NON-JSON] {line}"
    return json.dumps(payload, sort_keys=True)


def display_received_status(port: SerialPort, *, wait_seconds: float = 1.0) -> None:
    lines = collect_status_lines(port, wait_seconds=wait_seconds)
    if not lines:
        print("No serial status received during the wait interval.")
        return
    print("Received serial status:")
    for line in lines:
        print(f"  {format_status_line(line)}")


def _confirm_on(pump_id: int) -> bool:
    expected = f"ON {pump_id}"
    response = input(
        f"WARNING: Pump {pump_id} may energize. Type {expected} to confirm: "
    ).strip()
    if response != expected:
        print("ON command cancelled; no command was sent.")
        return False
    return True


def _send_menu_command(port: SerialPort, pump_id: int, state: str) -> None:
    if state == "on" and not _confirm_on(pump_id):
        return
    send_pump_command(port, pump_id, state)
    print(f"Sent Pump {pump_id} {state.upper()}.")
    display_received_status(port, wait_seconds=0.5)


def run_menu(port: SerialPort) -> None:
    while True:
        print()
        print("Challenge 4 Dual-Pump Hardware Test")
        print("1. Pump 1 ON")
        print("2. Pump 1 OFF")
        print("3. Pump 2 ON")
        print("4. Pump 2 OFF")
        print("5. ALL OFF")
        print("6. Show received serial status")
        print("7. Exit")

        choice = input("Choose an option: ").strip()
        if choice == "1":
            _send_menu_command(port, 1, "on")
        elif choice == "2":
            _send_menu_command(port, 1, "off")
        elif choice == "3":
            _send_menu_command(port, 2, "on")
        elif choice == "4":
            _send_menu_command(port, 2, "off")
        elif choice == "5":
            send_all_off(port)
            print("Sent independent OFF commands to Pump 1 and Pump 2.")
            display_received_status(port, wait_seconds=0.5)
        elif choice == "6":
            display_received_status(port, wait_seconds=2.0)
        elif choice == "7":
            return
        else:
            print("Please enter a menu number from 1 to 7.")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manual serial test utility for isolated dual-pump bring-up."
    )
    parser.add_argument(
        "--port",
        required=True,
        help="ESP32 serial port, for example COM5 or /dev/serial/by-id/<id>",
    )
    parser.add_argument(
        "--baud",
        type=_positive_int,
        default=DEFAULT_BAUD,
        help=f"serial baud rate (default: {DEFAULT_BAUD})",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        import serial
    except ImportError:
        print("pyserial is required; install repository requirements first.", file=sys.stderr)
        return 2

    print("WARNING: This utility can energize real pumps through connected relays.")
    print("It sends no ON command at startup. Supervise wiring and water flow.")

    try:
        port = serial.Serial(port=args.port, baudrate=args.baud, timeout=0.2)
    except (OSError, serial.SerialException) as exc:
        print(f"Could not open serial port {args.port!r}: {exc}", file=sys.stderr)
        return 2

    try:
        print(f"Opened {args.port} at {args.baud} baud.")
        run_menu(port)
    except (KeyboardInterrupt, EOFError):
        print("\nInput interrupted; attempting ALL OFF before exit.")
        return_code = 130
    except (OSError, serial.SerialException) as exc:
        print(f"Serial communication failed: {exc}", file=sys.stderr)
        return_code = 1
    else:
        return_code = 0
    finally:
        try:
            send_all_off(port)
            print("Exit safety: sent OFF to Pump 1 and Pump 2.")
        except (OSError, serial.SerialException) as exc:
            print(f"WARNING: exit ALL OFF could not be sent: {exc}", file=sys.stderr)
        finally:
            port.close()

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
