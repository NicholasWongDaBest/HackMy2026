# Foundation bring-up runbook

Run top to bottom on the Pi. Each step has a check; do not move on until
it passes. Total time if nothing fights back: ~25 minutes.

## 0. Get the code onto the Pi

From the laptop:
```
scp -r farm tools requirements.txt DEPLOY.md hgroup10@192.168.200.20:~/farm-project/
```
Or check out the SVN working copy on the Pi and copy into it (preferred —
see step 7).

## 1. Packages

Needs internet on the Pi's **WiFi** interface (Ethernet stays on the
static 192.168.200.20 the brief requires).

```
sudo apt update
sudo apt install -y mariadb-server python3-pip python3-venv mosquitto-clients subversion
pip3 install --break-system-packages -r requirements.txt
```
Check: `python3 -c "import pymodbus, gpiozero, flask, mysql.connector; print('ok')"`

## 2. Database

```
sudo mysql -e "CREATE USER IF NOT EXISTS 'farm'@'localhost' IDENTIFIED BY 'farm';
               GRANT ALL ON farm_local.* TO 'farm'@'localhost'; FLUSH PRIVILEGES;"
sudo mysql < farm/db/schema_local.sql
```
Check: `mysql -u farm -pfarm farm_local -e "SHOW TABLES; DESCRIBE sensor_data;"`
You should see sensor_data, selfcare_message, rejected_messages, sync_log,
automation_log and the `sensor` view.

## 3. Find the sensor

```
ls /dev/ttyUSB*                       # expect /dev/ttyUSB0
sudo usermod -aG dialout $USER        # then log out and back in
python3 tools/sensor_scan.py /dev/ttyUSB0 9600
```
Read the dump. Identify which register looks like moisture (0-100 after
/10), temperature (~20-35 after /10) and EC (hundreds to low thousands).

**Then correct `SENSOR_REGISTERS` in farm/config.py to match.** If nothing
answers, try baud 4800 and 19200 before suspecting the probe.

Check: `python3 -m farm.sensors` prints three plausible numbers.

## 4. Relay self-test — no water yet

```
python3 -m farm.actuator
```
You should hear each relay click on for 1.5 s. If a relay clicks
*inverted* (energised at rest), set `RELAY_ACTIVE_HIGH=1` in the
environment.

**Only put the pump in water once this passes.**

## 5. Run it

```
python3 -m farm.app
```
Open `http://192.168.200.20:5000` from the laptop.

Check, in order:
- three live sensor tiles showing real numbers
- "Pump 1" card says STOPPED
- press **Pump ON** — relay clicks, pump runs, card flips to RUNNING
- wait 30 s — safety cutoff stops it on its own, automation log shows
  `pump_off / safety / max runtime 30s exceeded`
- press the physical button — pump toggles
- dry the probe (lift it out of the soil) and wait one tick — automation
  log shows `pump_on / auto / moisture N% below threshold 30%`

That last bullet is the demo. It is the difference between "automation
exists" and "we can show you why it fired".

## 6. Run as services (so it survives a closed laptop)

```
sudo tee /etc/systemd/system/farm-app.service << 'UNIT'
[Unit]
Description=Farm dashboard and control loop
After=network.target mariadb.service
[Service]
User=hgroup10
WorkingDirectory=/home/hgroup10/farm-project
ExecStart=/usr/bin/python3 -m farm.app
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable --now farm-app
```
Check: `systemctl status farm-app` is active, and the dashboard survives
`sudo reboot`.

## 7. Submit

```
svn checkout http://svn.home/svnrepo/hGroup10_Project/trunk ~/farm-project --username hGroup10
# screenshot the dashboard from the laptop, scp it to docs/screenshot.png
svn add --force farm tools docs requirements.txt DEPLOY.md
svn commit -m "Foundation : Completed" --username hGroup10
```

If `svn.home` does not resolve, get the IP from a judge and add it to
`/etc/hosts`. Do this **early** — not at hour 5:50.

## Objective coverage

| Brief requirement | Where |
|---|---|
| 3 sensors, poll every 1 min | `farm/sensors.py`, `POLL_INTERVAL_S=60` |
| Dashboard exists | `farm/app.py` + `templates/dashboard.html` |
| Irrigation control, >=1 pump | `farm/actuator.py`, web + physical button |
| Automation logic | `farm/control.py` `decide()`, logged to automation_log |
| Min database requirement | `farm/db/schema_local.sql` sensor_data |
| Flowchart | `docs/flowchart.svg` / `.png` |
| Screenshot | `docs/screenshot.png` (take at step 5) |
