"""Hardware-free checks for the ESP32/Pi integration."""
import json
import sys
import time
import types
import unittest
from unittest import mock


# Keep these tests runnable on a developer machine without Pi packages.
if "serial" not in sys.modules:
    serial = types.ModuleType("serial")

    class SerialException(Exception):
        pass

    serial.SerialException = SerialException
    serial.Serial = object
    sys.modules["serial"] = serial

fake_database = types.ModuleType("farm.database")
fake_database.insert_reading = mock.Mock()
fake_database.record_rejection = mock.Mock()
fake_database.log_decision = mock.Mock()
sys.modules["farm.database"] = fake_database

fake_validation = types.ModuleType("farm.validation")
fake_validation.Rejected = ValueError
fake_validation.validate_sensor_message = mock.Mock()
sys.modules["farm.validation"] = fake_validation

fake_sensors = types.ModuleType("farm.sensors")


class SensorError(RuntimeError):
    pass


class SensorCommunicationError(SensorError):
    pass


class SensorDataError(SensorError):
    pass


fake_sensors.SensorError = SensorError
fake_sensors.SensorCommunicationError = SensorCommunicationError
fake_sensors.SensorDataError = SensorDataError
fake_sensors.read_all = mock.Mock()
sys.modules["farm.sensors"] = fake_sensors

from farm import config, control, esp_link, node_serial  # noqa: E402


class FakePort:
    def __init__(self):
        self.writes = []
        self.is_open = True

    def write(self, payload):
        self.writes.append(payload)

    def close(self):
        self.is_open = False


class FakePump:
    def __init__(self):
        self.running = False
        self.pin = 25
        self.run_seconds = 0
        self.stopped_at = time.time() - 100

    def enforce_max_runtime(self):
        return None

    def can_start(self):
        return True, "ok"

    def start(self, force=False):
        self.running = True
        return True, "started"

    def stop(self, reason="commanded"):
        self.running = False
        return True, reason


class FakeHardware:
    def __init__(self):
        self._pump = FakePump()
        self.stop_reason = None

    def pump(self, pump_id=1):
        return self._pump

    def all_stop(self, reason):
        self.stop_reason = reason
        self._pump.running = False

    def state(self):
        return {1: {"running": self._pump.running, "pin": 25}}

    def attach_button(self, handler):
        return None

    def close(self):
        return None


class EspLinkTests(unittest.TestCase):
    def test_pump_on_and_off_send_expected_json(self):
        link = esp_link.EspLink()
        link._port = FakePort()
        link.connected = True

        self.assertTrue(link.pump(True))
        self.assertTrue(link.pump(False))

        messages = [json.loads(item.decode()) for item in link._port.writes]
        self.assertEqual(messages, [
            {"cmd": "pump", "state": "on"},
            {"cmd": "pump", "state": "off"},
        ])

    def test_disconnected_link_refuses_pump_start(self):
        link = esp_link.EspLink()
        pump = esp_link.EspPump(1, link)
        ok, reason = pump.start()
        self.assertFalse(ok)
        self.assertIn("link down", reason)

    def test_board_safety_timeout_changes_state_to_stopped(self):
        link = esp_link.EspLink()
        link.connected = True
        link.send = mock.Mock(return_value=True)
        pump = esp_link.EspPump(1, link)

        self.assertTrue(pump.start(force=True)[0])
        link._handle(b'{"node":"esp32","pump":"off","reason":"safety_timeout"}')

        self.assertFalse(pump.running)
        self.assertEqual(link.esp_last_reason, "safety_timeout")

    def test_get_hardware_is_a_singleton(self):
        sentinel = object()
        with mock.patch.object(config, "PUMP_BACKEND", "esp"), \
                mock.patch.object(esp_link, "_hardware", None), \
                mock.patch.object(esp_link, "EspHardware", return_value=sentinel) as factory:
            self.assertIs(esp_link.get_hardware(), sentinel)
            self.assertIs(esp_link.get_hardware(), sentinel)
            factory.assert_called_once_with()

    def test_legacy_reader_uses_same_link_implementation(self):
        self.assertIs(node_serial.EspLink, esp_link.EspLink)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.hardware = FakeHardware()
        fake_database.insert_reading.reset_mock()
        fake_database.log_decision.reset_mock()
        fake_sensors.read_all.reset_mock()
        fake_sensors.read_all.side_effect = None
        fake_sensors.read_all.return_value = {}

    def make_controller(self):
        with mock.patch.object(esp_link, "get_hardware", return_value=self.hardware):
            return control.Controller()

    def test_controller_poll_has_no_missing_link_attribute(self):
        fake_sensors.read_all.return_value = {
            "moisture": 38.0, "temperature": 24.0, "ec": 0.0,
        }
        controller = self.make_controller()
        self.assertEqual(controller.poll_once()["moisture"], 38.0)
        self.assertEqual(fake_database.insert_reading.call_count, 3)

    def test_probe_polling_is_independent_of_esp32_connection(self):
        fake_sensors.read_all.return_value = {
            "moisture": 41.0, "temperature": 25.0, "ec": 100.0,
        }
        controller = self.make_controller()
        self.assertEqual(controller.poll_once()["moisture"], 41.0)

    def test_stale_reading_stops_running_pump(self):
        controller = self.make_controller()
        controller.sensor_health.mark_success()
        controller.latest = {"moisture": 5.0}
        controller.latest_at = time.time() - config.READING_STALE_S - 1
        self.hardware._pump.running = True
        decision, _, source = controller.decide()
        self.assertEqual(decision, "pump_off")
        self.assertEqual(source, "safety")

    def test_sensor_timeout_stops_running_pump_in_same_tick(self):
        controller = self.make_controller()
        controller.sensor_health.mark_success()
        controller.latest = {"moisture": 5.0}
        self.hardware._pump.running = True
        fake_sensors.read_all.side_effect = SensorCommunicationError("timeout")

        controller.tick(store=False)

        self.assertFalse(self.hardware._pump.running)
        self.assertEqual(controller.status()["sensor_health"]["state"], "offline")
        self.assertEqual(controller.last_decision["source"], "safety")

    def test_cached_low_reading_cannot_restart_pump_after_timeout(self):
        controller = self.make_controller()
        controller.sensor_health.mark_success()
        controller.latest = {"moisture": 5.0}
        fake_sensors.read_all.side_effect = SensorCommunicationError("timeout")
        controller.tick(store=False)

        decision, reason, source = controller.decide()

        self.assertEqual(decision, "hold")
        self.assertEqual(source, "safety")
        self.assertIn("offline", reason)

    def test_manual_start_is_blocked_when_sensor_is_offline(self):
        controller = self.make_controller()
        controller.sensor_health.mark_failure("offline", "timeout")
        self.hardware._pump.start = mock.Mock(
            wraps=self.hardware._pump.start
        )

        ok, reason = controller.manual("on")

        self.assertFalse(ok)
        self.assertIn("refused", reason)
        self.hardware._pump.start.assert_not_called()

    def test_repeated_timeout_does_not_duplicate_safety_decision(self):
        controller = self.make_controller()
        controller.sensor_health.mark_success()
        fake_sensors.read_all.side_effect = SensorCommunicationError("timeout")

        controller.tick(store=False)
        first_log_count = fake_database.log_decision.call_count
        controller.tick(store=False)

        self.assertEqual(fake_database.log_decision.call_count, first_log_count)

    def test_valid_reading_recovers_without_controller_restart(self):
        controller = self.make_controller()
        controller.sensor_health.mark_failure("offline", "timeout")
        fake_sensors.read_all.return_value = {
            "moisture": 40.0, "temperature": 24.0, "ec": 100.0,
        }

        controller.tick(store=False)

        health = controller.status()["sensor_health"]
        self.assertEqual(health["state"], "online")
        self.assertTrue(health["can_irrigate"])
        self.assertIsNone(controller.last_error)

    def test_unexpected_decision_error_stops_all_pumps(self):
        controller = self.make_controller()
        controller.poll_once = mock.Mock(return_value={})
        controller.decide = mock.Mock(side_effect=RuntimeError("boom"))
        controller.tick()
        self.assertEqual(self.hardware.stop_reason, "controller error")

    def test_maximum_runtime_matches_firmware(self):
        self.assertEqual(config.PUMP_MAX_RUN_S, 10)


if __name__ == "__main__":
    unittest.main()
