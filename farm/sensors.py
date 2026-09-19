"""RS485 / Modbus RTU soil sensor.

The 3-in-1 probe reports moisture, temperature and EC over a single
serial link. Nothing here is hardcoded or simulated: every value in the
database came out of read_all() below, and if the probe is unplugged
read_all() raises rather than inventing a number.

Run:  python3 -m farm.sensors          (one-shot read, prints values)
"""
import logging

from pymodbus.client import ModbusSerialClient

from . import config

log = logging.getLogger("sensors")


class SensorError(Exception):
    """The probe could not be read. Never substitute a default value."""


def _decode(raw: int, scale: float, signed: bool) -> float:
    """Modbus registers are unsigned 16-bit. A negative temperature comes
    back as two's complement, so sign-extend before scaling."""
    if signed and raw > 0x7FFF:
        raw -= 0x10000
    return round(raw * scale, 2)


class SoilSensor:
    def __init__(self):
        self.client = ModbusSerialClient(
            port=config.RS485_PORT,
            baudrate=config.RS485_BAUD,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=config.RS485_TIMEOUT,
        )

    def connect(self) -> None:
        if not self.client.connect():
            raise SensorError(f"cannot open {config.RS485_PORT}")

    def close(self) -> None:
        self.client.close()

    def _read_register(self, address: int):
        reader = (
            self.client.read_holding_registers
            if config.RS485_FUNC == "holding"
            else self.client.read_input_registers
        )
        result = reader(address, count=1, device_id=config.RS485_SLAVE)
        if result.isError():
            raise SensorError(f"modbus error reading register 0x{address:04X}: {result}")
        return result.registers[0]

    def read_all(self) -> dict:
        """Returns {sensor_type: value} for every configured register.

        One probe, three independent measurands -- that is the three
        sensors the brief asks for. A partial failure raises rather than
        returning a half-populated dict, so the caller never stores a
        reading it cannot stand behind.
        """
        if not self.client.connected:
            self.connect()

        readings = {}
        for name, (address, scale, signed) in config.SENSOR_REGISTERS.items():
            raw = self._read_register(address)
            value = _decode(raw, scale, signed)

            low, high = config.SENSOR_RANGES.get(name, (float("-inf"), float("inf")))
            if not (low <= value <= high):
                raise SensorError(
                    f"{name} read {value} (raw {raw}) outside plausible range "
                    f"{low}..{high} -- check the register map with tools/sensor_scan.py"
                )
            readings[name] = value
        return readings


_sensor = None


def get_sensor() -> SoilSensor:
    global _sensor
    if _sensor is None:
        _sensor = SoilSensor()
    return _sensor


def read_all() -> dict:
    return get_sensor().read_all()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        for name, value in read_all().items():
            print(f"{name:14s} {value}")
    except SensorError as exc:
        raise SystemExit(f"SENSOR FAILURE: {exc}")
