# Foundation status board

Last updated: Sat 19 Sep, 12:02

## Done

- [x] Pi boots, on the network
      wlan0 = 192.168.200.20  (the static IP the brief requires)
      eth0  = 192.168.50.20   (CAT6 to laptop at 192.168.50.10)
- [x] SSH route confirmed available: `ssh hgroup10@192.168.50.20`
- [x] All Foundation code written (on the LAPTOP, not yet on the Pi)
      farm/sensors.py    RS485 probe read
      farm/actuator.py   relay + button
      farm/control.py    poll -> store -> decide -> act -> log
      farm/app.py        dashboard + manual pump routes
      farm/db/schema_local.sql
      tools/sensor_scan.py
- [x] Automation flowchart (docs/flowchart.svg + .png) - submission item
- [ ] ERD started by teammate (docs/erd.mmd) - for Task 1, not Foundation

## Not done

- [ ] Code copied to the Pi
- [ ] Python packages installed on the Pi
- [ ] Database created
- [ ] Sensor read even once
- [ ] Relay tested
- [ ] Dashboard ever run
- [ ] Dashboard screenshot (submission item)
- [ ] SVN checked out, nothing committed

## Foundation objectives - honest state

| # | Objective | State |
|---|-----------|-------|
| 1 | 3 sensors, poll every 1 min | code written, never run |
| 2 | Dashboard exists | code written, never run |
| 3 | Irrigation control, >=1 pump | code written, never tested |
| 4 | Automation logic | code + flowchart done, never run |
| 5 | Min database requirement | schema written, DB not created |

Nothing is proven until it runs on the Pi. Code on a laptop scores zero.

## Open questions

1. Probe register map - unknown until sensor_scan.py runs
2. Is 192.168.200.20 static, or did DHCP happen to hand it to us?
3. How do we reach central at 192.168.98.50? Neither of our subnets match
4. Does svn.home resolve? Need it before we can submit

## Current step

STEP 1 - confirm SSH works and see the Pi's real network state.
