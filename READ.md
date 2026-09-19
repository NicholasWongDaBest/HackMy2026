# Save the Farm — live project tracker

Last updated: 2026-09-19 15:18 +08 (Asia/Kuala_Lumpur)

This is the canonical status record. `STATUS.md` is retained as a historical snapshot from earlier on 2026-09-19; where it conflicts with this file, use this file.

## Objective and current scope

Build and defend an edge-based farm irrigation system within the 30-hour challenge. The system must read real sensors, control real pumps, make explainable automation decisions, keep operating through bad input, network loss, low water, and sensor removal, and survive all conditions together in the final test.

Required phase sequence:

**Welcome → Task1 → Task2 → Task3 → Task4 → Task5 → FunBox → Perfect Storm**

The user reports **26 hours remain**, the hardware is assembled, and the Raspberry Pi/network setup is complete. The application has not yet been verified on the Pi. No command output or photographs from that setup were available during this audit, so those claims are recorded as user-reported rather than independently verified.

## Confirmed architecture

- Target computer: Raspberry Pi 4 Model B, 2 GB, running the preloaded Raspberry Pi OS image specified by `Phase/welcome.pdf`.
- The Pi is intended to own the Flask dashboard, MariaDB local buffer, irrigation control loop, GPIO relay outputs, physical button input, MQTT client, and central-database sync worker.
- A Keyestudio ESP32 Plus board is intended to read the kit's DHT11 and analog channels, then send newline-delimited JSON to the Pi over USB serial. Current firmware reads DHT11 air temperature/humidity plus light, water level, and steam/rain channels.
- A separate 3-in-1 moisture/temperature/EC probe is intended to connect directly to the Pi through USB-RS485 and Modbus RTU.
- Pump relay channels and the panel button are assigned to Pi GPIO using GPIO Zero's BCM numbering: pump 1 BCM17, pump 2 BCM27, button BCM26. These assignments are software configuration only; the physical wiring has not been verified in this audit.
- Farm Central is configured at `192.168.98.50` for MySQL and MQTT. The Pi stores readings locally first and a separate worker attempts to copy unsynced rows to Central.

Current execution paths:

```text
RS485 probe -> farm.sensors -> farm.control -> local MariaDB -> dashboard
                                      |-> Pi GPIO relay/pump 1

ESP32 kit sensors -> USB serial -> farm.node_serial -> local MariaDB -> dashboard

MQTT broadcast/test/verify -> farm.mqtt_client -> validator -> local MariaDB

local MariaDB -> farm.sync -> Farm Central MySQL
```

The ESP32 path does **not** feed the controller's in-memory state. Water-level and air-temperature readings can appear in the database/dashboard, but cannot currently stop or influence irrigation. Pump 2 exists as a generic GPIO object but has no zone-allocation control path. These are central blockers for Task4 and Perfect Storm.

## Status scoring method

Each phase has an explicit, equally weighted checklist. Every criterion is worth two points:

- `0` — absent, unknown, or contradicted by evidence.
- `1` — implemented or reported ready, but incomplete or not verified at the required integration/hardware level.
- `2` — verified at the level the brief requires. Real sensor, pump, network, or failure behavior requires evidence from the actual hardware/event services; a mock or source review cannot earn full credit for it.

`Completion % = earned points / maximum points × 100`, rounded to the nearest whole percent. This measures requirement completion, not code volume. Refactoring earns no points by itself.

## Phase status

| Phase | Completion % | Status | Completed work | Work in progress | Remaining work / blockers | Evidence and verification |
|---|---:|---|---|---|---|---|
| Welcome | 44% (7/16) | In progress | Hardware/Pi/network setup reported complete; dashboard, schema, sensor, relay, automation code and flowchart exist | Bring-up has not started from recorded evidence | Fix PyModbus compatibility and fail-safe defects; create DB; prove 3 real readings/minute, dashboard, pump and automation; capture screenshot; SVN submission | `farm/app.py`, `farm/control.py`, `farm/sensors.py`, `farm/actuator.py`, `farm/db/schema_local.sql`; `docs/flowchart.png` visually inspected; no Pi/hardware run recorded |
| Task1 | 31% (5/16) | In progress | Central DB/MQTT/sync code, validation, ERD source and selfcare dashboard card exist | Central schema and exact message shape still need discovery | Prove Central connection and sync; prevent duplicate sync; fix MQTT self-ack loop; render ERD PNG; capture selfcare screenshot; SVN submission | Offline validator 18/18 passed; mocked dashboard rendered and escaped markup; no Central connection, live MQTT, DB sync, or screenshot verified |
| Task2 | 25% (3/12) | In progress | Range validation can reject implausible typed MQTT/serial readings; dashboard has rejection log | Challenge-specific trigger and comparative display absent | Subscribe/publish required Challenge2 topic/message; validate every ingestion path, including Central DB; ensure bad data never reaches automation; screenshot comparison; SVN submission | Range cases passed offline; audit reproduced a mixed-payload bypass and direct DB values such as temperature 999 rendering without validation |
| Task3 | 38% (6/16) | In progress | Local-first storage, local dashboard, retrying sync loop and edge automation are represented in code | Recovery behavior is unverified | Fix idempotency/data-shape issues; run actual offline period; prove local operation and automatic recovery with no gaps/duplicates; required trigger and SVN submission | Source traced; audit simulation reproduced a duplicate Central insert after Central commit/local commit failure; no outage test run |
| Task4 | 8% (1/12) | In progress | Two relay/pump objects are configured | No phase-specific allocation implementation | Integrate water level into control; define zones/crop-health priority; map both pumps and containers; refuse unsafe pumping; explain and demonstrate allocation; SVN submission | `PUMP_PINS` contains two channels, but `Controller` only calls `pump(1)` and never reads `water_level` |
| Task5 | 29% (4/14) | In progress | RS485 exceptions are caught; dashboard can show `sensor_error`; process loop is intended to continue | Missing-sensor behavior is unsafe and unverified | On read failure, immediately fail safe and invalidate prior reading; prove other services/sensors continue; keep dashboard live; capture photo; SVN submission | Software probe reproduced pump start from a previous fresh dry reading after the current sensor read failed; no physical removal test |
| FunBox | 30% (3/10) | Implemented but unverified | BCM26 button callback is wired to a manual pump toggle in code | Physical panel-button wiring and behavior unverified | Verify useful action on real button, make safety precedence explicit, document chosen feature, demonstrate it, SVN submission | `Hardware.attach_button()` and `Controller.manual()` inspected; no button press recorded |
| Perfect Storm | 0% (0/8) | Not started | None specific to the combined scenario | Depends on all earlier phases | Internet down + sensor removed + low water + extreme temperature must coexist without restart or live patching; final SVN submission | No combined test or supporting implementation evidence |

## Acceptance checklists

Legend: `[x]` verified (2 points), `[~]` implemented/reported but not fully verified (1 point), `[ ]` absent/unknown/failed (0 points).

### Welcome — 7/16

- [~] At least three real sensor measures are polled every minute. Code targets moisture, temperature, and EC at 60 seconds, but current PyModbus compatibility and the register map block proof.
- [~] Dashboard exists. Template and route render in a mocked software check; never run against the real Pi database/hardware.
- [~] At least one real pump can be controlled. GPIO code exists; relay/pump behavior is unverified.
- [~] At least one explainable automation rule controls irrigation. Hysteresis logic exists; unsafe error paths remain.
- [~] Minimum local database structure exists as SQL source; schema creation on the Pi is unverified.
- [ ] Required dashboard screenshot is absent.
- [x] Automation flowchart exists as SVG and PNG and the SVG parses.
- [ ] Required `Foundation : Completed` SVN commit is not evidenced.

Dependencies: assembled farm, Pi 4, Raspberry Pi OS, USB-RS485 adapter/probe, relay/pump/button wiring, MariaDB, Python runtime. All later phases depend on this gate.

### Task1 — 5/16

- [ ] Pi connects to the event Central MySQL database and discovers its actual schema.
- [~] Pi-to-Central synchronization is implemented but is not idempotent and is unverified live.
- [~] MQTT `/test` and `/verify` handling exists, but live verification is absent and `/test` can acknowledge its own acknowledgement forever.
- [~] Dashboard can display an MQTT selfcare message; the Central-DB fetch helpers are unused.
- [~] Validation, parameterized SQL and escaped rendering exist; reproduced bypasses mean the system is not yet proven resistant to all challenge inputs.
- [~] ERD source exists at `docs/erd.mmd`; required rendered submission is absent.
- [ ] Required selfcare dashboard screenshot is absent.
- [ ] Required `Challenge1 : Completed` SVN commit is not evidenced.

Dependencies: Welcome; routed access to `192.168.98.50`; correct team name, DB schema, MQTT payload shape and credentials.

### Task2 — 3/12

- [ ] Required `hackathon/{teamName}/Challenge2` start trigger is implemented and sent.
- [~] Abnormal typed values are range-checked automatically.
- [~] Rejections can appear on the dashboard.
- [~] Rejected MQTT/serial values are not inserted, but Central DB ingestion bypasses validation and mixed sensor/message payloads can fall back to accepted selfcare text.
- [ ] Required stable-versus-malicious comparison screenshot is absent.
- [ ] Required `Challenge2 : Completed` SVN commit is not evidenced.

Dependencies: Task1 MQTT/DB connectivity; complete validation at every trust boundary; safe control behavior.

### Task3 — 6/16

- [ ] Required `Challenge3` trigger is implemented and sent.
- [~] Core irrigation logic is local to the Pi.
- [~] Sensor readings are written to local MariaDB.
- [~] Unsynced rows are buffered locally.
- [ ] Reconnect cannot yet guarantee no loss and no duplicates; a duplicate retry was reproduced.
- [~] Dashboard is locally hosted and should not require Central, but this is unverified on the Pi.
- [~] Sync retries automatically on its interval.
- [ ] Required `Challenge3 : Completed` SVN commit is not evidenced.

Dependencies: stable Welcome system; local database; Central route for before/after comparison.

### Task4 — 1/12

- [ ] Detect manually reduced water in Container 1 and block/adjust pumping safely.
- [ ] Define and implement crop-health/zone-priority allocation rather than equal distribution.
- [~] Two pump/relay GPIO objects exist, but only pump 1 is controlled.
- [ ] Demonstrate crop health under limited water.
- [ ] Explain the allocation logic with a clear reasoned policy.
- [ ] Required `Challenge4 : Completed` SVN commit is not evidenced.

Dependencies: Task3; four containers and two pumps/relays; calibrated water-level input; zone identity and crop-health priority data. The current database/control model has no zone allocation policy.

### Task5 — 4/14

- [~] A Modbus timeout/error becomes a caught `SensorError`.
- [~] The dashboard can show `sensor_error` after the controller observes an error.
- [ ] Irrigation does not reliably fail safe: the controller can act on the previous reading after a failed poll, and manual override is evaluated before stale-data shutdown.
- [~] The process catches errors and continues looping.
- [~] The dashboard process is designed to stay up, but has not been tested during removal.
- [ ] Required photo of the disconnected sensor and dashboard alert is absent.
- [ ] Required `Challenge5 : Completed` SVN commit is not evidenced.

Dependencies: Task4; stable Modbus polling; independent sensor services; explicit degraded-mode policy.

### FunBox — 3/10

- [~] A physical panel button is configured.
- [~] It has a backend action: toggle pump 1 with a 120-second manual hold.
- [~] The behavior is simple enough to explain quickly, but has not been demonstrated.
- [ ] The chosen feature and safety behavior are not documented as the phase submission explanation.
- [ ] Required `Challenge6 : Completed` SVN commit is not evidenced.

Dependencies: safe Welcome/Task5 control precedence and verified panel-button wiring.

### Perfect Storm — 0/8

- [ ] All previous challenge behaviors work simultaneously.
- [ ] Internet loss, one removed sensor, low water, and injected extreme temperature are handled together.
- [ ] No manual restart or live patch is needed.
- [ ] Required `Bonus Challenge : Completed` SVN commit is not evidenced.

Dependencies: verified completion of every preceding phase.

## Hardware and reference mapping

The Keyestudio tutorial is a behavioral and wiring reference for its ESP32 kit. It is not a Raspberry Pi wiring guide. The repository deliberately keeps the kit's analog sensors on the ESP32 and uses USB serial to the Pi; this avoids connecting analog outputs to Pi digital GPIO.

| Requirement / component | Keyestudio reference | Current Pi/ESP32 implementation | Differences, constraints, and unknowns |
|---|---|---|---|
| Target hardware | [Kit list and parameters](https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/index.html) | Pi 4 is the edge computer; ESP32 is a USB sensor node | Challenge packing list adds Pi 4, RS485 probe, 2-channel relay and two pumps beyond the stock kit |
| Kit wiring | [Assembly and factory ESP32 map](https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/4_Assemble_the_Smart_Farm_Kit.html) | Firmware retains DHT11 IO17, light IO34, water IO33, steam IO35 | Stock soil IO32 is omitted from firmware because the design instead expects the separate RS485 soil probe |
| DHT11 | [Temperature/humidity section](https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/5.7_Temperature_Control_System.html) | ESP32 reads DHT11 and sends temperature/humidity JSON at 60-second intervals | Digital sensor remains on ESP32; library version/compile and real reads are unverified |
| Light | [Light sensor section](https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/5.2_Light_Control_System.html) | ESP32 ADC IO34, raw 0–4095 mapped linearly to 0–100% | Reference confirms 12-bit raw range and increasing value with brightness; percentage is relative full scale, not calibrated illuminance |
| Steam/rain | [Rain detection section](https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/5.4_Rain_Detection_System.html) | ESP32 ADC IO35, mapped to `rainfall` 0–100% | Reference calls this a 3–5 V steam sensor. Keep it on ESP32; output and wet/dry calibration remain unverified |
| Water level | [Water-level section](https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/5.9_Water_Level_Monitoring_System.html) | ESP32 ADC IO33, stored in local DB | Reference sensor is DC 5 V and only its detection area is waterproof. Current controller never consumes the reading, so there is no low-water interlock |
| Soil moisture | [Stock analog soil section](https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/5.8_Soil_Humidity_Monitoring_System.html) | Separate RS485 3-in-1 probe via Pi USB adapter | Actual probe model, supply, A/B wiring, baud, slave ID, function code, register map and scaling are unconfirmed. Run the scanner before trusting values |
| Pump/relay | [Auto-irrigation section](https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/5.10_Auto-Irrigation_System.html) | Pi BCM17/27 drive a supplied 2-channel 5 V active-low relay; two 3–5 V pumps are expected on relay contacts | Tutorial uses one ESP32 IO25 relay and includes a water-level interlock. Current Pi code assumes active-low and 3.3 V-compatible relay inputs; verify relay board model, VCC/JD-VCC, idle state, contact wiring and separate pump supply before energizing |
| Physical button | [Button behavior](https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/5.1_Lighting_System.html) | Panel switch on Pi BCM26 with internal pull-up, active when shorted to ground | Packing list button is not necessarily the stock powered module. Wire the dry contact between GPIO and ground; do not feed 5 V into Pi GPIO |
| Web control | [Web-controlled farm](https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/5.11_Web-controlled_Smart_Farm.html) | Flask runs on Pi; ESP32 does not host Wi-Fi/web services | This is intentional: the Pi is the edge/server authority and the ESP32 uses USB serial |
| Pi electrical limits | [Official Raspberry Pi GPIO documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio-and-the-40-pin-header) | GPIO Zero uses BCM numbers | Pi GPIO is 3.3 V logic and motors must not be connected directly. Pumps require external power and driver/relay contacts. Never apply 5 V to a GPIO input |
| ESP32 ADC | [Official Arduino-ESP32 ADC documentation](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/adc.html) | Default 12-bit `analogRead()` | Default range is 0–4095; measurable voltage depends on attenuation. Current firmware does not explicitly set attenuation or calibrate channels |
| Modbus library | [PyModbus API changes](https://pymodbus.readthedocs.io/en/dev/source/api_changes.html) | Source calls `slave=` | PyModbus 3.10 replaced `slave=` with `device_id=`. Current dependency range permits incompatible releases |

Do not energize pumps or put them in water until relay logic, idle state, pump supply, hose routing, container placement, and emergency stop procedure have been physically checked. This audit did not operate any actuator.

## Known defects, blockers, and unverified behavior

Priority 0 — blocks safe Welcome bring-up:

1. `requirements.txt` permits PyModbus 3.10+, while `farm/sensors.py` and `tools/sensor_scan.py` call the removed `slave=` keyword. With PyModbus 3.15.0, the call raises `TypeError` before any serial transaction.
2. After an RS485 poll fails, `Controller.tick()` continues into `decide()` with the previous reading. If that prior reading is still younger than 180 seconds and dry, the controller can start the pump after the sensor has just failed.
3. Manual override is checked before stale-reading safety, so a manually running pump can remain on with stale/no current sensor input until the independent max-runtime cutoff.
4. The 1-second max-runtime checks in `_run()` call the pump object directly and do not write an automation-log row, despite the deployment guide expecting such evidence.
5. Relay active level, 3.3 V input compatibility, external pump power/contact wiring, and actual BCM wiring are unverified. These must be checked before actuator tests.

Priority 1 — blocks Tasks 1–3:

1. MQTT subscribes and publishes to the same `/test` topic. `handle_test()` acknowledges every message, including its own acknowledgement, which can form a message loop.
2. Non-JSON `/test` payloads bypass the common size/schema validators. Challenge trigger topics for Tasks 2 and 3 are absent.
3. `validate_broadcast()` can reinterpret an invalid sensor-shaped JSON object as a valid selfcare message if it also contains `message`.
4. `check_timestamp(float("nan"))` accepts NaN because both time comparisons are false.
5. `tools/attack_test.py` reports a validator crash as PASS whenever rejection was expected; its 18/18 result therefore proves expected accept/reject outcomes only when no unexpected exception occurs.
6. Sync commits to Central before marking local rows synced and has no stable unique key/upsert. If the Central commit succeeds and the local commit fails, retry inserts a duplicate. The Central schema/insert also drops `sensor_type`.
7. Functions to pull selfcare text from Central exist but no worker calls them. The only active selfcare path is MQTT broadcast.
8. Direct values already in Central/local DB are rendered without physical-range validation. Task2's attack description says Central will insert malicious values, so validating only MQTT/serial is insufficient.

Priority 1 — blocks Tasks 4–Perfect Storm:

1. `node_serial` stores ESP32 readings independently; the controller never receives `water_level` or `air_temperature`.
2. There is no container, zone, crop-priority, allocation, low-water cutoff, or pump-2 behavior.
3. `node_serial` treats any line without the literal `"sensor_value"` as harmless status, including malformed JSON, contrary to its claim that bad lines are recorded.
4. `DEPLOY.md` starts only the Flask app as a service. MQTT, sync and ESP32 serial workers would not survive reboot unless separately managed.
5. ESP32 firmware compilation, upload, serial port identity, ADC calibration, and live data are unverified. `/dev/ttyUSB0` and `/dev/ttyUSB1` can swap; stable `/dev/serial/by-id/` names are needed.
6. No challenge trigger implementation, phase screenshots/photos, rendered ERD, or SVN completion commits were found.

## Current work in progress

- Hardware is assembled and Pi/network setup is reported complete.
- Application deployment and all real sensor, database, dashboard, relay, pump, button, MQTT, Central DB, offline recovery, sensor-removal and combined-failure checks remain unverified.
- The immediate engineering focus is the Welcome gate: fix software blockers, bring up the DB and sensors, then verify relay logic without water before a controlled pump test.

## Setup, run, and test instructions for the current source

These are the commands represented by the repository. Run them on the Pi from the repository root. Because the checked-in PyModbus range is currently incompatible with its call syntax, install a pre-3.10 release until the source/dependency fix is committed:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install 'pymodbus>=3.6,<3.10'
sudo mysql < farm/db/schema_local.sql
python3 tools/attack_test.py
bash tools/preflight.sh
```

Discover and verify the real RS485 probe before running automation:

```bash
ls -l /dev/serial/by-id/
python3 tools/sensor_scan.py /dev/ttyUSB0 9600
python3 -m farm.sensors
```

The current design requires four long-running Python processes, not the three listed in the old README:

```bash
python3 -m farm.node_serial
python3 -m farm.mqtt_client
python3 -m farm.sync
python3 -m farm.app
```

Open `http://<pi-ip>:5000`. Do not run `python3 -m farm.actuator` until the relay inputs, normally-open contacts, external pump supply, inactive boot state, and dry hose/container setup are physically verified. That module energizes both configured relay channels.

Safe unresolved verification steps:

1. Record `cat /proc/device-tree/model`, `cat /etc/os-release`, `ip -brief addr`, `ip route`, and `ls -l /dev/serial/by-id/`.
2. Create/inspect the local schema and run the offline validator.
3. Scan the RS485 device and confirm register values against controlled wet/dry and temperature changes.
4. Compile/upload ESP32 firmware and observe valid JSON without starting any Pi actuator process.
5. Start `node_serial`, MQTT, sync and app; verify rows, dashboard and logs.
6. With pump power disconnected, verify relay idle state and logic using a meter/relay indicator. Then perform a separately authorized, supervised water test.
7. For every phase, retain terminal logs, DB queries and required screenshots/photos as evidence.

## Checks performed in this audit

- `git status --short`: existing untracked `.DS_Store` and `Phase/`; no tracked changes existed before documentation updates.
- Read every page/image in all eight PDFs in `Phase/` and visually inspected `docs/flowchart.png` plus relevant official wiring images.
- `python3 tools/attack_test.py`: **18/18 reported passed**. Limitation: the test harness crash-accounting defect described above weakens this result.
- Parsed/compiled 13 Python source files using `compile(...)`: **passed**.
- `bash -n tools/preflight.sh`: **passed** syntax check.
- Parsed `docs/flowchart.svg` as XML: **passed**.
- Installed project dependencies plus PDF tools in an isolated `/tmp` virtual environment; `pip check`: **no broken requirements**.
- Mocked software checks: Flask dashboard/status routes rendered, Jinja escaped a script payload, invalid pump action returned HTTP 400, valid/invalid ESP32-style readings routed as expected, and dry/wet controller decisions were exercised without real GPIO.
- Audit probes reproduced 21 observations, including the PyModbus API failure, MQTT self-ack behavior, sensor-failure unsafe decision, missing cutoff log, DB display bypass, and duplicate sync retry.

Not run: real Pi imports/runtime, MariaDB schema/query, RS485 traffic, ESP32 compile/upload, serial reads, relay/pump/button operation, Farm Central DB/MQTT, network blackout/recovery, physical sensor removal, water allocation, or Perfect Storm. No actuator was energized.

## Prioritized next actions and 26-hour allocation

The remaining-time assumption comes directly from the user at this audit point. Suggested allocation preserves the required phase order and includes two hours of final evidence/buffer:

1. **Hours 0–2, Welcome safety fixes:** resolve PyModbus API/version; make any current read failure invalidate control data and stop/refuse pumps; fix cutoff logging; add focused software tests.
2. **Hours 2–5, Welcome hardware bring-up:** deploy DB/app/workers; identify serial devices; calibrate/verify three RS485 values; validate relay idle state; controlled pump/button/automation demo; screenshot and commit.
3. **Hours 5–8, Task1:** discover Central schema, fix MQTT loop, make sync idempotent, prove selfcare/verify/sync, render ERD, capture evidence and commit.
4. **Hours 8–11, Task2:** implement challenge trigger and validation for Central DB as well as MQTT/serial; show stable vs rejected malicious readings; commit.
5. **Hours 11–14, Task3:** implement idempotent sync and run a real blackout/recovery test with row counts and unique IDs; commit.
6. **Hours 14–19, Task4:** integrate water level and pump 2, define a simple auditable priority policy, test low-water allocation with dry relay/pump safety first; commit.
7. **Hours 19–21, Task5:** enforce fail-safe degraded mode and physically remove the Modbus probe while capturing dashboard/system evidence; commit.
8. **Hours 21–22, FunBox:** verify and explain the panel-button action and safety precedence; commit.
9. **Hours 22–24, Perfect Storm:** run the combined scenario without restart or live patch; commit.
10. **Hours 24–26, evidence and contingency:** screenshots/photos, submission paths, service reboot test, clean demo rehearsal, and buffer.

Mandatory work is every phase acceptance item and its evidence/submission. Optional improvements include visual polish, extra sensors, richer analytics, additional automation modes, and architectural rewrites. They should wait until the full required sequence has demonstrable evidence.

## Chronological change log

### 2026-09-19 15:18 +08 — Initial evidence-based audit

- Changed: created this canonical tracker; marked `STATUS.md` as historical; added `AGENTS.md` instructions to keep this tracker current.
- Why: the repository had implementation claims and a Foundation-only snapshot but no auditable tracker for all eight required phases.
- Files/phases affected: documentation for Welcome, Task1, Task2, Task3, Task4, Task5, FunBox and Perfect Storm; no product source behavior changed.
- Tests: offline validator 18/18 reported pass; 13 Python files parsed; preflight shell syntax and flowchart SVG passed; dependency environment passed `pip check`; 21 software audit observations reproduced.
- Untested/blocked: all physical hardware and event-service verification listed above.
- Percentage change: initial checklist baseline established; no prior canonical percentages existed.
- Next action: fix the Welcome PyModbus and fail-safe control blockers, then perform a non-actuating Pi bring-up before any pump test.

