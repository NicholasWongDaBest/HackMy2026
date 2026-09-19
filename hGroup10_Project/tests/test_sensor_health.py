"""Hardware-free checks for Task 5 sensor health state."""
import unittest

from farm.sensor_health import SensorHealth


class SensorHealthTests(unittest.TestCase):
    def make_health(self):
        return SensorHealth(
            "modbus:zone-1:slave-1",
            "zone-1",
            ("moisture", "temperature", "ec"),
            clock=lambda: 100.0,
        )

    def test_starting_source_blocks_its_zone(self):
        health = self.make_health()
        allowed, reason = health.can_irrigate("zone-1")
        self.assertFalse(allowed)
        self.assertIn("not produced", reason)

    def test_failure_transition_is_emitted_once(self):
        health = self.make_health()
        health.mark_success(at=90.0)
        self.assertEqual(health.mark_failure("offline", "timeout", at=95.0), "offline")
        self.assertIsNone(health.mark_failure("offline", "timeout", at=96.0))
        snapshot = health.snapshot(now=100.0)
        self.assertEqual(snapshot["failure_seconds"], 5.0)
        self.assertEqual(snapshot["seconds_since_success"], 10.0)

    def test_complete_read_recovers_source(self):
        health = self.make_health()
        health.mark_failure("offline", "timeout", at=95.0)
        self.assertEqual(health.mark_success(at=99.0), "recovered")
        self.assertTrue(health.snapshot(now=100.0)["can_irrigate"])

    def test_source_does_not_block_an_unrelated_zone(self):
        health = self.make_health()
        health.mark_failure("offline", "timeout")
        allowed, _ = health.can_irrigate("zone-2")
        self.assertTrue(allowed)

    def test_invalid_data_is_not_reported_as_disconnection(self):
        health = self.make_health()
        health.mark_failure("invalid", "out of range")
        self.assertEqual(health.snapshot()["state"], "invalid")


if __name__ == "__main__":
    unittest.main()
