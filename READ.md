# Save the Farm — live project tracker

Last updated: 2026-09-19 16:09 +08 (Asia/Kuala_Lumpur)

This is the canonical status record. `STATUS.md` is retained as a historical snapshot from earlier on 2026-09-19; where it conflicts with this file, use this file.

## Objective and current scope

Build and defend an edge-based farm irrigation system within the 30-hour challenge. The system must read real sensors, control real pumps, make explainable automation decisions, keep operating through bad input, network loss, low water, and sensor removal, and survive all conditions together in the final test.

Required phase sequence:

**Welcome → Task1 → Task2 → Task3 → Task4 → Task5 → FunBox → Perfect Storm**

At 15:18 +08 the user reported **26 hours remained**, the hardware was assembled, and the Raspberry Pi/network setup was complete. The application has not yet been verified on the Pi. No command output or photographs from that setup were available during this audit, so those claims are recorded as user-reported rather than independently verified.

## Intended architecture and current merged state

- Target computer: Raspberry Pi 4 Model B, 2 GB, running the preloaded Raspberry Pi OS image specified by `Phase/welcome.pdf`.
- The Pi is intended to own the Flask dashboard, MariaDB local buffer, irrigation decisions, physical button input, MQTT client, and central-database sync worker.
- A Keyestudio ESP32 Plus board is intended to read the kit's DHT11 and analog channels, send newline-delimited JSON to the Pi over USB serial, and—according to the newly merged `esp_link.py`—receive pump commands for the relay on ESP32 IO25.
- A separate 3-in-1 moisture/temperature/EC probe is intended to connect directly to the Pi through USB-RS485 and Modbus RTU.
- The merged repository contains two incompatible relay architectures. `control.py` still instantiates the Pi GPIO backend (pump 1 BCM17, pump 2 BCM27), while `esp_link.py` and the ESP32 firmware describe an ESP32 IO25 relay. The physical button remains assigned to Pi BCM26. The actual relay wiring has not been verified in this audit.
- Farm Central is configured at `192.168.98.50` for MySQL and MQTT. The Pi stores readings locally first and a separate worker attempts to copy unsynced rows to Central.

Intended execution paths after the merge:

```text
RS485 probe -> farm.sensors -> farm.control -> local MariaDB -> dashboard
                                      |-> pump command -> ESP32 IO25 relay

ESP32 kit sensors <-> farm.esp_link over one USB serial owner -> local MariaDB

MQTT broadcast/test/verify -> farm.mqtt_client -> validator -> local MariaDB

local MariaDB -> farm.sync -> Farm Central MySQL
```

This intended path is **not operational at the merged HEAD**. `control.py` does not instantiate `esp_link`, calls an undefined `self.link`, and catches an exception class absent from `node_serial`. `esp_link` references three missing configuration values, and the ESP32 sketch does not compile. Water-level and air-temperature readings still do not influence irrigation. Pump 2 has no zone-allocation control path.

## Status scoring method

Each phase has an explicit, equally weighted checklist. Every criterion is worth two points:

- `0` — absent, unknown, or contradicted by evidence.
- `1` — implemented or reported ready, but incomplete or not verified at the required integration/hardware level.
- `2` — verified at the level the brief requires. Real sensor, pump, network, or failure behavior requires evidence from the actual hardware/event services; a mock or source review cannot earn full credit for it.

`Completion % = earned points / maximum points × 100`, rounded to the nearest whole percent. This measures requirement completion, not code volume. Refactoring earns no points by itself.

## Phase status

| Phase | Completion % | Status | Completed work | Work in progress | Remaining work / blockers | Evidence and verification |
|---|---:|---|---|---|---|---|
| Welcome | 44% (7/16) | In progress | Hardware/Pi/network setup reported complete; dashboard, schema, sensor, relay, automation code and flowchart exist | Merged ESP32 sensor/pump integration is broken and bring-up has not started from recorded evidence | Repair merged controller/config/firmware; fix PyModbus and fail-safe defects; create DB; prove 3 real readings/minute, dashboard, pump and automation; capture screenshot; SVN submission | Post-merge probes reproduced controller, ESP backend, PyModbus and fail-safe failures; ESP32 static review found compile blockers; no Pi/hardware run recorded |
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

- [~] At least three real sensor measures are polled every minute. Code targets moisture, temperature, and EC at 60 seconds, but PyModbus compatibility blocks RS485 calls and the merged ESP32/controller path is internally inconsistent.
- [~] Dashboard exists. Template and route render in a mocked software check; never run against the real Pi database/hardware.
- [~] At least one real pump can be controlled. Both Pi-GPIO and ESP32-serial implementations exist, but the controller still selects Pi GPIO while the new firmware expects ESP32 relay control; neither path is verified.
- [~] At least one explainable automation rule controls irrigation. Hysteresis logic exists, but a current sensor failure can still act on the previous dry reading and manual ON now force-starts without a valid reading.
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
| Pump/relay | [Auto-irrigation section](https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/5.10_Auto-Irrigation_System.html) | Merged code conflicts: `control.py` selects Pi BCM17/27 GPIO, while `esp_link.py` and firmware target ESP32 IO25 | Choose the architecture that matches physical wiring, remove the unused owner, then verify active level, boot-off state, contact wiring and pump supply before energizing |
| Physical button | [Button behavior](https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/5.1_Lighting_System.html) | Panel switch on Pi BCM26 with internal pull-up, active when shorted to ground | Packing list button is not necessarily the stock powered module. Wire the dry contact between GPIO and ground; do not feed 5 V into Pi GPIO |
| Web control | [Web-controlled farm](https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/5.11_Web-controlled_Smart_Farm.html) | Flask runs on Pi; ESP32 does not host Wi-Fi/web services | This is intentional: the Pi is the edge/server authority and the ESP32 uses USB serial |
| Pi electrical limits | [Official Raspberry Pi GPIO documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio-and-the-40-pin-header) | GPIO Zero uses BCM numbers | Pi GPIO is 3.3 V logic and motors must not be connected directly. Pumps require external power and driver/relay contacts. Never apply 5 V to a GPIO input |
| ESP32 ADC | [Official Arduino-ESP32 ADC documentation](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/adc.html) | Default 12-bit `analogRead()` | Default range is 0–4095; measurable voltage depends on attenuation. Current firmware does not explicitly set attenuation or calibrate channels |
| Modbus library | [PyModbus API changes](https://pymodbus.readthedocs.io/en/dev/source/api_changes.html) | Source calls `slave=` | PyModbus 3.10 replaced `slave=` with `device_id=`. Current dependency range permits incompatible releases |

Do not energize pumps or put them in water until relay logic, idle state, pump supply, hose routing, container placement, and emergency stop procedure have been physically checked. This audit did not operate any actuator.

## Known defects, blockers, and unverified behavior

Priority 0 — blocks safe Welcome bring-up:

1. The merged `control.py` calls `self.link.snapshot()` although `self.link` is never initialized. Its handler references `node_serial.NodeSerialError`, which does not exist. A mocked successful RS485 poll therefore ends in `AttributeError` after inserting the readings.
2. `esp_link.py` cannot construct its backend because `config.PUMP_BACKEND`, `config.ESP_RELAY_PIN`, and `config.ESP_KEEPALIVE_S` are absent. `control.py` imports `actuator`, not `esp_link`, so the new serial pump backend is dead code even if those settings are restored.
3. The merged ESP32 sketch has duplicate `POSITION` and `percentOfFullScale` definitions and references undefined `RELAY_ACTIVE_HIGH`, `clampPercent`, `chk`, `setPump`, `COMMAND_TIMEOUT_MS`, and `handleCommand`. It cannot compile in its current form.
4. Serial baud rates disagree: firmware uses 115200 while the merged Pi configuration uses 9600. Even a compiled board and repaired Python link would not communicate with defaults.
5. `requirements.txt` permits PyModbus 3.10+, while `farm/sensors.py` and `tools/sensor_scan.py` call the removed `slave=` keyword. With PyModbus 3.15.0, the call raises `TypeError` before any serial transaction.
6. After an RS485 poll fails, `Controller.tick()` still calls `decide()` with the previous reading. A mocked current failure with a previous fresh dry reading started pump 1.
7. `Controller.manual("on")` now calls `pump.start(force=True)`. A mocked check proved it starts with no sensor reading and bypasses minimum rest. A manual command needs an explicit, documented safety policy rather than bypassing all start gates.
8. The 1-second max-runtime checks in `_run()` still call the pump directly and do not write an automation-log row, despite the deployment guide expecting that evidence.
9. The relay owner, active level, external pump power/contact wiring, boot state and actual physical pins are unresolved. Do not run either actuator self-test until the code architecture matches verified wiring.

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
- Merge commit `c555596` added `esp_link.py` and altered the controller/firmware, but the resulting Welcome integration is not runnable as checked above. `READ.md` was not updated in that merge; this entry reconciles it.
- Application deployment and all real sensor, database, dashboard, relay, pump, button, MQTT, Central DB, offline recovery, sensor-removal and combined-failure checks remain unverified.
- The immediate engineering focus is the Welcome gate: restore one coherent controller/ESP32 serial implementation, fix fail-safe behavior and PyModbus compatibility, then bring up the DB and sensors before any relay command.

## Setup, run, and test instructions for the current source

The merged HEAD is not safe to deploy or run against actuators. The commands below are limited to environment/database setup and non-actuating checks. Because the checked-in PyModbus range is incompatible with its call syntax, install a pre-3.10 release until the source/dependency fix is committed:

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

After the ESP32 integration is repaired, only one process may own its serial port. Use the integrated `esp_link` inside the Flask/control process **or** the standalone `node_serial` worker, never both. The intended repaired process set is:

```bash
python3 -m farm.mqtt_client
python3 -m farm.sync
python3 -m farm.app
```

Do not start `farm.app`, `farm.actuator`, or `farm.esp_link` against connected relay hardware at the current merged HEAD. First repair and software-test the integration. Then verify the chosen relay input, normally-open contacts, external pump supply, inactive boot state, and dry hose/container setup. Both actuator self-test modules can energize a relay.

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
- Parsed/compiled the original 13 Python source files using `compile(...)`: **passed**.
- `bash -n tools/preflight.sh`: **passed** syntax check.
- Parsed `docs/flowchart.svg` as XML: **passed**.
- Installed project dependencies plus PDF tools in an isolated `/tmp` virtual environment; `pip check`: **no broken requirements**.
- Mocked software checks: Flask dashboard/status routes rendered, Jinja escaped a script payload, invalid pump action returned HTTP 400, valid/invalid ESP32-style readings routed as expected, and dry/wet controller decisions were exercised without real GPIO.
- Audit probes reproduced 21 observations, including the PyModbus API failure, MQTT self-ack behavior, sensor-failure unsafe decision, missing cutoff log, DB display bypass, and duplicate sync retry.
- Post-merge Welcome review at commit `c555596`: all 14 Python files parse and the offline validator reports 18/18, but runtime probes reproduced the missing ESP configuration, undefined controller link/exception, PyModbus failure, previous-reading pump start, and force-start without readings. Static firmware review found eight undefined/duplicate-symbol categories and the 9600/115200 baud mismatch. Arduino compilation was unavailable because `arduino-cli` is not installed.

Not run: real Pi imports/runtime, MariaDB schema/query, RS485 traffic, ESP32 compile/upload, serial reads, relay/pump/button operation, Farm Central DB/MQTT, network blackout/recovery, physical sensor removal, water allocation, or Perfect Storm. No actuator was energized.

## Prioritized next actions

Follow this sequence to restore the Welcome gate before continuing through the required phase order:

1. **Welcome merge repair first:** choose the relay owner that matches wiring; restore a single `esp_link`/controller/config/firmware implementation; align baud; compile firmware; add protocol and controller tests.
2. **Welcome safety fixes:** resolve PyModbus API/version; make every current read failure invalidate decision data and stop/refuse pumps; define safe manual-start gates; log cutoff interventions.
3. **Welcome hardware bring-up:** deploy DB/app/workers; identify stable serial paths; calibrate/verify three RS485 values; validate relay idle state with pump power disconnected; then perform a controlled pump/button/automation demo, screenshot and commit.
4. **Then continue in required order:** Task1 → Task2 → Task3 → Task4 → Task5 → FunBox → Perfect Storm, retaining the detailed acceptance checklists above.

Mandatory work is every phase acceptance item and its evidence/submission. Optional improvements include visual polish, extra sensors, richer analytics, additional automation modes, and architectural rewrites. They should wait until the full required sequence has demonstrable evidence.

## Chronological change log

### 2026-09-19 16:09 +08 — Post-merge Welcome / Priority 0 review

- Changed: reconciled the tracker with merge commit `c555596`; documented the new ESP32 serial-pump design and its merged-state failures. No product source was changed.
- Why: the merge added 512 lines across controller/config/sync/firmware work without the required tracker update, and the resulting Welcome path contains runtime and firmware compile blockers.
- Files/phases affected: `READ.md`; Welcome and dependencies used by later phases.
- Tests: 14 Python files parsed; preflight shell syntax passed; offline validator reported 18/18; dependency environment passed `pip check`; mocked runtime probes reproduced five critical failure classes; firmware static check found duplicate and undefined symbols plus baud mismatch.
- Untested/blocked: Arduino compile/upload, Pi runtime, DB, real serial devices, relay/pump/button and all Central services. No actuator was energized.
- Percentage change: Welcome remains 44% because no acceptance item gained required integration or hardware verification; the blocker list increased based on merged-source evidence.
- Next action: repair one coherent ESP32/controller/config protocol and test it without relay power, then address RS485 and fail-safe defects.

### 2026-09-19 15:18 +08 — Initial evidence-based audit

- Changed: created this canonical tracker; marked `STATUS.md` as historical; added `AGENTS.md` instructions to keep this tracker current.
- Why: the repository had implementation claims and a Foundation-only snapshot but no auditable tracker for all eight required phases.
- Files/phases affected: documentation for Welcome, Task1, Task2, Task3, Task4, Task5, FunBox and Perfect Storm; no product source behavior changed.
- Tests: offline validator 18/18 reported pass; 13 Python files parsed; preflight shell syntax and flowchart SVG passed; dependency environment passed `pip check`; 21 software audit observations reproduced.
- Untested/blocked: all physical hardware and event-service verification listed above.
- Percentage change: initial checklist baseline established; no prior canonical percentages existed.
- Next action: fix the Welcome PyModbus and fail-safe control blockers, then perform a non-actuating Pi bring-up before any pump test.
