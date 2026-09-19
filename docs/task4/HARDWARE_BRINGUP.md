# Challenge 4 isolated dual-pump hardware bring-up

This package is for supervised, isolated relay and pump testing. It does not
replace `firmware/esp32_node/esp32_node.ino`, and it is not connected to the
Task 1 controller, allocation engine, dashboard, database, or MQTT path.
The pin, relay-channel, polarity, and water-path configuration documented
below is the physically verified Challenge 4 configuration.

## Physical topology

```text
Container 1 -> Pump 1 -> Container 2 / Zone 1
Container 3 -> Pump 2 -> Container 4 / Zone 2
```

The paths are independent. Pump 1 must never serve Zone 2, and Pump 2 must
never serve Zone 1. The firmware provides separate relay state and runtime
tracking; it does not perform allocation decisions.

## Repository-derived ESP32 pin inventory

The canonical production sketch, `firmware/esp32_node/esp32_node.ino`, defines:

| GPIO | Current canonical function | Notes |
|---:|---|---|
| 17 | DHT11 data | Digital sensor input. |
| 34 | Light sensor | ADC input; GPIO34 is input-only. |
| 33 | Water-level sensor | ADC input. |
| 35 | Rain/steam sensor | ADC input; GPIO35 is input-only. |
| 25 | Pump 1 relay | Current production relay output. |

The official Keyestudio KS0567 physical assembly also occupies pins that are
not represented in the current canonical firmware:

| GPIO | KS0567 physical function |
|---:|---|
| 17 | DHT11 |
| 25 | Existing Pump 1 relay |
| 26 | Servo — **reserved; do not use for Pump 2** |
| 27 | LED |
| 32 | Soil-moisture sensor |
| 33 | Water-level sensor |
| 34 | Photoresistor |
| 35 | Rain/steam sensor |

The canonical sketch contains no servo, LED, or button GPIO definition, but
that absence does not make those physically connected KS0567 pins available.
The button in `farm/config.py` is Raspberry Pi **BCM GPIO 26**, which is a
different device and pin namespace from the ESP32 servo on GPIO26.

### Relay pin decision

- **Pump 1:** ESP32 GPIO25, using the existing single relay, **active HIGH**.
- **Pump 2:** ESP32 GPIO14, using **K1 / IN1** of the two-channel relay,
  **active LOW**.
- **K2 / IN2:** unused.

This is the physically verified configuration. **Do not use GPIO4 for Pump
2.** GPIO26 also remains reserved for the Keyestudio servo and must not be used
for either pump.

The isolated sketch keeps each relay polarity in a separate constant because
the two verified relay paths use opposite logic levels. Do not collapse them
into a shared active-high or active-low setting.

## Electrical architecture and rules

```text
ESP32 GPIO25 -> existing single relay (active HIGH) -> Pump 1 -> C2 / Zone 1
ESP32 GPIO14 -> two-channel relay K1/IN1 (active LOW) -> Pump 2 -> C4 / Zone 2
Two-channel relay K2/IN2 -> unused
```

The complete independent source paths are:

```text
C1 -> Pump 1 -> C2 / Zone 1
C3 -> Pump 2 -> C4 / Zone 2
```

Never power a pump directly from an ESP32 GPIO. An ESP32 GPIO drives only a
compatible relay/module input. Pump current must come from an appropriately
rated external supply through relay contacts rated for the pump's voltage,
running current, and startup/stall current.

Before wiring, identify the relay module's actual VCC, GND, input, COM, NO, and
NC terminals from its documentation. Do not infer the pinout from this guide.
Determine whether its input is 3.3 V compatible and active-high or active-low.
Where the relay input is not galvanically isolated, the ESP32 and relay-control
supply normally need a common ground. Some opto-isolated boards require a
different grounding/power arrangement, so follow that module's documentation.
Use normally-open contacts when the safety design requires pumps to remain off
with an unpowered relay, and verify this physically with pumps disconnected.

## Isolated firmware behavior

`firmware/task4_dual_pump_test/task4_dual_pump_test.ino` uses 9600 baud and the
ArduinoJson library. Both outputs are driven to their configured OFF levels at
boot. It emits a ready message and an OFF status for each pump.

Commands are one JSON object per line:

```json
{"cmd":"pump","pump":1,"state":"on"}
{"cmd":"pump","pump":1,"state":"off"}
{"cmd":"pump","pump":2,"state":"on"}
{"cmd":"pump","pump":2,"state":"off"}
```

Typical status responses are:

```json
{"type":"pump_status","pump":1,"state":"on","reason":"command"}
{"type":"pump_status","pump":2,"state":"off","reason":"safety_timeout"}
```

Malformed JSON, an unsupported command, an invalid pump ID, an invalid state,
or an overlong line emits a JSON error and leaves both existing pump states
unchanged. OFF commands affect only the named pump. The PC/Pi utility implements
ALL OFF by sending independent OFF commands for Pump 1 and Pump 2.

Each pump has its own state, start timestamp, and 10,000 ms maximum runtime,
for isolated bring-up safety. A repeated ON while already running emits
`already_on` but does not reset its original start time. A timeout stops and
reports only the affected pump. This absolute-runtime behavior differs from
the canonical production keepalive/watchdog behavior, in which a repeated
`PUMP_ON` extends the deadline. The isolated firmware is a hardware bring-up
artifact and must not blindly replace canonical production firmware; final
integration must preserve Task 1–3 sensor/serial behavior and deliberately
reconcile the controller and firmware timing contract.

## Build and flash commands

These commands must be run later with the ESP32 connected. First identify the
actual board and port; do not guess the FQBN or serial device:

```bash
arduino-cli board list
arduino-cli core update-index
arduino-cli core install esp32:esp32
arduino-cli lib install ArduinoJson
```

For an ESP32 Dev Module, the usual FQBN is `esp32:esp32:esp32`. Confirm that
`arduino-cli board list` reports the same board before using these commands:

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/task4_dual_pump_test
arduino-cli upload --port COM5 --fqbn esp32:esp32:esp32 firmware/task4_dual_pump_test
python tools/task4_pump_test.py --port COM5 --baud 9600
```

On Raspberry Pi/Linux, replace the port but keep the confirmed FQBN:

```bash
arduino-cli upload \
  --port /dev/serial/by-id/<esp32-id> \
  --fqbn esp32:esp32:esp32 \
  firmware/task4_dual_pump_test

python3 tools/task4_pump_test.py \
  --port /dev/serial/by-id/<esp32-id> \
  --baud 9600
```

The test utility warns before use, requires the operator to type `ON 1` or
`ON 2` before the corresponding ON command, provides ALL OFF, and attempts to
send OFF to both pumps on normal exit, EOF, Ctrl+C, or a handled serial error.
Opening the utility does not turn on either pump.

## Supervised physical test sequence

Use only the verified GPIO25 active-high Pump 1 path and GPIO14 active-low
K1/IN1 Pump 2 path. Before testing, reconfirm contact selection, power ratings,
grounds/isolation, and plumbing against the actual assembled hardware.

### Test A — relay-only boot safety

1. Disconnect both pumps from relay contacts.
2. Power the ESP32 and relay modules.
3. Verify both relay outputs boot OFF with a meter/indicator.
4. Verify the serial output reports both pumps OFF with reason `boot`.

### Test B — Pump 1 only

1. Keep Pump 2 disconnected.
2. Connect Pump 1 with a safe water path; never dry-run unless rated for it.
3. Use menu options 1 and 2 and confirm only Pump 1 starts/stops.

### Test C — Pump 2 only

1. Disconnect Pump 1.
2. Connect Pump 2 with a safe water path.
3. Use menu options 3 and 4 and confirm only Pump 2 starts/stops.

### Test D — independent paths and interlock

1. Connect both pumps only after Tests A–C pass.
2. Test each ON/OFF command separately.
3. Verify each pump moves water only through its own physical path.
4. While one pump is running, request the other and verify the
   one-pump-at-a-time interlock stops the first before starting the second.
5. Use ALL OFF and verify both stop.

### Test E — automatic runtime cutoff

1. Start one pump under supervision.
2. Do not send OFF.
3. Confirm it stops after approximately 10 seconds and reports
   `safety_timeout`.
4. Repeat an ON while it runs and confirm cutoff remains measured from the
   original ON rather than being extended.
5. Repeat independently for the other pump.

### Test F — OFF behavior

1. Run Pump 1, stop it, and verify Pump 1 is OFF.
2. Run Pump 2, stop it, and verify Pump 2 is OFF.
3. Never bypass the interlock or attempt to keep both pumps running
   concurrently.
4. Finish with ALL OFF and remove pump power.

## Verified configuration and remaining checks

- Pump 1 is physically verified on ESP32 GPIO25 using the existing single
  relay with active-HIGH control.
- Pump 2 is physically verified on ESP32 GPIO14 using K1/IN1 of the
  two-channel relay with active-LOW control.
- K2/IN2 is unused.
- The verified plumbing is C1 -> Pump 1 -> C2 / Zone 1 and
  C3 -> Pump 2 -> C4 / Zone 2.
- GPIO4 must not be used for Pump 2. GPIO26 remains reserved for the physically
  connected servo.

The following operational and electrical details must still be confirmed for
each future build or integration:

- The exact ESP32 board/FQBN and upload port.
- Each relay module's pinout, 3.3 V compatibility, and boot state.
- COM/NO/NC contact choice and fail-off behavior.
- Relay and pump supply voltage/current ratings, protection, and common-ground
  or opto-isolation arrangement.
- Boot-OFF, actual 10-second isolated cutoff timing, and the one-pump-at-a-time
  interlock after any firmware or wiring change.

The verified pin, polarity, relay-channel, and plumbing facts above supersede
the former GPIO4 proposal. The remaining checks are not evidence that the old
GPIO4 proposal is valid. Production Task 1 firmware and Python code remain
separate and unchanged.
