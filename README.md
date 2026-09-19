# HackMy2026 - Save the Farm (hGroup10)

Edge irrigation system: Raspberry Pi reads sensors, buffers locally,
syncs to Farm Central, and refuses to be fooled by what it receives.

## Layout

    farm/config.py        credentials + tunables (env-overridable)
    farm/esp_link.py      sole ESP32 serial owner: readings in, pump commands out
    farm/validation.py    every input gate; nothing reaches the DB unvalidated
    farm/database.py      all SQL, fully parameterised
    farm/mqtt_client.py   subscriber + self-verification + Challenge3 ACK
    farm/sync.py          Pi -> central sync worker (survives LAN / WiFi loss)
    farm/app.py           Flask dashboard (works offline on the Pi)
    farm/db/*.sql         local + central schema + Challenge3 migration
    tools/preflight.sh    connectivity check -- RUN THIS FIRST
    tools/attack_test.py  fires hostile payloads at our own validator
    tools/challenge3_*.py Alien Attack trigger + self-test
    docs/                 ERD, flowchart, dashboard screenshot (submissions)
    CHALLENGE3.md         Alien Attack runbook

## Setup (blank Pi)

    sudo apt update
    sudo apt install -y mariadb-server python3-pip mosquitto-clients
    pip3 install -r requirements.txt

    sudo mysql < farm/db/schema_local.sql
    sudo mysql -e "CREATE USER IF NOT EXISTS 'farm'@'localhost' IDENTIFIED BY 'farm';
                   GRANT ALL ON farm_local.* TO 'farm'@'localhost';
                   FLUSH PRIVILEGES;"

    export TEAM_NAME=hGroup10     # CONFIRM THE EXACT STRING WITH A JUDGE

## Run

    bash tools/preflight.sh          # can we even reach central?
    python3 -m farm.mqtt_client      # terminal 1
    python3 -m farm.sync             # terminal 2
    export NODE_SERIAL_PORT=/dev/serial/by-id/<esp32-id>
    python3 -m farm.app              # terminal 3 -> http://<pi-ip>:5000

Do not run `farm.node_serial` beside `farm.app`; the app owns the same
bidirectional ESP32 serial connection. A Linux lock rejects accidental
second owners.

## Prove it can't be fooled

    python3 tools/attack_test.py          # offline, 18 cases
    python3 tools/attack_test.py --mqtt   # publish live, watch the dashboard

Every hostile payload must be REJECTED with a reason. The two SQL/unicode
cases are ACCEPTED on purpose: they are inert text, defeated by
parameterised queries and escaped rendering, not by keyword blacklists.

## Challenge 3 — Alien Attack

When WiFi is cut after the Challenge3 MQTT trigger, the farm must keep
running on the edge and auto-sync every buffered reading when the link
returns. Full runbook: [CHALLENGE3.md](CHALLENGE3.md).

    python3 tools/challenge3_selftest.py  # payload + idempotency checks
    python3 tools/challenge3_trigger.py   # publish start_challenge (while online)

Required processes on the Pi: `farm.mqtt_client`, `farm.sync`, `farm.app`.

## Validation gates

Size cap -> UTF-8 decode -> JSON parse -> schema and types -> physical
range -> timestamp sanity -> control-character and markup rejection.
Rendering escapes independently (Jinja autoescape), so display safety
does not depend on the validator being perfect.

## Task 1 submission checklist

- [ ] ERD              docs/erd.mmd -> render to docs/erd.png
- [ ] Dashboard screenshot showing the selfcare message -> docs/screenshot/
- [ ] Automation flowchart -> docs/flowchart/
- [ ] `svn commit --username hGroup10 -m "Challenge1 : Completed"`

## Challenge 3 submission checklist

- [ ] Edge irrigation + local logging while WiFi is blocked
- [ ] Buffered readings auto-sync to central with no gaps / duplicates
- [ ] Offline dashboard reachable (Ethernet or localhost on the Pi)
- [ ] `svn commit --username hGroup10 -m "Challenge3 : Completed"`

## Open questions for the judges

1. Exact `{teamName}` string for `hackathon/{teamName}/test` and `/verify`.
2. Task1.pdf says table `sensor` (`sensor_values`, `created_at`);
   Setup.pdf says `sensor_data` (`sensor_position`, `sensor_value`, ...).
   We build `sensor_data` and expose a `sensor` view covering both.
3. Pi is specified as 192.168.200.20, central as 192.168.98.50 -- different
   subnets. Confirm routing exists between them.
