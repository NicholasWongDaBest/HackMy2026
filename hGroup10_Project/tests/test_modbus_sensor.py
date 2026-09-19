"""Task 5 Modbus failure tests without a serial adapter or PyModbus."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


fake_pymodbus = types.ModuleType("pymodbus")
fake_pymodbus_client = types.ModuleType("pymodbus.client")
fake_pymodbus_client.ModbusSerialClient = mock.Mock()

module_path = Path(__file__).parents[1] / "farm" / "sensors.py"
spec = importlib.util.spec_from_file_location("farm._task5_sensors", module_path)
sensors = importlib.util.module_from_spec(spec)
with mock.patch.dict(sys.modules, {
    "pymodbus": fake_pymodbus,
    "pymodbus.client": fake_pymodbus_client,
}):
    spec.loader.exec_module(sensors)


class FakeResult:
    def __init__(self, value=None, error=False):
        self.registers = [] if value is None else [value]
        self._error = error

    def isError(self):
        return self._error


class FakeClient:
    def __init__(self, reader):
        self.connected = True
        self._reader = reader
        self.closed = False

    def connect(self):
        self.connected = True
        return True

    def close(self):
        self.closed = True
        self.connected = False

    def read_holding_registers(self, address, count, slave):
        return self._reader(address)

    read_input_registers = read_holding_registers


class DeviceIdClient(FakeClient):
    def __init__(self, reader):
        super().__init__(reader)
        self.device_ids = []

    def read_holding_registers(self, address, count, device_id):
        self.device_ids.append(device_id)
        return self._reader(address)

    read_input_registers = read_holding_registers


class SoilSensorFailureTests(unittest.TestCase):
    def setUp(self):
        sensors.ModbusSerialClient.reset_mock()
        sensors.ModbusSerialClient.side_effect = None

    def test_modbus_error_resets_client_for_next_reconnect(self):
        failed = FakeClient(lambda _address: FakeResult(error=True))
        replacement = FakeClient(lambda _address: FakeResult(1))
        sensors.ModbusSerialClient.side_effect = [failed, replacement]
        probe = sensors.SoilSensor()

        with self.assertRaises(sensors.SensorCommunicationError):
            probe.read_all()

        self.assertTrue(failed.closed)
        self.assertIs(probe.client, replacement)

    def test_impossible_value_is_data_error_not_disconnection(self):
        client = FakeClient(lambda _address: FakeResult(65535))
        sensors.ModbusSerialClient.return_value = client
        probe = sensors.SoilSensor()

        with self.assertRaises(sensors.SensorDataError):
            probe.read_all()

        self.assertIs(probe.client, client)
        self.assertFalse(client.closed)

    def test_complete_valid_read_returns_all_channels(self):
        raw_by_address = {0x0000: 380, 0x0001: 250, 0x0002: 100}
        client = DeviceIdClient(
            lambda address: FakeResult(raw_by_address[address])
        )
        sensors.ModbusSerialClient.return_value = client
        probe = sensors.SoilSensor()

        self.assertEqual(probe.read_all(), {
            "moisture": 38.0,
            "temperature": 25.0,
            "ec": 100.0,
        })
        self.assertEqual(client.device_ids, [1, 1, 1])

    def test_legacy_slave_keyword_remains_supported(self):
        raw_by_address = {0x0000: 380, 0x0001: 250, 0x0002: 100}
        client = FakeClient(lambda address: FakeResult(raw_by_address[address]))
        sensors.ModbusSerialClient.return_value = client

        self.assertEqual(sensors.SoilSensor().read_all()["moisture"], 38.0)


if __name__ == "__main__":
    unittest.main()
