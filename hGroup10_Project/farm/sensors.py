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
    """The probe could not provide a trusted complete reading."""


class SensorCommunicationError(SensorError):
    """The Modbus device or serial transport did not respond correctly."""


class SensorDataError(SensorError):
    """The device responded, but the value is physically implausible."""


def _decode(raw: int, scale: float, signed: bool) -> float:
    """Modbus registers are unsigned 16-bit. A negative temperature comes
    back as two's complement, so sign-extend before scaling."""
    if signed and raw > 0x7FFF:
        raw -= 0x10000
    return round(raw * scale, 2)


class SoilSensor:
    def __init__(self):
        self.client = self._new_client()

    @staticmethod
    def _new_client():
        return ModbusSerialClient(
            port=config.RS485_PORT,
            baudrate=config.RS485_BAUD,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=config.RS485_TIMEOUT,
        )

    def _reset_client(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
        self.client = self._new_client()

    def connect(self) -> None:
        try:
            connected = self.client.connect()
        except Exception as exc:
            self._reset_client()
            raise SensorCommunicationError(
                f"cannot open {config.RS485_PORT}: {exc}"
            ) from exc
        if not connected:
            self._reset_client()
            raise SensorCommunicationError(f"cannot open {config.RS485_PORT}")

    def close(self) -> None:
        self.client.close()

    def _read_register(self, address: int):
        reader = (
            self.client.read_holding_registers
            if config.RS485_FUNC == "holding"
            else self.client.read_input_registers
        )
        try:
            # PyModbus 3.10 renamed ``slave`` to ``device_id``. Prefer the
            # current API used on the Pi, but retain compatibility with the
            # older release used by some development machines.
            try:
                result = reader(
                    address, count=1, device_id=config.RS485_SLAVE
                )
            except TypeError as exc:
                if "device_id" not in str(exc):
                    raise
                result = reader(
                    address, count=1, slave=config.RS485_SLAVE
                )
        except Exception as exc:
            self._reset_client()
            raise SensorCommunicationError(
                f"communication failure reading register 0x{address:04X}: {exc}"
            ) from exc

        if result is None or result.isError():
            self._reset_client()
            raise SensorCommunicationError(
                f"modbus timeout/error reading register 0x{address:04X}: {result}"
            )
        try:
            return result.registers[0]
        except (AttributeError, IndexError) as exc:
            self._reset_client()
            raise SensorCommunicationError(
                f"malformed Modbus response for register 0x{address:04X}"
            ) from exc

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
                raise SensorDataError(
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
