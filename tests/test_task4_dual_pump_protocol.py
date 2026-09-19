"""Hardware-free tests for the isolated Challenge 4 serial test protocol."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import unittest

from tools.task4_pump_test import (
    build_all_off_commands,
    build_pump_command,
    send_all_off,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class FakeSerial:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.flush_count = 0

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        self.flush_count += 1


class PumpCommandTests(unittest.TestCase):
    def test_pump_1_on_command_format(self) -> None:
        self.assertEqual(
            build_pump_command(1, "on"),
            b'{"cmd":"pump","pump":1,"state":"on"}\n',
        )

    def test_pump_2_on_command_format(self) -> None:
        self.assertEqual(
            build_pump_command(2, "on"),
            b'{"cmd":"pump","pump":2,"state":"on"}\n',
        )

    def test_pump_ids_remain_distinct(self) -> None:
        pump_1 = build_pump_command(1, "on")
        pump_2 = build_pump_command(2, "on")
        self.assertNotEqual(pump_1, pump_2)
        self.assertIn(b'"pump":1', pump_1)
        self.assertIn(b'"pump":2', pump_2)

    def test_independent_off_commands(self) -> None:
        self.assertEqual(
            build_pump_command(1, "off"),
            b'{"cmd":"pump","pump":1,"state":"off"}\n',
        )
        self.assertEqual(
            build_pump_command(2, "off"),
            b'{"cmd":"pump","pump":2,"state":"off"}\n',
        )

    def test_all_off_is_two_independent_off_commands(self) -> None:
        self.assertEqual(
            build_all_off_commands(),
            (
                b'{"cmd":"pump","pump":1,"state":"off"}\n',
                b'{"cmd":"pump","pump":2,"state":"off"}\n',
            ),
        )

    def test_send_all_off_writes_and_flushes_both_commands(self) -> None:
        port = FakeSerial()
        send_all_off(port)
        self.assertEqual(port.writes, list(build_all_off_commands()))
        self.assertEqual(port.flush_count, 2)

    def test_invalid_pump_ids_are_rejected(self) -> None:
        for invalid_id in (0, 3, -1, True, "1", None):
            with self.subTest(pump_id=invalid_id):
                with self.assertRaises(ValueError):
                    build_pump_command(invalid_id, "on")  # type: ignore[arg-type]

    def test_invalid_states_are_rejected(self) -> None:
        for invalid_state in ("start", "", 1, None):
            with self.subTest(state=invalid_state):
                with self.assertRaises(ValueError):
                    build_pump_command(1, invalid_state)  # type: ignore[arg-type]

    def test_serialization_is_deterministic(self) -> None:
        expected = build_pump_command(2, "off")
        for _ in range(20):
            self.assertEqual(build_pump_command(2, "OFF"), expected)

    def test_import_has_no_output_or_automatic_command(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "-c", "import tools.task4_pump_test"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
