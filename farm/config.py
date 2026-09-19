"""All credentials and tunables in one place.

Override any of these with environment variables so nothing secret is
hardcoded in the logic files. Example:
    export TEAM_NAME=hGroup10
"""
import os

# ---- Team identity -----------------------------------------------------
# CONFIRM THIS WITH A JUDGE. If the topic string is wrong, the verify
# signal is published into the void and objective 3 silently fails.
TEAM_NAME = os.getenv("TEAM_NAME", "hGroup10")

# ---- Central station ---------------------------------------------------
CENTRAL_HOST = os.getenv("CENTRAL_HOST", "192.168.98.50")

CENTRAL_DB = {
    "host": CENTRAL_HOST,
    "user": os.getenv("CENTRAL_DB_USER", "hGroup10"),
    "password": os.getenv("CENTRAL_DB_PASS", "teamGroup10"),
    "database": os.getenv("CENTRAL_DB_NAME", "hackathonGroup10"),
    "connection_timeout": 5,
}

MQTT_HOST = CENTRAL_HOST
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

TOPIC_TEST      = f"hackathon/{TEAM_NAME}/test"       # sub + pub
TOPIC_VERIFY    = f"hackathon/{TEAM_NAME}/verify"     # sub + pub
TOPIC_BROADCAST = "hackathon/broadcast"               # sub only (HOSTILE)

# ---- Local buffer database (on the Pi) ---------------------------------
LOCAL_DB = {
    "host": os.getenv("LOCAL_DB_HOST", "127.0.0.1"),
    "user": os.getenv("LOCAL_DB_USER", "farm"),
    "password": os.getenv("LOCAL_DB_PASS", "farm"),
    "database": os.getenv("LOCAL_DB_NAME", "farm_local"),
    "connection_timeout": 5,
}

# ---- Validation limits -------------------------------------------------
MAX_PAYLOAD_BYTES = 4096      # drop anything larger before parsing
MAX_MESSAGE_CHARS = 500       # selfcare message display cap
CLOCK_SKEW_FUTURE_S = 60      # reject timestamps this far in the future
CLOCK_SKEW_PAST_S   = 3600    # reject timestamps older than this

# Physical plausibility per sensor. A reading outside these is corrupt
# data, not a measurement. Tighten to your real sensor datasheet.
SENSOR_RANGES = {
    "moisture":    (0.0, 100.0),    # %
    "temperature": (-40.0, 85.0),   # degC
    "ec":          (0.0, 20000.0),  # uS/cm
    "humidity":    (0.0, 100.0),    # %
    "ph":          (0.0, 14.0),
}

SYNC_INTERVAL_S = 10          # how often the sync worker drains the buffer
SYNC_BATCH = 200              # rows pushed per cycle


# ---- RS485 soil sensor (Modbus RTU) ------------------------------------
# The 3-in-1 probe exposes moisture, temperature and EC. Register layout
# differs between vendors -- run tools/sensor_scan.py FIRST and correct
# SENSOR_REGISTERS below to match what actually comes back.
RS485_PORT   = os.getenv("RS485_PORT", "/dev/ttyUSB0")
RS485_BAUD   = int(os.getenv("RS485_BAUD", "9600"))
RS485_SLAVE  = int(os.getenv("RS485_SLAVE", "1"))
RS485_FUNC   = os.getenv("RS485_FUNC", "holding")      # holding | input
RS485_TIMEOUT = float(os.getenv("RS485_TIMEOUT", "1.0"))

# Where this probe physically sits. Goes into sensor_data.sensor_position.
SENSOR_POSITION = os.getenv("SENSOR_POSITION", "zone-1")

# name -> (register address, scale, signed)
# raw * scale = engineering units. Most of these probes report
# moisture and temperature at 0.1 resolution and EC as a raw integer.
SENSOR_REGISTERS = {
    "moisture":    (0x0000, 0.1, False),   # %
    "temperature": (0x0001, 0.1, True),    # degC, can be negative
    "ec":          (0x0002, 1.0, False),   # uS/cm
}

# ---- Pump output -------------------------------------------------------
# The relay is wired to the ESP32, not directly to Raspberry Pi GPIO.
# This value is displayed on the dashboard; the ESP32 firmware owns it.
PUMP_PINS = {1: int(os.getenv("ESP32_PUMP_PIN", "25"))}

# ---- Polling and automation -------------------------------------------
POLL_INTERVAL_S = int(os.getenv("POLL_INTERVAL_S", "60"))   # brief: every 1 minute

# Hysteresis band. Turning on and off at the same threshold makes the pump
# chatter around the setpoint; the gap between these two numbers is what
# stops that.
MOISTURE_ON_BELOW  = float(os.getenv("MOISTURE_ON_BELOW", "30.0"))
MOISTURE_OFF_ABOVE = float(os.getenv("MOISTURE_OFF_ABOVE", "45.0"))

# Safety envelope. These bound the automation regardless of what the
# sensor claims -- a stuck-low probe must not run the pump forever.
PUMP_MAX_RUN_S  = int(os.getenv("PUMP_MAX_RUN_S", "10"))
PUMP_MIN_REST_S = int(os.getenv("PUMP_MIN_REST_S", "60"))

# Refuse to irrigate on a reading older than this (sensor died mid-run).
READING_STALE_S = int(os.getenv("READING_STALE_S", "180"))


# ---- ESP32 sensor node (USB serial) ------------------------------------
# The kit's analog sensors cannot connect to the Pi: a Raspberry Pi has no
# ADC. The ESP32 reads them and streams newline-delimited JSON over USB.
# Prefer a stable /dev/serial/by-id/... path when one is available.
NODE_SERIAL_PORT = os.getenv("NODE_SERIAL_PORT", "/dev/ttyUSB0")
NODE_SERIAL_BAUD = int(os.getenv("NODE_SERIAL_BAUD", "9600"))
NODE_POSITION = os.getenv("NODE_POSITION", "zone-1")

# Physical plausibility for the node's channels. Anything outside these
# is corrupt data, not a measurement -- same rule as the RS485 probe.
SENSOR_RANGES.update({
    "air_temperature": (-40.0, 80.0),   # accepted legacy name
    "light":           (0.0, 100.0),    # % of full scale
    "water_level":     (0.0, 100.0),    # % of full scale
    "rainfall":        (0.0, 100.0),    # % of full scale
})
