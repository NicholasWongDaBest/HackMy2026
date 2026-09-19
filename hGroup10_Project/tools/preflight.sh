#!/usr/bin/env bash
# Run this on the Pi FIRST. Answers "can we even reach central?" before
# anyone wastes an hour debugging Python.
set -u
CENTRAL="${CENTRAL_HOST:-192.168.98.50}"
echo "=== interfaces / routing ==="; ip -brief addr; ip route
echo; echo "=== ping central ($CENTRAL) ==="
ping -c 3 -W 2 "$CENTRAL" || echo "!! NO ROUTE TO CENTRAL -- this is a network problem, not a code problem"
echo; echo "=== MySQL port 3306 ==="
timeout 4 bash -c "</dev/tcp/$CENTRAL/3306" 2>/dev/null && echo "3306 open" || echo "3306 unreachable"
echo; echo "=== MQTT port 1883 ==="
timeout 4 bash -c "</dev/tcp/$CENTRAL/1883" 2>/dev/null && echo "1883 open" || echo "1883 unreachable"
echo; echo "=== central tables ==="
mysql -h "$CENTRAL" -u hGroup10 -pteamGroup10 hackathonGroup10 \
  -e "SHOW TABLES;" 2>&1 | head -30
echo; echo "=== listening on broadcast for 10s ==="
timeout 10 mosquitto_sub -h "$CENTRAL" -p 1883 -t 'hackathon/broadcast' -v || true
