# Challenge 4 Handoff

This document is the integration handoff for the isolated Challenge 4 work. It
is intended for a teammate or Codex instance integrating Challenge 4 into the
latest Task 1–3 baseline without relying on previous chat history.

The document deliberately separates:

- **VERIFIED PHYSICAL FACTS** supplied from the completed hardware bring-up;
- **CURRENT ISOLATED SOFTWARE** present in this repository; and
- **FUTURE INTEGRATION WORK** that has not been implemented in production.

Do not treat an isolated test artifact as production firmware. Do not copy old
Task 1 production files wholesale over newer Task 2/3 work.

## 1. Objective

Challenge 4 adds scarcity-aware, crop-priority-based irrigation over two
physically independent water paths:

```text
Container 1 -> Pump 1 -> Container 2 / Zone 1
Container 3 -> Pump 2 -> Container 4 / Zone 2
```

Container 1 and Container 3 are separate sources. Pump 1 cannot deliver water
to Zone 2, and Pump 2 cannot deliver water to Zone 1. No cross-zone water or
pump substitution is physically possible or permitted by policy.

The isolated work currently provides:

1. empirical Container 1 ADC calibration;
2. a pure, deterministic allocation policy;
3. a hardware-free terminal demonstration;
4. tests for calibration, policy, demo behavior, and serial command encoding;
5. an isolated dual-pump firmware and manual serial bring-up utility.

It does **not** yet connect those pieces to the production controller,
production ESP link, Flask application, database, MQTT, sync, dashboard, or
canonical production firmware.

## 2. Verified Physical Hardware

The following are the **verified physical facts supplied for this handoff**.
They were not re-tested while creating this document.

### Pump 1

- Existing Keyestudio single relay.
- ESP32 GPIO25.
- Relay is **active-high**.
- Water path: Container 1 -> Pump 1 -> Container 2 / Zone 1.

### Pump 2

- Uses **K1 / IN1 only** on the two-channel relay module.
- ESP32 GPIO14.
- Relay is **active-low**.
- Water path: Container 3 -> Pump 2 -> Container 4 / Zone 2.
- K2 / IN2 is unused.

### Verified isolated bring-up safety

- Both pumps are OFF on boot.
- Each pump has a 10-second maximum continuous runtime.
- Repeating ON for an already-running pump does not reset its original safety
  timer.
- A one-pump-at-a-time interlock is enforced. Starting one pump stops the other
  with reason `interlock` before the requested pump starts.
- Pump 1 and Pump 2 were each independently verified physically.

The current isolated sketch
`firmware/task4_dual_pump_test/task4_dual_pump_test.ino` agrees with these
facts: it defines Pump 1 as GPIO25 active-high, Pump 2 as GPIO14 active-low,
`PUMP_MAX_RUN_MS = 10000`, boot-OFF initialization, repeated-ON protection, and
the interlock. That sketch remains a bring-up artifact, not production
firmware.

## 3. Container / Zone Meaning

| Container | Meaning |
|---|---|
| C1 | Measured scarce source for Pump 1 and Zone 1. |
| C2 | Zone 1 receiving/irrigation area. |
| C3 | Independent source for Pump 2 and Zone 2. |
| C4 | Zone 2 receiving/irrigation area. |

C1 has the Keyestudio water-level sensor connected to ESP32 GPIO33.

C3 does **not** have a water-level sensor. Software must represent C3 only as:

```python
container_3_available: bool
```

Never invent, derive, display, store, or transmit a Container 3 water
percentage. `False` is a valid operational state meaning the C3/Pump 2/Zone 2
path is unavailable; a non-Boolean value is invalid allocation input.

## 4. Water-Level Calibration

The empirical C1 measurements from the actual hackathon container/sensor are:

```text
ADC 0    -> approximately 0% / empty
ADC 1700 -> physical 25%
ADC 2000 -> approximately 100% / full
```

Container volume is non-linear relative to sensor ADC response. The pure
function `farm.task4_calibration.calibrate_c1_water_percent()` therefore uses
piecewise-linear interpolation through all three measured anchors.

For `0 <= ADC <= 1700`:

```text
percent = ADC * 25 / 1700
```

For `1700 < ADC < 2000`:

```text
percent = 25 + (ADC - 1700) * 75 / 300
```

- ADC values below 0 clamp to 0%.
- ADC values at or above 2000 clamp to 100%.
- Booleans and non-numeric values raise `TypeError`.
- NaN and positive/negative infinity raise `ValueError`.
- ADC 1700 maps to exactly `25.0`.
- ADC 1500 maps to approximately `22.0588%`.

> **Do not use `raw / 2000 * 100`.** That incorrect formula maps ADC 1700 to
> approximately 85%, contradicting the physical 25% measurement.

### Production sensor-contract warning

The current canonical Task 1 firmware calls `percentOfFullScale()` and emits
GPIO33 `water_level` as `raw / 4095 * 100`, not as raw ADC. Do **not** pass that
pseudo-percentage into `calibrate_c1_water_percent()` as though it were raw
ADC. It is only an ADC full-scale percentage; it is **not** the physical C1
water percentage.

Task 4 calibration requires the raw GPIO33 ADC reading and applies these
empirical anchors:

```text
raw 0    -> 0%
raw 1700 -> 25%
raw 2000 -> 100%
```

Final Task 1–4 integration must explicitly design a backward-compatible way
for the Pi/controller to obtain raw GPIO33 ADC before applying
`farm/task4_calibration.py`. Preserve the existing Task 1–3 sensor contract
where possible—for example, add a clearly named raw field while retaining the
legacy field during migration—rather than silently changing the meaning or
units of `water_level`. Audit Task 2 validation before introducing a raw value
greater than 100. Never feed the legacy `raw / 4095 * 100` value into
`calibrate_c1_water_percent()`.

## 5. Allocation Policy

The pure policy is implemented in `farm/allocation.py`. It imports no GPIO,
serial, Flask, MQTT, database, controller, or hardware module.

### Input contract

```python
AllocationInput(
    container_1_water_percent: Optional[float],
    container_1_valid: bool = True,
    container_1_fresh: bool = True,
    container_3_available: bool = True,
    zone_1_priority: int = 1,
    zone_2_priority: int = 1,
    pump_1_available: bool = True,
    pump_2_available: bool = True,
    scarcity_threshold_percent: float = 25.0,
)
```

The integration layer must calibrate raw C1 ADC before constructing this
object and must set the C1 valid/fresh flags from real runtime state.

### Policy rules

- Scarcity is triggered **only** by calibrated C1 water percentage.
- Default scarcity threshold is 25%.
- C3 availability never triggers scarcity because C3 has no level sensor.
- Crop priorities are configured positive integers.
- Higher integer means a more important crop.
- Soil moisture is **not** part of Challenge 4 allocation.
- Equal crop priorities deterministically select Zone 1.
- `requested_pumps` always remains empty in the pure policy.
- `allowed_pumps` identifies paths policy permits; it is not an actuator
  command and does not imply simultaneous operation.
- `deferred_zones` identifies a physically healthy path intentionally delayed
  to conserve scarce C1 water.
- `restricted_zones` identifies a path that cannot operate safely because its
  source/pump is unavailable or C1 is empty.
- Actual demand, one-pump scheduling, minimum rest, runtime enforcement, and
  actuation belong to the future controller/integration layer.

### Expected decisions

#### C1 above 25%

- Mode is `NORMAL`.
- Pump 1 is allowed if C1 is non-empty and Pump 1 is available.
- Pump 2 is independently allowed if C3 is configured available and Pump 2 is
  available.

#### C1 at or below 25%

- Mode is `SCARCITY`.
- Configured crop priorities are compared.

If Zone 2 has higher priority:

- a healthy Zone 1 path is deferred to conserve scarce C1 water;
- Pump 2 remains independently allowed only if C3 is available and Pump 2
  works;
- Pump 2 is not serving Zone 1.

If Zone 1 has higher priority, or priorities tie and Zone 1 wins the fixed
tie-break:

- Pump 1 may use remaining C1 water if C1 is greater than 0 and Pump 1 works;
- a healthy C3/Pump 2/Zone 2 path may remain independently allowed.

If C1 equals 0, Zone 1 is restricted regardless of priority. If C3 is
unavailable, Zone 2 is restricted. If a pump is unavailable, only its own path
is restricted. No cross-zone substitution exists.

### Interlock integration requirement

The allocator can return both pumps in `allowed_pumps`; this means both paths
are policy-eligible, not that both should run simultaneously. The verified
hardware policy permits only one running pump. The production controller must
schedule at most one actual request at a time and must preserve the firmware
interlock as an independent safety layer.

## 6. Isolated Task 4 Files

### Core policy/calibration/demo

| File | Purpose |
|---|---|
| `farm/allocation.py` | Immutable input/plan dataclasses and pure scarcity, priority, defer/restrict policy. Never actuates hardware. |
| `farm/task4_calibration.py` | Pure empirical C1 raw-ADC-to-percent conversion through 0/1700/2000 anchors. |
| `tests/test_allocation.py` | Hardware-free tests for the current API, safety refusal, priority, topology, deterministic behavior, and non-actuation. |
| `tests/test_task4_calibration.py` | Hardware-free anchor, interpolation, clamping, invalid-input, and determinism tests. |
| `tools/task4_demo.py` | Local terminal demo that calibrates raw C1 ADC, constructs the current allocation input, and displays the returned plan. |
| `tests/test_task4_demo.py` | Hardware-free checks for demo presets, rendered calibration, and empty pump requests. |

### Dual-pump bring-up artifacts

| File | Purpose/status |
|---|---|
| `firmware/task4_dual_pump_test/task4_dual_pump_test.ino` | Current isolated dual-pump sketch. Uses GPIO25 active-high and GPIO14 active-low, explicit pump IDs, boot OFF, 10-second cutoff, repeated-ON protection, and one-pump interlock. **Not production firmware.** |
| `tools/task4_pump_test.py` | Manual pyserial utility with Pump 1/2 ON/OFF, ALL OFF, explicit ON confirmation, status display, and exit cleanup. Does not import the controller or allocator. |
| `tests/test_task4_dual_pump_protocol.py` | Hardware-free tests for deterministic pump-ID JSON commands and ALL OFF encoding. It does not compile or physically test firmware. |
| `docs/task4/HARDWARE_BRINGUP.md` | Verified isolated bring-up guide for GPIO25 active-high Pump 1 and GPIO14 active-low Pump 2 on K1/IN1. K2/IN2 is unused; GPIO4 must not be used. |

The serial command format used by the isolated sketch/tool is:

```json
{"cmd":"pump","pump":1,"state":"on"}
{"cmd":"pump","pump":1,"state":"off"}
{"cmd":"pump","pump":2,"state":"on"}
{"cmd":"pump","pump":2,"state":"off"}
```

Production `farm/esp_link.py` still uses the original single-pump contract and
must not be assumed compatible merely because the isolated tool works.

## 7. Verification Status

The latest recorded local software verification completed with bytecode writes
disabled:

| Suite | Result |
|---|---:|
| Calibration tests | 13/13 passed |
| Allocation tests | 34/34 passed |
| Demo tests | 6/6 passed |
| Full repository unit-test discovery | 73/73 passed |

The full count also includes the isolated dual-pump protocol tests (10/10) and
the existing Task 1 ESP/controller tests. The existing controller fail-safe
test deliberately raises `RuntimeError("boom")`; its expected traceback is
logged and the test passes.

The software tests are hardware-free. They do not compile/flash the ESP32,
energize relays, run pumps, contact databases, start Flask, connect to MQTT, or
exercise sync. Physical facts in Section 2 come from the completed supervised
bring-up record supplied for this handoff, not from Python unit tests.

### Hardware documentation alignment

`docs/task4/HARDWARE_BRINGUP.md` has been corrected to the verified hardware:
Pump 1 uses GPIO25 active-high; Pump 2 uses GPIO14 active-low through K1/IN1;
and K2/IN2 is unused. Its remaining GPIO4 references are explicit warnings not
to use the former proposal.

## 8. Demo Behaviour

Run the software-only terminal demo from the repository root:

```bash
python tools/task4_demo.py
```

It provides presets plus interactive raw-ADC input and displays raw ADC,
calibrated C1 percentage, mode, prioritized zone, allowed pumps, deferred and
restricted zones, empty requested pumps, and a human-readable explanation.

### Recommended physical presentation

#### Normal

- C1 is above 25%.
- Zone 1 irrigation is eligible through Pump 1 when demand and controller
  safety permit it.

#### Water crisis

- C1 is at or below 25%.
- Configure Zone 2 with higher crop priority.
- Allocation detects scarcity.
- Zone 1 is deferred to conserve C1.
- The later demand/controller layer selects Pump 2 for Zone 2.
- Physical water path is C3 -> Pump 2 -> C4.

Suggested visual setup:

- tissue in C2 represents the Zone 1 crop/root area;
- tissue in C4 represents the Zone 2 crop/root area;
- label Zone 1 “low priority” and Zone 2 “high priority” for the main crisis
  demonstration.

The judge-facing message is:

> Scarcity triggers prioritisation; configured crop priority decides which
> crop is protected.

The demo is explanatory only. `requested_pumps` remains empty, so it never
commands real hardware.

## 9. Production Integration Still Required

The following work has **not** been implemented in the production system:

### Critical pump-watchdog integration warning

The canonical production firmware and the isolated Task 4 bring-up firmware
have deliberately different ON-command timing semantics:

- **Canonical production behavior:** the Raspberry Pi sends repeated
  `PUMP_ON` keepalives for Pump 1. Every `PUMP_ON` extends the firmware's
  10-second watchdog deadline. Pump 1 can therefore run for longer than 10
  seconds while healthy keepalives continue. If communication stops, the
  firmware turns the pump OFF within 10 seconds.
- **Isolated Task 4 bring-up behavior:** repeating an ON command for an
  already-running pump deliberately does **not** reset its timer. Each pump has
  an absolute 10-second maximum per activation. This stricter behavior was
  used for safe, supervised hardware verification only.

These semantics **must be reconciled explicitly** during final Task 1–4
production integration. Do not blindly copy the isolated dual-pump sketch over
the canonical production firmware. The final design must:

1. preserve all existing Task 1–3 sensor reporting and serial compatibility;
2. explicitly choose whether both pumps use either the existing
   keepalive/watchdog model or a controller-approved absolute-runtime model;
3. ensure the Raspberry Pi controller and ESP32 firmware implement the same
   selected timing contract;
4. preserve safe OFF behavior when Raspberry Pi communication fails; and
5. preserve the verified one-pump-at-a-time hardware interlock.

The selected model must be documented and tested for both pump IDs. Until that
decision is made, neither firmware's repeated-ON behavior should be assumed to
be the final two-pump production contract.

### Remaining integration work

1. Merge the isolated Task 4 modules into the newest Task 1–3 baseline.
2. Update the canonical ESP32 production firmware for:
   - Pump 1 on GPIO25, active-high;
   - Pump 2 on GPIO14, active-low, K1/IN1;
   - explicit pump IDs in commands and status;
   - both pumps OFF at boot;
   - the explicitly selected, controller-aligned watchdog/runtime contract;
   - communication-loss OFF protection;
   - one-pump-at-a-time interlock;
   - preservation of all existing sensor reporting.
3. Define a backward-compatible raw/calibrated GPIO33 reporting contract so
   the Pi can obtain raw ADC. Do not feed the current `raw / 4095 * 100`
   pseudo-percentage into the empirical raw-ADC calibrator.
4. Update `farm/esp_link.py` for two independent pump IDs, statuses, timers,
   and interlock/status reasons while preserving single serial-port ownership.
5. Integrate `calibrate_c1_water_percent()` into the runtime sensor/controller
   boundary and provide trustworthy C1 valid/fresh flags.
6. Update `farm/control.py` to construct `AllocationInput`, call
   `plan_allocation()`, combine allowed paths with actual irrigation demand,
   and schedule at most one pump at a time.
7. Supply configured positive-integer crop priorities.
8. Supply the operator/configured `container_3_available` Boolean without
   inventing a C3 percentage.
9. Add logging/persistence for allocation inputs, results, reasons, actual
   requests, interlock actions, and outcomes if required.
10. Update Flask routes/API contracts as narrowly as needed.
11. Update the dashboard **last**, after controller and persistence contracts
    are stable.

Safety precedence must be explicit: invalid/stale C1 data, empty source,
unavailable source/pump, maximum runtime, rest rules, all-stop behavior, and
the one-pump interlock must override ordinary irrigation demand.

## 10. Dashboard Recommendation

After backend integration is complete, display:

- calibrated C1 water percentage;
- `LOW WATER` / `NORMAL` source state;
- C3 source `AVAILABLE` / `UNAVAILABLE`;
- Zone 1 configured priority;
- Zone 2 configured priority;
- allocation mode: `NORMAL`, `SCARCITY`, or `SAFETY_REFUSAL`;
- prioritized zone;
- Pump 1 actual state;
- Pump 2 actual state;
- deferred zone(s);
- restricted zone(s);
- human-readable allocation/controller explanation.

The dashboard must display results produced by the controller/allocation
layers. Do **not** reimplement scarcity, priority, defer/restrict, calibration,
or interlock policy in Jinja or browser JavaScript.

Clearly distinguish `allowed` from `requested` and from actual relay state. An
allowed pump is not necessarily running.

## 11. Merge Safety

Do **not** copy the old Task 1 production files wholesale over Task 2/3 work.

Recommended procedure:

```text
latest Task 1–3 baseline
    +
isolated Task 4 files
    ->
re-run all tests
    ->
audit current controller / validation / serial / firmware interfaces
    ->
perform narrow Challenge 4 integration
    ->
perform supervised end-to-end verification
```

Likely shared/conflict-prone files:

- `farm/control.py`
- `farm/config.py`
- `farm/esp_link.py`
- `farm/app.py`
- `farm/templates/dashboard.html`
- canonical ESP32 production firmware

Avoid unnecessarily modifying or reverting:

- Task 2 validation/MQTT work;
- Task 3 sync/offline work;
- database schemas or contracts unrelated to the agreed allocation audit;
- existing sensor behavior that does not require a narrow unit-contract fix.

Before editing shared files, inspect the newest versions rather than relying on
the old Task 1 handoff or this repository’s older production snapshot.

## 12. Final Integration Acceptance Checklist

- [ ] Latest Task 1–3 baseline is the integration base.
- [ ] C1 raw ADC enters the runtime calibration boundary with explicit units.
- [ ] Calibration maps ADC 1700 to exactly 25%.
- [ ] C1 at or below 25% enters scarcity mode.
- [ ] C3 availability is handled as a Boolean without a fake percentage.
- [ ] Zone 1 and Zone 2 crop priorities are visible and configurable.
- [ ] Equal priorities deterministically select Zone 1.
- [ ] Soil moisture does not affect Challenge 4 allocation.
- [ ] Pump 1 production command/status works with GPIO25 active-high.
- [ ] Pump 2 production command/status works with GPIO14 active-low via K1/IN1.
- [ ] K2/IN2 remains unused.
- [ ] Both production relay outputs boot OFF.
- [ ] A single production timing contract—keepalive watchdog or approved
      absolute runtime—is explicitly selected for both pumps.
- [ ] Raspberry Pi controller and ESP32 firmware agree on repeated-ON and
      timeout semantics for both pump IDs.
- [ ] Communication loss causes safe pump OFF within the selected safety
      deadline (no longer than the existing 10-second watchdog protection).
- [ ] One-pump-at-a-time interlock works in production.
- [ ] Controller schedules no simultaneous pump requests.
- [ ] C1 empty prevents Pump 1.
- [ ] C3 unavailable prevents Pump 2.
- [ ] No cross-zone substitution exists in decisions, commands, or plumbing.
- [ ] Dashboard reflects actual allocation and controller decisions.
- [ ] Dashboard does not contain policy logic.
- [ ] Task 1–3 tests still pass.
- [ ] Challenge 4 calibration, allocation, demo, and protocol tests still pass.
- [ ] Full merged repository test suite passes.
- [ ] Supervised end-to-end physical test passes on the merged production build.
- [x] GPIO4 proposal removed from bring-up instructions; remaining mentions
      are explicit do-not-use warnings.

Until every applicable item is checked, the isolated Task 4 work should remain
separate from production operation.
