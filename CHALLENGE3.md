# Challenge 3 — Alien Attack

The network drops. The farm cannot stop.

When judges publish `start_challenge` on MQTT, a script blocks WiFi. The Pi
must keep irrigating, logging, and serving the dashboard locally, then restore
every buffered reading to central with **no gaps and no duplicates**.

## MQTT trigger

| | |
|---|---|
| Host | `192.168.98.50` |
| Port | `1883` |
| Topic | `hackathon/{TEAM_NAME}/Challenge3` |
| Payload (brief) | `{type:start_challenge;message:"Please start Challenge 3"}` |

Publish it yourself (while still online):

```bash
python3 tools/challenge3_trigger.py
```

## What the code does

1. `farm/mqtt_client.py` subscribes to Challenge3, validates the payload,
   records it in `challenge_events`, and ACKs on the same topic.
2. Sensors + control + Flask dashboard never needed central — they keep
   running on the Pi (use Ethernet `192.168.50.20:5000` if WiFi is dead).
3. Readings land in local `sensor_data` with `synced=0`.
4. `farm/sync.py` retries every `SYNC_INTERVAL_S` seconds. When central
   returns it drains the backlog automatically (**bonus: auto sync**).
5. Each row is pushed with key `position/type#L{local_id}` so a retry after
   a partial failure cannot insert duplicates.

## Run on the Pi (before the cut)

```bash
# one-time if the DB predates this challenge
sudo mysql < farm/db/migrate_challenge3.sql

export TEAM_NAME=hGroup10   # confirm with a judge
bash tools/preflight.sh

python3 -m farm.mqtt_client   # terminal 1
python3 -m farm.sync          # terminal 2
python3 -m farm.app           # terminal 3
```

Self-check without the live broker:

```bash
python3 tools/challenge3_selftest.py
```

## Prove it to a judge

1. Dashboard shows live sensors and pump control.
2. Trigger Challenge3 (or wait for judges).
3. WiFi dies — chip shows **Edge offline · buffering**; irrigation still works.
4. Open dashboard via Ethernet / localhost.
5. WiFi returns — pending count drains; central has every blackout reading once.
6. SVN:

```bash
svn commit -m "Challenge3 : Completed" --username hGroup10
```

## Objectives map

| Objective | Where |
|---|---|
| Core irrigation without internet | `farm/control.py` + `farm/app.py` (local only) |
| Local logging | `farm/database.py` → `sensor_data` |
| Buffer, no loss / no duplicates | `synced` flag + `#L{id}` keys in `farm/sync.py` |
| Offline dashboard | Flask on `0.0.0.0:5000` |
| Bonus auto sync | `farm/sync.py` loop |
