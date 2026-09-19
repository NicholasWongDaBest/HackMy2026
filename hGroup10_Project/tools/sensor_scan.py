#!/usr/bin/env python3
"""Discover the soil probe's Modbus layout.

Vendors ship these 3-in-1 probes with different register maps and
sometimes different slave addresses. Run this before trusting
config.SENSOR_REGISTERS -- it sweeps slave addresses and dumps the first
16 registers on both function codes so you can see which numbers look
like moisture (0-100), temperature (~20-35) and EC (hundreds-thousands).

Usage:  python3 tools/sensor_scan.py [/dev/ttyUSB0] [baud]
"""
import sys

from pymodbus.client import ModbusSerialClient

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 9600


def signed(v):
    return v - 0x10000 if v > 0x7FFF else v


def main():
    client = ModbusSerialClient(
        port=PORT, baudrate=BAUD, bytesize=8, parity="N", stopbits=1, timeout=0.5
    )
    if not client.connect():
        raise SystemExit(f"cannot open {PORT} -- is the USB-RS485 adapter plugged in? "
                         f"check 'ls /dev/ttyUSB*' and that you are in the dialout group")

    print(f"port={PORT} baud={BAUD}\n")
    found = False

    for slave in range(1, 11):
        for func_name, reader in (
            ("holding(0x03)", client.read_holding_registers),
            ("input(0x04)", client.read_input_registers),
        ):
            try:
                result = reader(0, count=16, slave=slave)
            except Exception:
                continue
            if result.isError():
                continue

            found = True
            print(f"=== slave {slave} via {func_name} ===")
            for i, raw in enumerate(result.registers):
                print(f"  reg 0x{i:04X} raw={raw:6d}  /10={raw/10:8.1f}  "
                      f"signed/10={signed(raw)/10:8.1f}")
            print()

    if not found:
        print("No response from any slave address 1-10 on either function code.")
        print("Check:  A/B wiring not swapped, probe powered, baud rate "
              "(try 4800 and 19200), adapter LEDs blinking on request.")
    client.close()


if __name__ == "__main__":
    main()
