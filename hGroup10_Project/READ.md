# Save the Farm - canonical project tracker

Last updated: 2026-09-20 00:22 +08:00 (Asia/Singapore)

This is the canonical status record for branch `nicholas` at commit `44d173c`. `STATUS.md` is an older Foundation snapshot; where it conflicts with this file, use this file.

## Audit scope and evidence authority

The required sequence is:

**Welcome -> Task1 -> Task2 -> Task3 -> Task4 -> Task5 -> FunBox -> Perfect Storm**

The checked-out branch does not contain `Phase/`, but all eight source briefs were found in Git object `de9c546` on `origin/yao`. Every page was extracted and visually inspected without switching branches. Those PDFs and explicit user instructions are the requirement authority. The Keyestudio KS0567 guide and official Raspberry Pi, Espressif, and PyModbus documentation were used only to confirm component behavior and API/wiring facts.

This pass is an audit and documentation baseline. It did not energize a relay or pump, change application behavior, contact Farm Central, publish MQTT triggers, or claim physical verification.

## Project objective

Build and defend an edge-based irrigation system that reads real sensors at least once per minute, stores and displays the measurements, controls real pumps using explainable automation, remains safe under bad data and missing hardware, continues locally during a network outage, restores data without gaps or duplicates, allocates scarce water deliberately, exposes a useful physical button, and survives all failure conditions together.

## Current architecture

```text
RS485 3-in-1 probe
  -> USB-RS485 / Modbus RTU
  -> farm.sensors
  -> farm.sensor_health (source-level online/offline/invalid state)
  -> farm.control (moisture hysteresis decision source)
  -> local MariaDB sensor_data + automation_log
  -> Flask dashboard

Keyestudio ESP32 sensors
  -> newline JSON at 9600 baud over one shared USB serial connection
  -> farm.esp_link (sole serial owner)
  -> validation
  -> local MariaDB sensor_data
  -> Flask dashboard

Dashboard POST /pump/on|off
  -> farm.control
  -> EspPump
  -> shared farm.esp_link
  -> ESP32 JSON command
  -> ESP32 GPIO25
  -> relay
  -> pump 1

local MariaDB -> farm.sync -> Farm Central MySQL
Farm Central MQTT -> farm.mqtt_client -> validation -> local MariaDB
```

The default backend has one ESP32-controlled pump. The GPIO fallback defines two Pi relay channels, but the active controller only addresses pump 1. ESP32 water-level readings are stored and displayed but are not consumed by irrigation logic.

## Scoring method

Each phase has an explicit checklist derived from the brief's narrative, objectives, and submission requirements. Each criterion has equal weight within its phase:

- `2` - verified at the level required by the brief.
- `1` - implemented or credibly evidenced, but incomplete or not verified at the required hardware/integration level.
- `0` - absent, contradicted, unknown, or blocked.

`Completion % = earned points / maximum points * 100`, rounded to the nearest whole percent. Real sensor, actuator, Raspberry Pi, event-network, outage, or recovery behavior cannot receive full credit from source review or mocks alone.

## Phase status

| Phase | Completion % | Status | What is done | What is in progress | What remains | Blockers/dependencies | Evidence/verification |
|---|---:|---|---|---|---|---|---|
| Welcome | 38% (6/16) | In progress | Dashboard, local schema, three-channel RS485 reader, ESP32 node, pump command path, hysteresis automation, and flowchart files exist | Pi/ESP32 integration has software tests; a prior user log showed one three-reading MySQL insert | Prove one-minute live polling, current dashboard, relay/pump, automation, correct flowchart, screenshot, and SVN completion commit | Current Pi deployment appears older than this branch; PyModbus version/API risk; serial identity, relay polarity, and wiring unverified | 10/10 integration tests pass; prior Pi log is evidence for one insertion only; no current-head hardware run |
| Task1 | 31% (5/16) | In progress | Central DB config, local-to-central sync worker, request-only MQTT verification handler, validation, ERD source, and self-care dashboard card exist | Deploy the corrected same-topic response and capture Central's verdict | Prove Central MySQL/sync, successful MQTT acknowledgement, self-care display, rendered ERD, screenshot, and SVN commit | Automatic test-initiation payload is unknown; Central self-care fetch helper is unused; sync can duplicate | 16/16 local unit tests pass; Pi log captured the real request envelope and proved Central requires the response on the team `/test` topic |
| Task2 | 25% (3/12) | In progress | Typed MQTT/serial readings have physical-range checks; rejections can be shown on dashboard | Trust-boundary validation exists but is incomplete | Implement/publish Challenge2 trigger; validate hostile rows inserted by Central; prevent mixed-payload bypass; comparison screenshot; SVN commit | Challenge explicitly injects into the sensor table, while direct DB values bypass validation | Mixed invalid sensor plus `message` payload was reproduced as accepted self-care text |
| Task3 | 31% (5/16) | In progress | Control, dashboard, and local logging are designed to run on the Pi; unsynced rows are retried automatically | Local-first buffering and retry logic exist in source | Implement trigger; prove blackout behavior; make sync idempotent; restore every row with no gaps/duplicates; SVN commit | Central insert commits before local `synced` update and has no stable idempotency key | Source traced; no real outage/recovery test |
| Task4 | 8% (1/12) | In progress | A two-channel GPIO fallback exists as scaffolding | ESP32 water level is captured for display | Detect 25% low water; implement two pump flows, crop-health priority/allocation policy, low-water interlock, explanation, demo, and SVN commit | Default ESP backend exposes only pump 1; controller never reads water level; no zone/container model | Search found no `pump(2)` control path and no water-level decision path |
| Task5 | 36% (5/14) | Implemented locally, hardware verification pending | Two-second source-health checks, PyModbus `device_id`/legacy `slave` compatibility, typed failures, immediate auto/manual irrigation block, same-cycle pump stop, reconnect reset, structured API state, and offline dashboard labels exist | Pi ran 29/29 pre-compatibility tests and served the dashboard, exposing the live API/config blockers; the compatibility fix passes 30/30 locally | Deploy compatibility fix; configure stable ESP32 port; prove physical timeout, alert, continued readings, recovery, photo, and SVN commit | Pi runtime used PyModbus `device_id` API and had no `NODE_SERIAL_PORT`; neither actual removal nor continued ESP32 readings has been tested | Pi log records HTTP 200 dashboard responses and the two blockers; 30/30 current hardware-free tests pass; no actuator energized |
| FunBox | 30% (3/10) | Implemented but unverified | BCM26 button callback toggles pump 1 through the same controller backend | Backend action and 10-second cutoff are implemented | Wire/test a real panel button, document the chosen action and safety precedence, demonstrate, SVN commit | Physical wiring unverified; manual start bypasses minimum-rest check; production has no timed override despite UI/flowchart wording | Source review only; no recorded button press |
| Perfect Storm | 0% (0/8) | Not started | No combined-scenario evidence | Depends on all prior phases | Handle internet down, one sensor removed, low water, and extreme temperature simultaneously without restart/patch; SVN commit | Task2, Task4, and Task5 acceptance gaps must be closed first | No combined test or supporting evidence |

## Acceptance checklists

Legend: `[x]` verified (2), `[~]` implemented/reported but not fully verified (1), `[ ]` absent/unknown/failed (0).

### Welcome - 6/16

- [~] At least three real sensor measurements poll every minute. Code targets moisture, temperature, and EC every 60 seconds; one prior Pi log showed one three-value read, not sustained polling.
- [~] Dashboard exists and renders from the local database; current branch was not run with its dependencies during this audit.
- [~] At least one pump has a complete software command path; relay and pump behavior are not physically verified.
- [~] Explainable automation exists: moisture below 30% starts, above 45% stops, with hysteresis and safety cutoffs; no live demo exists.
- [~] Minimum `sensor_data` database schema exists and a prior Pi log showed an insert; current schema on the Pi was not inspected.
- [ ] Required dashboard screenshot is absent.
- [~] Flowchart SVG/PNG exist, but still show a 30-second cutoff and 120-second manual override that the production code does not implement.
- [ ] Required SVN `Foundation : Completed` commit is not evidenced in this Git checkout.

### Task1 - 5/16

- [ ] Live connection to the event Central MySQL database is not verified.
- [~] Pi-to-Central synchronization is implemented, but it is not idempotent and has not been exercised live.
- [~] MQTT `/test`, `/verify`, and broadcast handling exists; request IDs, supplied responses, reply topics, echoes, failures, and duplicates are handled locally, but Central has not yet acknowledged the deployed response.
- [~] Dashboard can display MQTT self-care text; the Central DB self-care fetch helpers have no caller.
- [~] Validation, parameterized SQL, and escaped Jinja rendering exist, but reproduced bypasses prevent a complete security claim.
- [~] ERD source exists at `docs/erd.mmd`; required rendered submission is absent.
- [ ] Required self-care dashboard screenshot is absent.
- [ ] Required SVN `Challenge1 : Completed` commit is not evidenced.

### Task2 - 3/12

- [ ] Required `hackathon/{teamName}/Challenge2` trigger and start message are absent.
- [~] Abnormal typed MQTT/serial sensor values are range-checked automatically.
- [~] Rejections can appear as a visible dashboard warning/log.
- [~] Rejected MQTT/serial values are not inserted, but challenge-injected Central/local DB rows bypass validation and mixed payloads can be misclassified.
- [ ] Required stable-versus-malicious comparison screenshot is absent.
- [ ] Required SVN `Challenge2 : Completed` commit is not evidenced.

### Task3 - 5/16

- [ ] Required `hackathon/{teamName}/Challenge3` trigger and start message are absent.
- [~] Core irrigation logic runs locally on the Pi in the intended architecture.
- [~] Readings are logged to local MariaDB; sustained offline operation is unverified.
- [~] Unsynced rows are buffered locally.
- [ ] Reconnection cannot guarantee no gaps and no duplicates because the Central and local commits are not atomic or idempotent.
- [~] Dashboard is locally hosted and should remain reachable on the LAN; outage behavior is unverified.
- [~] Sync retries automatically when the worker remains running.
- [ ] Required SVN `Challenge3 : Completed` commit is not evidenced.

### Task4 - 1/12

- [ ] Detect Container 1 being reduced to 25% and respond safely.
- [ ] Define and implement deliberate crop-health/zone-priority allocation rather than equal sharing.
- [~] Two relay channels exist only in the optional Pi GPIO backend; the default ESP32 backend and controller expose pump 1 only.
- [ ] Demonstrate maintained crop health with limited water.
- [ ] Explain a clear, reasoned allocation policy.
- [ ] Required SVN `Challenge4 : Completed` commit is not evidenced.

### Task5 - 5/14

- [~] Communication failures are classified, reset the Modbus client, and transition the physical source offline; actual removal is unverified.
- [~] Dashboard/API expose structured health, a visible Modbus alert, last-known labels, affected channels, and irrigation-block status; Flask rendering on the Pi is unverified.
- [~] A failed health check immediately gates both automatic and manual Pump ON and stops a running affected pump in the same software cycle; physical relay behavior is unverified.
- [~] Fast Modbus checks are independent of one-minute persistence, and the ESP32 reader remains an independent thread/source; continued live readings during removal are unverified.
- [~] Repeated failures are suppressed, the loop continues, and a later complete read recovers without restart in hardware-free tests; physical recovery is unverified.
- [ ] Required photo of the disconnected sensor and dashboard alert is absent.
- [ ] Required SVN `Challenge5 : Completed` commit is not evidenced.

### FunBox - 3/10

- [~] A physical panel button is configured on Pi BCM26.
- [~] It has a backend action: toggle pump 1 through the shared ESP32 serial path.
- [~] The feature is simple and potentially useful, but physical behavior and safety precedence are unverified.
- [ ] The chosen feature and rationale are not documented as a submission artifact.
- [ ] Required SVN `Challenge6 : Completed` commit is not evidenced.

### Perfect Storm - 0/8

- [ ] All previous challenge behaviors have not been shown working simultaneously.
- [ ] Internet loss, sensor removal, low water, and injected extreme temperature have not been tested together.
- [ ] No-restart/no-live-patching behavior is unverified.
- [ ] Required SVN `Bonus Challenge : Completed` commit is not evidenced.

## Hardware and official-reference mapping

| Component or requirement | Official reference behavior | Current implementation | Difference / risk |
|---|---|---|---|
| Keyestudio ESP32 board | Tutorial selects `ESP32 Dev Module` | Firmware targets ESP32 and was previously uploaded by the user | Current repository firmware has not been compiled in this audit; Arduino CLI is unavailable here |
| DHT11 | Signal on ESP32 IO17 | `DHT11PIN 17` | Matches; real readings and library compatibility not verified against current HEAD |
| Steam/rain sensor | Signal on IO35 | IO35 stored as `rainfall` percent | Pin matches; name and linear percentage are application choices, not calibrated rainfall |
| Photoresistor | Signal on IO34 | IO34 stored as `light` percent | Pin matches; ADC value is uncalibrated relative full-scale, not lux |
| Water-level sensor | Signal on IO33; only sensing area is waterproof | IO33 stored as `water_level` | Pin matches; current control logic ignores low water |
| Stock soil sensor | Analog IO32 | Omitted from ESP32 firmware; separate RS485 3-in-1 probe is used | Intentional architecture difference; actual register map/scaling must be verified |
| Relay/pump | Relay signal on IO25; stock example uses water-level interlock | ESP32 GPIO25 accepts serial pump commands and applies a 10-second cutoff | Pin matches; active level, contact wiring, supply, pump flow, and low-water interlock remain unverified |
| ESP32 ADC | Default `analogRead()` is 12-bit raw 0-4095 and non-calibrated | Firmware divides raw values by 4095 | Numerically consistent; channel-specific calibration is still required |
| Raspberry Pi GPIO | 3.3 V logic; motors must use a driver/controller | Optional GPIO backend uses a relay; default pump backend is ESP32 serial | Never connect a pump directly to Pi GPIO; verify relay input compatibility before energizing |
| PyModbus | From 3.10, `slave=` was replaced with `device_id=` | Source uses `slave=` while requirements permit any 3.x release below 4 | A fresh install can fail before sending a Modbus request; pin below 3.10 or update the calls |

Official references:

- Keyestudio kit and component list: <https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/>
- Keyestudio assembly and pin map: <https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/4_Assemble_the_Smart_Farm_Kit.html>
- Keyestudio auto-irrigation behavior: <https://docs.keyestudio.com/projects/KS0567/en/latest/wiki/Arduino/project/5.10_Auto-Irrigation_System.html>
- Espressif Arduino ADC: <https://docs.espressif.com/projects/arduino-esp32/en/latest/api/adc.html>
- Raspberry Pi GPIO guidance: <https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio-and-the-40-pin-header>
- PyModbus API changes: <https://pymodbus.readthedocs.io/en/dev/source/api_changes.html>

## Known defects, blockers, and unverified behavior

### Priority 0 - blocks a safe, current Welcome demonstration

1. The last Raspberry Pi log supplied by the user ran `python3 -m app.app` and showed old `self.link` and `/dev/ttyUSB1` failures. Current branch code is package `farm` and no longer uses `Controller.link`. The Pi and this branch must be synchronized before any result is attributed to current HEAD.
2. `requirements.txt` permits PyModbus 3.10+, while `farm/sensors.py` and `tools/sensor_scan.py` still call `slave=`. Official PyModbus documentation records the replacement with `device_id=` in 3.10.
3. A current RS485 poll failure leaves the previous `latest` reading valid. Until it becomes 180 seconds old, automation can still act on data from before the disconnection.
4. The flowchart is not the current implementation: it says 30-second maximum runtime and a 120-second manual override; production uses 10 seconds and `_manual_until` is never set above zero.
5. No explicit Flask/process shutdown hook calls `Controller.stop()`. Normal interpreter exit may leave cleanup to daemon-thread/process teardown; the ESP32 cutoff is the independent last safety layer.
6. Relay active polarity, normally-open contact wiring, external pump supply, hose routing, serial device identity, and current firmware on the physical ESP32 are unverified.

### Priority 1 - blocks Tasks 1-3

1. The MQTT self-ack/unsolicited-heartbeat defect is fixed locally and a real request was captured, but the corrected `/test` response still needs deployment and a recorded Central success verdict. No evidence defines a client-initiated test-request payload.
2. Challenge2 and Challenge3 topics/messages are absent.
3. `validate_broadcast()` tries a sensor validator and then a self-care validator. A JSON object with an impossible sensor value plus a benign `message` field was reproduced as accepted self-care text.
4. `check_timestamp(float('nan'))` was reproduced returning NaN instead of rejecting it.
5. `tools/attack_test.py` was reproduced printing `PASS` for an unexpected validator crash when a rejection was expected.
6. Task2 says Central will insert malicious sensor-table values. Database reads displayed by the dashboard do not revalidate physical ranges, so the active validator does not cover that attack path.
7. Sync commits to Central before marking local rows synced and uses no idempotency key/upsert. A failure between commits can insert the same reading again on retry.
8. The Central self-care query helpers have no worker or route calling them.
9. The deployment service example starts only the Flask app; MQTT and sync need their own supervised services to survive reboot.

### Priority 1 - blocks Tasks 4-Perfect Storm

1. Water level is stored/displayed but never reaches `Controller.decide()`; there is no low-water interlock.
2. The default ESP32 backend has only pump 1. There is no container/zone/crop-priority model or allocation policy.
3. Manual pump start uses `force=True`, bypassing minimum-rest policy. It still refuses if serial write fails and remains bounded by the ESP32's 10-second cutoff.
4. `EspLink` treats any line without the literal `"sensor_value"` as status; malformed/non-JSON status lines are logged but not recorded as rejected input.
5. The production dashboard exposes manual-override UI state, but production never activates a timed override. The preview simulates 120 seconds, so preview behavior differs from real behavior.
6. The dashboard requests Google Fonts. It remains usable with fallback fonts offline, but its appearance is not fully self-contained.
7. Required phase triggers, rendered ERD, screenshots/photos, and SVN completion evidence are absent from the current branch.

## Current work in progress

- Current code unifies ESP32 sensor input and pump output through one process-level serial owner and a Linux advisory lock.
- The missing `Controller.link` implementation from the older Pi deployment has been removed from current source.
- Ten integration tests cover command serialization, disconnected-link refusal, timeout status, singleton ownership, Controller construction, continued RS485 polling, stale-data stop, controller exception stop, and the 10-second runtime value.
- Hardware/electrical bring-up, Central integration, phase triggers, allocation, physical button, evidence capture, and the combined scenario remain unverified.

## Safe setup, run, and test instructions

Run from the repository root on the Raspberry Pi. Confirm that the deployed tree contains `farm/`, not an older `app/` copy.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
# Until the source uses device_id=, keep PyModbus below 3.10:
pip install 'pymodbus>=3.6,<3.10'
sudo mysql < farm/db/schema_local.sql
```

Identify devices without guessing plug-order-dependent names:

```bash
ls -l /dev/serial/by-id/
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
export RS485_PORT=/dev/serial/by-id/<rs485-adapter-id>
export NODE_SERIAL_PORT=/dev/serial/by-id/<esp32-id>
export NODE_SERIAL_BAUD=9600
export PUMP_BACKEND=esp
```

Safe software-only checks:

```bash
python3 -m unittest discover -s tests -v
python3 tools/attack_test.py
python3 tools/sensor_scan.py "$RS485_PORT" 4800
python3 -m farm.sensors
```

Long-running processes for the current architecture:

```bash
python3 -m farm.mqtt_client   # terminal/service 1
python3 -m farm.sync          # terminal/service 2
python3 -m farm.app           # terminal/service 3; owns ESP32 serial + control loop
```

Open `http://<pi-ip>:5000`. Do not also run `python3 -m farm.node_serial`; the application owns the same ESP32 port. Do not run the `farm.esp_link` or `farm.actuator` self-test entry points until relay power and pump safety have been physically checked, because those entry points intentionally issue pump-on commands.

## Checks performed in this audit

- Git state before documentation: clean `nicholas...origin/nicholas` at `44d173c`.
- All 11 pages in eight phase PDFs were rendered and visually inspected.
- Official Keyestudio pin/water-safety sections and official Raspberry Pi, Espressif, and PyModbus documentation were reviewed.
- `python -m unittest discover -s tests -v`: **10/10 passed**. Tests are hardware-free and use fakes.
- `python tools/attack_test.py`: **18/18 declared cases reported passed**. The crash-accounting weakness above limits this claim.
- Parsed/compiled all **16 Python source/test/tool files** without writing bytecode: **passed**.
- Parsed `docs/flowchart.svg` as XML: **passed**; content mismatch remains.
- Reproduced mixed-payload validation bypass, NaN timestamp acceptance, and attack-test crash-as-pass behavior.
- Local dashboard render check was not run because Flask is not installed in the available Windows Python environments.
- Arduino firmware compilation was not run because `arduino-cli` is unavailable.

Not run: current code on the Raspberry Pi, MariaDB schema/query verification, sustained RS485 polling, current firmware compile/upload, stable ESP32 path detection, relay/pump/button operation, Farm Central DB/MQTT, challenge triggers, blackout/recovery, physical sensor removal, limited-water allocation, or Perfect Storm. No actuator was energized.

## Prioritized next actions

1. **Synchronize the Raspberry Pi with current `nicholas` source** and confirm the package name, Git/SVN revision, and stable serial paths before diagnosing old logs.
2. **Close Welcome safety blockers**: pin/update PyModbus, deploy and physically verify immediate failure handling, add graceful shutdown, and correct/regenerate the flowchart.
3. **Run a non-actuating Pi bring-up**: database, RS485 readings, ESP32 JSON/status, dashboard, and logs with pump power disconnected.
4. **Verify relay safety physically**, then perform one supervised pump command and automation cycle; capture the required Welcome screenshot and submit via SVN.
5. **Complete Task1 before Task2**: deploy the request-only MQTT handler, capture the full Central request and verdict, then make sync idempotent, wire the Central self-care source, prove live sync, render the ERD, capture evidence, and commit.
6. Implement and verify Task2/3 triggers and failure behavior, integrate Task4's two-pump allocation/low-water interlock with `SensorHealth.can_irrigate()`, then physically verify Task5 before FunBox/Perfect Storm.

## Chronological change log

### 2026-09-20 00:22 +08:00 - Pi runtime blockers and PyModbus compatibility

- Actual Pi evidence: `python3 -m unittest discover -s tests -v` passed 29/29 and quiet `compileall` completed. `farm.app` remained up and served the dashboard/CSS with HTTP 200/304 responses.
- Runtime blocker found: the installed PyModbus rejects `slave=` and requires `device_id=`. This was a software API mismatch, not evidence that the physical sensor had been removed.
- Runtime blocker found: `NODE_SERIAL_PORT` was empty, so the ESP32 reader retried every five seconds and independent sensor continuity could not be demonstrated.
- Changed: `farm/sensors.py` now prefers current PyModbus `device_id=` and falls back only when an older version rejects that keyword. Transport failures still reset the client and fail safe.
- Tests: added modern-API and legacy-keyword coverage. The current hardware-free suite passes 30/30 and Python compilation succeeds. No hardware path was invoked.
- Phases affected: Welcome and Task5 Modbus compatibility. Task1 MQTT, Task2 validation, Task3 synchronization, Task4 allocation, firmware, database schema, and dashboard layout are unchanged.
- Unverified: the fix has not been copied to the Pi; the correct stable ESP32 `/dev/serial/by-id/...` path is not recorded; no physical removal/reconnection or continued-reading test has occurred.
- Percentage change: Task5 remains 36% (5/14) pending actual hardware evidence.
- Next action: upload `farm/sensors.py` and `tests/test_modbus_sensor.py`, list `/dev/serial/by-id/`, start `farm.app` with the real `NODE_SERIAL_PORT`, confirm both sensor sources are healthy, then conduct the powered-off-pump removal/recovery test.

### 2026-09-20 00:09 +08:00 - Task 5 sensor-removal fail-safe implementation

- Changed: added `farm/sensor_health.py` with thread-safe source-level health, timestamps, affected channels, irrigation eligibility, transition suppression, and automatic recovery state.
- Changed: `farm/sensors.py` now distinguishes communication loss from implausible data, never returns partial values, resets the Modbus client after transport/protocol failure, and reconnects on a later check.
- Changed: `farm/control.py` checks sensor health every two seconds while preserving one-minute database persistence. A failed check immediately blocks cached data, stops a running affected pump, blocks automatic/manual Pump ON, avoids duplicate decisions on repeated failures, and resumes from a later complete valid read without application restart.
- Changed: the dashboard/API now expose the structured health state, describe the affected zone/channels, mark retained values as `Offline - last known`, keep independent channels visibly live, and disable the visual Pump ON control while the soil source is unavailable. Server-side blocking remains authoritative.
- Tests: baseline was 16/16. The expanded hardware-free suite passes 29/29, covering health transitions, same-cycle stop, cached-low-value blocking, manual-start refusal, repeated-timeout suppression, unrelated-zone eligibility, invalid-data classification, Modbus client reset, complete reads, and restart-free recovery. Changed Python files compile successfully.
- Phases affected: Task5 primarily; Welcome, FunBox safety, and future Task4/Perfect Storm integration benefit from the shared safety gate. MQTT verification, Task2 validation, Task3 synchronization, database schema, firmware, and physical wiring are unchanged. No serial port, relay, or pump was activated.
- Unverified: Raspberry Pi/PyModbus compatibility, actual removal timing, live dashboard rendering, continued ESP32 timestamps, relay state, automatic physical reconnection, required photo, and SVN submission.
- Percentage change: Task5 remains 36% (5/14). The missing behavior is implemented and locally tested, but the scoring policy does not award full hardware criteria without actual device evidence.
- Next action: deploy the changed Task5 files to the Pi, keep pump power disconnected, run the full suite, then unplug/reconnect the Modbus probe while recording logs, dashboard state, continued ESP32 readings, and the required photo.

### 2026-09-19 22:15 +08:00 - Task 1 live response-topic correction

- Evidence: the Pi received a real `mqtt_test` request whose instruction says to copy the supplied response object and publish it to `hackathon/hGroup10/test`. The previous local fallback incorrectly chose `/verify`, so the two queued replies could not satisfy Central.
- Changed: the structured reply-topic override remains supported, but the observed protocol default is now the team `/test` topic.
- Tests: added the exact live Central envelope as a regression case. The full hardware-free suite passes 16/16 and both changed Python files parse successfully.
- Phases affected: Task1 only. Selfcare, synchronization, dashboard, sensors, irrigation, firmware, and Tasks 2-5 are unchanged. No pump path was invoked.
- Unverified: Central success is not yet recorded. The judge manually initiated the observed test; the repository and live request do not reveal a supported client-to-Central initiation payload, so none was invented.
- Percentage change: Task1 remains 31% (5/16) pending a Central success verdict.
- Next action: upload the corrected `farm/mqtt_client.py` and test file, restart the client, have Central initiate one test, and retain its success/failure verdict.

### 2026-09-19 22:05 +08:00 - Task 1 MQTT verification handshake fix

- Changed: `farm/mqtt_client.py` now responds only to `mqtt_test`, validates `requestId`, preserves a valid Central-supplied response object, validates an explicit reply topic, ignores response echoes and failure notifications, logs complete failure objects with sensitive fields redacted, and suppresses duplicate request IDs for 120 seconds. The initial default was `/verify`; the later live correction above supersedes it with `/test`.
- Changed: removed the startup and 30-second custom verify heartbeats that the Pi log showed echoing back from `/verify`; broadcast/Selfcare handling is unchanged.
- Tests: added five hardware-free MQTT tests covering the supplied response envelope, fallback response, exact-once duplicate handling, echo/failure handling, and invalid response rejection. The full suite passes 15/15; both changed Python files parse successfully.
- Phases affected: Task1 only. No sensor, synchronization, dashboard, irrigation, firmware, Task2-Task5, FunBox, or Perfect Storm behavior changed. No pump path was invoked.
- Unverified: this computer cannot reach `192.168.98.50:1883`; the new handler has not received a real Central request or success verdict. The exact live envelope must be confirmed from the Pi log.
- Percentage change: Task1 remains 31% (5/16) because protocol handling is locally verified but Central acceptance is not yet evidenced.
- Next action: copy/update these files on the Pi, restart only `farm.mqtt_client`, and retain the complete `mqtt_test` request plus `mqtt_test_success`/`mqtt_test_failed` verdict in the log.

### 2026-09-19 16:47 +08:00 - First-pass audit baseline for `nicholas`

- Changed: created this canonical tracker and restored concise repository maintenance instructions in `AGENTS.md`.
- Why: the current branch had no all-phase tracker and omitted the phase briefs/instructions that exist on `origin/yao`.
- Product behavior changed: none.
- Phases affected: documentation/evidence baseline for all eight phases.
- Checks: 10/10 integration tests, 18/18 declared attack cases, 16 Python files parsed, flowchart XML parsed, all phase PDF pages inspected.
- Untested/blocked: all physical hardware and live event-service behaviors listed above.
- Percentage change: initial canonical scores established for this branch; no previous `READ.md` score existed here.
- Next action: synchronize the Pi to this revision and fix Welcome safety/documentation blockers before any powered pump test.
