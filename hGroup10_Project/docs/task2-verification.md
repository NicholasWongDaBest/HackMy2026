# Task 2: Central data guard

Status: base implementation and suffix correction are confirmed by user-provided Pi logs. The user reports the challenge now works. The new comparison/report view below is tested locally; its Pi deployment and the actual malicious-data submission screenshot are pending. Judge completion is not certified by this code change.
Task5 is paused; its controller, sensor-health logic, serial driver and firmware are unchanged.

## Current action: deploy the comparison graph

This is the only section needed for the latest graph update. There is no new package to install, no need to resend the challenge trigger, and no need to repeat the full test suite on the Pi.

What is displayed:

- Main graph: green in-range local measurements from `sensor_data` versus red rejected Central observations from `central_changes`, with a shared linear value/time scale. Red timestamps are when the Pi observed the row, not a fabricated server injection time.
- Stable-value detail: the same local samples on a separately labeled zoomed value scale, so an extreme value such as 999 does not hide the normal variation. No generated baselines, filled-forward readings or fake attack values.
- Correct sensor units and extra charts for known rejected sensor types (e.g. air temperature). Different local sensor positions are not joined into one series. A missing baseline stays empty, and the last local measurement time is printed so old history cannot be mistaken for a current measurement.
- Last 12 recorded rejection events show Central IDs, original values, positions and reasons even if later good uploads displace the row or the judge corrects it. Unknown/non-numeric/unplottable values stay in the table; they are not guessed onto a temperature axis. Earlier false-rejection audit records are retained, not silently erased.
- `/task2/report` is a read-only snapshot with no pump controls, auto-refresh or automatic challenge request. It offers a print/save-PDF button; the submission requirement remains a screenshot of the real comparison.

Keep `farm.sync` running. With pump power disconnected, stop only the dashboard (`farm.app`) in its original terminal using Ctrl+C. Back up the existing display files before replacing them. Do not copy the full project or replace config, sync, parser, controls or firmware.

In **Windows PowerShell, not SSH**:

```powershell
cd C:\Users\Yao\Downloads\HackMy2026\hGroup10_Project
$pi = "hgroup10@192.168.200.20:/home/hgroup10/hackathon/hGroup10_Project"
scp farm/anomaly_chart.py farm/database.py farm/app.py "${pi}/farm/"
scp farm/templates/dashboard.html farm/templates/task2_charts.html farm/templates/task2_report.html "${pi}/farm/templates/"
scp farm/static/dashboard.css "${pi}/farm/static/"
```

In the **same configured Pi terminal that was running the dashboard**:

```bash
cd /home/hgroup10/hackathon/hGroup10_Project
python3 -m farm.app
```

This is the existing app startup and still starts the normal controller; isolate physical pump power during software verification. Do not launch a second app instance, and do not change its working RS485/ESP environment settings.

Open `http://192.168.200.20:5000/task2/report` or click **Open submission graph** in the dashboard's Task2 panel. Hard-refresh once for the new CSS. Use **Refresh snapshot** to include new observations; the standalone view intentionally stays still while taking a screenshot. On Windows use Win+Shift+S for the visible comparison, or the browser's full-page screenshot if you also need the evidence table. Include team name, legend, local baseline, actual rejected values and their reasons; capture separate sensor charts if needed for readable text. A corrected Central row may show zero current rejections while its genuine historical red points remain.

Only the screenshot from the live Pi counts as submission evidence. Test fixtures/screenshots are not judge data. If rejected rows have an unknown type, obtain the judge's confirmed type mapping instead of fabricating a temperature/moisture plot.

Local checks: 82 Python tests, 11 browser scenarios, syntax across 22 maintained Python files and Git whitespace checks pass. The offline fixture graphs were visually inspected. Runtime files changed: `farm/anomaly_chart.py`, `farm/database.py`, `farm/app.py`, `farm/static/dashboard.css`, `farm/templates/dashboard.html`, `farm/templates/task2_charts.html`, `farm/templates/task2_report.html`. Tests and both READ trackers were also updated. No worker/controller/firmware changes or new dependencies.

## Earlier follow-up: valid types with a trailing suffix (already verified on Pi)

The supplied Pi run passed 72 tests and accepted IDs 150-154 after the fix; it revalidated 404 rows with no rejections and then reported 404 unchanged. A later dashboard screenshot showed 604 accepted / zero rejected. The steps in this older section are retained for reference, not a request to redeploy/retest the suffix fix now.

The user's Pi query returned IDs 150-154 with in-range rainfall, water-level, light, humidity and air-temperature values, but positions such as `zone-2-canopy/humidity#L3283`. The previous parser treated `humidity#L3283` as the entire sensor type. These five were parser false rejections, not evidence of a malicious value; the other 27 rejection reasons and the suffix producer remain unconfirmed.

The fix recognizes only the exact trailing `#L` plus ASCII digits on the type in `zone/type`. It does not guess the type of a bare `zone-9`, ignore arbitrary suffixes, or bypass numeric/range/conflicting-type checks. Raw positions/values remain unchanged in the audit. Validator revision 2 rechecks saved rows once even if Central has not changed them. Current Task2 counts should reflect corrected verdicts; old entries in the historical rejection log remain deliberately. The first upgraded scan can report changes for all rows because the validation policy changed; the next identical scan should report them as unchanged.

Deploy this follow-up only (do not replace a teammate's sync/config code):

1. In the Pi terminal running `python3 -m farm.sync`, press Ctrl+C and wait for it to stop. Leave the dashboard running and keep pump power disconnected during software verification. Back up the existing parser and test in this Pi shell:

   ```bash
   cd /home/hgroup10/hackathon/hGroup10_Project
   cp -p --backup=numbered farm/central_pull.py farm/central_pull.py.before-suffix-fix
   cp -p --backup=numbered tests/test_central_pull.py tests/test_central_pull.py.before-suffix-fix
   ```

2. In a Windows PowerShell window (not inside SSH):

   ```powershell
   cd C:\Users\Yao\Downloads\HackMy2026\hGroup10_Project
   scp farm/central_pull.py hgroup10@192.168.200.20:/home/hgroup10/hackathon/hGroup10_Project/farm/central_pull.py
   scp tests/test_central_pull.py hgroup10@192.168.200.20:/home/hgroup10/hackathon/hGroup10_Project/tests/test_central_pull.py
   ```

3. Back in that Pi sync terminal:

   ```bash
   cd /home/hgroup10/hackathon/hGroup10_Project
   python3 -m unittest discover -s tests -v
   ```

   Expect 72 tests and `OK` for this version. If tests fail, share the failure before restarting. Otherwise run:

   ```bash
   python3 -m farm.sync
   ```

Send the first two scan summaries and any remaining rejection reasons. The five supplied rows should now be accepted if their values/configuration are unchanged. Do not promise zero remaining rejections without inspecting the other rows. No dashboard restart or new dependencies are required. Do not send a challenge trigger until this check is understood.

## Why the old implementation missed the judge's changes

- `farm.sync` uploaded only; there was no Central-to-dashboard path in the active runtime.
- `app.sync` and `farm_pull.py` looked only above a saved ID. An UPDATE to an existing ID was invisible.
- The standalone script accepted unknown types when no range rule existed. It could also advance the ID mark without processing rows.
- The standalone rejection writer looked for `source`/`payload` rather than the actual `topic`/`raw_excerpt`/`payload_len` schema.
- Separate packages and workers made it unclear which implementation was actually running.

## New behavior

Run one `python3 -m farm.sync` worker. Upload format is unchanged. Each cycle also streams **all Central IDs** in batches of 200, including IDs already seen. There is no persistent high-water mark.

Three additive local InnoDB tables (`central_rows`, `central_changes`, `central_pull_status`) retain the latest observed row states, changed-value history, and scan status. SHA-256 fingerprints include row content and validation rules. Repeated unchanged scans/restarts do not produce repeated rejection events; an old ID changing to 999, then 25, then 999 produces three genuine changes. Ledger/history/rejection inserts are committed in the same local transaction. A per-source database advisory lock prevents overlapping pull scans. Leave only one combined worker running; this does not redesign Task3's existing upload/idempotency behavior.

Central is read-only on the pull path. Accepted and rejected Central observations are displayed separately and **never inserted into `sensor_data`, uploaded back, or passed to irrigation**. This preserves recorded local readings rather than allowing judge edits to rewrite the real sensor history. Rejection evidence is retained; it is discarded from the trusted measurement/control path, not erased from the audit log.

Supported Central fields: `id`, `sensor_position`, `sensor_value`, `created_at`, plus optional `sensor_type`. Type comes from `zone/type` (including the observed `zone/type#L123` format), a known bare type, the explicit column, or a confirmed position mapping. Conflicting or unknown types, booleans, non-numeric/non-finite values and out-of-range values are rejected. A bare `zone-9` is not assumed to mean temperature: 999 is valid for some EC sensors, so guessing would be incorrect.

Only after the judge confirms the meaning, an optional mapping can be supplied in the worker's shell, for example:

```bash
export CENTRAL_POSITION_TYPES='{"zone-9":"temperature"}'
```

Do not use that example to guess the meaning of your judge's actual rows. Configuration/credentials in the existing `farm/config.py` remain unchanged.

The dashboard's **Task 2 - Central data guard** section shows scan freshness, counts, recent observed row IDs/values/verdicts, and temperature/moisture comparison graphs. Green is in-range local history; red is rejected Central data at its local observation time. Unknown types are shown in the table, not mislabeled on a temperature axis. Empty graphs stay empty, without fake values. Deleted Central rows remain as last-observed audit evidence; this monitor is not a destructive replica. Changes made and reverted entirely between scans cannot be detected without a Central change log.

`app.sync` and `farm_pull.py` now delegate to the same maintained implementation. The active dashboard remains `farm.app`, not `app.app`.

## Deploy only the Task2 files

First stop the existing sync worker in its terminal with Ctrl+C (or stop its known service). Do not leave old `app.sync` or `farm_pull.py` loops running. Back up the affected Pi files before replacing them. Do not copy the entire repo, `.venv`, `.svn`, credentials, or firmware.

From **Windows PowerShell**:

```powershell
cd C:\Users\Yao\Downloads\HackMy2026\hGroup10_Project
$pi = "hgroup10@192.168.200.20:/home/hgroup10/hackathon/hGroup10_Project"
scp farm/sync.py farm/central_pull.py farm/anomaly_chart.py farm/challenge2.py farm/database.py farm/app.py "${pi}/farm/"
scp farm/templates/dashboard.html farm/templates/dashboard_updates.html "${pi}/farm/templates/"
scp farm/static/dashboard.css "${pi}/farm/static/"
scp app/sync.py "${pi}/app/"
scp farm_pull.py READ.md "${pi}/"
scp tests/test_central_pull.py tests/test_dashboard.py "${pi}/tests/"
scp docs/task2-verification.md "${pi}/docs/"
```

No new packages are required on the Pi. The existing no-refresh `farm/static/dashboard.js` must already be deployed; if not, also copy it into the Pi's `farm/static/` directory.

On the **Pi**, from the correct directory:

```bash
cd /home/hgroup10/hackathon/hGroup10_Project
python3 -m unittest discover -s tests -v
python3 -m farm.sync --inspect-central
python3 -m farm.sync --pull-only --once
```

Inspection prints real column names and the latest five rows (selected sensor fields only), without database writes or credentials. If the schema differs, share this output instead of assuming what a position means. The one-shot pull creates only the additive local ledger tables, validates the actual data, and exits nonzero on failure. It does not upload or operate hardware.

After a successful one-shot check, run one combined worker and leave it running:

```bash
python3 -m farm.sync
```

Restart the **existing** `farm.app` dashboard process in its original configured shell, not a second copy. It still starts the normal irrigation controller; keep pump power disconnected during Task2 software verification. Open `http://192.168.200.20:5000`, hard-refresh once, then click **Task 2**. Subsequent values update in place; the page should not keep reloading. Read-only monitor JSON is available at `/api/challenge2`.

## Start the judge challenge when ready

In another Pi terminal:

```bash
cd /home/hgroup10/hackathon/hGroup10_Project
python3 -m farm.challenge2
python3 -m farm.challenge2 --start
```

The first command previews only. The second explicitly publishes once with QoS 1, not retained, to `hackathon/hGroup10/Challenge2`:

```json
{"type":"start_challenge","message":"Please start Challenge 2"}
```

The request matches `Phase/Task2.pdf`. A broker acknowledgment proves message delivery, **not that the challenge passed**. Check the worker and dashboard for actual judge-injected rows.

## Evidence to collect

1. Capture a complete scan log and actual Central row shape. `scanned=...` must be nonzero if the judge has rows; `unchanged=...` means previously observed rows were checked again, not that pull is missing.
2. Ask the judge to modify an existing typed row to an impossible value. Confirm the same ID appears as rejected, the graph/log records it, and the local readings/control are not replaced by it. A correction to an in-range value should become accepted on a subsequent scan. Do not run invented SQL against the judge's database.
3. Leave it running through multiple cycles and restart the worker once; the same unchanged invalid row must not multiply rejections. Capture the required **real** stable-versus-malicious graph screenshot. Submit the required SVN `Challenge2 : Completed` commit only after real acceptance evidence. Local simulated screenshots/tests are not challenge evidence.

## Local checks and limits

Current suffix correction: 72 Python tests, syntax checks for the two changed Python files, and Git whitespace checks pass. Task1 MQTT and existing Task5 regressions remain passing. The earlier implementation also passed 10 browser scenarios and 37-file syntax checks; those browser checks were not rerun for this parser-only fix. The simulated UI was previously visually inspected; no fake runtime sensor values or pass messages were introduced.

The regression suite uses fake hardware and in-memory SQLite with a narrow MySQL SQL adapter; it tests the actual scan, transaction, dashboard-read and upload paths without contacting Central. Browser checks intercept every request. They do not establish MariaDB compatibility, Pi performance, or judge acceptance. The supplied Pi output separately records 66 earlier tests passing, successful repeated live scans and the dashboard at 159 rows (127 accepted/32 rejected). The suffix patch, remaining rejection reasons and actual judge challenge still require live verification; no new direct SSH or service test was performed for this patch.
