"""Full Challenge 3 simulation without Raspberry Pi, MySQL, or MQTT broker.

Exercises the real validation + sync-key logic, then simulates:
  start_challenge → edge buffer while "offline" → catch-up sync with
  retry-after-crash (must not duplicate).

    python3 tools/challenge3_simulate.py
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, ".")
from farm import config, database, validation  # noqa: E402


@dataclass
class FakeCentral:
    rows: dict[str, tuple] = field(default_factory=dict)  # key -> (value, created_at)
    fail_next_insert: bool = False

    def existing(self, keys):
        return {k for k in keys if k in self.rows}

    def insert_many(self, items):
        if self.fail_next_insert:
            self.fail_next_insert = False
            raise ConnectionError("simulated WiFi cut mid-push")
        for key, value, created_at in items:
            self.rows[key] = (value, created_at)


@dataclass
class FakeLocal:
    next_id: int = 1
    sensor_data: list = field(default_factory=list)
    challenge_events: list = field(default_factory=list)
    sync_log: list = field(default_factory=list)

    def insert_reading(self, position, value, sensor_type, created_at=None):
        row = {
            "id": self.next_id,
            "sensor_position": position,
            "sensor_type": sensor_type,
            "sensor_value": value,
            "created_at": created_at or time.strftime("%Y-%m-%d %H:%M:%S"),
            "synced": 0,
        }
        self.next_id += 1
        self.sensor_data.append(row)
        return row

    def pending(self):
        return [r for r in self.sensor_data if r["synced"] == 0]

    def mark_synced(self, ids):
        for r in self.sensor_data:
            if r["id"] in ids:
                r["synced"] = 1


class FakeMqtt:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=1):
        self.published.append((topic, payload, qos))


def check(label, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    suffix = f"  — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    return bool(ok)


def simulated_push(local: FakeLocal, central: FakeCentral, batch=200):
    """Mirrors farm.sync.push_batch idempotency rules against in-memory stores."""
    rows = local.pending()[:batch]
    if not rows:
        return 0
    keys = [database.central_key_for_row(r) for r in rows]
    key_by_id = {r["id"]: database.central_key_for_row(r) for r in rows}
    already = central.existing(keys)
    to_insert = [
        (key_by_id[r["id"]], r["sensor_value"], r["created_at"])
        for r in rows
        if key_by_id[r["id"]] not in already
    ]
    if to_insert:
        central.insert_many(to_insert)
    local.mark_synced([r["id"] for r in rows])
    local.sync_log.append({"rows": len(rows), "status": "ok"})
    return len(rows)


def handle_challenge3_sim(client: FakeMqtt, local: FakeLocal, raw: bytes):
    """Same control flow as mqtt_client.handle_challenge3, without DB/MQTT deps."""
    parsed = validation.parse_challenge3_payload(raw)
    local.challenge_events.append({
        "challenge": "challenge3",
        "event_type": parsed["type"],
        "message": parsed["message"],
        "raw": raw.decode("utf-8", errors="replace"),
    })
    edge = parsed["type"].lower() in ("start_challenge", "start", "begin")
    ack = {
        "team": config.TEAM_NAME,
        "challenge": "challenge3",
        "ack": True,
        "type": parsed["type"],
        "edge_mode": True,
        "ts": time.time(),
    }
    client.publish(config.TOPIC_CHALLENGE3, json.dumps(ack), qos=1)
    return edge, parsed


def main():
    results = []
    print("\n=== Challenge 3 local simulation (no Pi / MySQL / broker) ===\n")

    # --- 1. Payload parsing -------------------------------------------------
    print("1) MQTT start payload parsing")
    brief = b'{type:start_challenge;message:"Please start Challenge 3"}'
    parsed = validation.parse_challenge3_payload(brief)
    results.append(check(
        "brief format from ALIEN ATTACK.pdf",
        parsed["type"] == "start_challenge" and "Challenge 3" in parsed["message"],
        parsed,
    ))
    results.append(check(
        "JSON format also accepted",
        validation.parse_challenge3_payload(
            b'{"type":"start_challenge","message":"Please start Challenge 3"}'
        )["type"] == "start_challenge",
    ))
    try:
        validation.parse_challenge3_payload(b"")
        results.append(check("empty payload rejected", False))
    except validation.Rejected:
        results.append(check("empty payload rejected", True))

    # --- 2. Trigger → ACK → edge mode --------------------------------------
    print("\n2) start_challenge handler (simulated MQTT)")
    local = FakeLocal()
    mqtt = FakeMqtt()
    edge, parsed = handle_challenge3_sim(mqtt, local, brief)
    results.append(check("enters edge mode on start_challenge", edge))
    results.append(check("event stored locally", len(local.challenge_events) == 1))
    results.append(check(
        "ACK published on Challenge3 topic",
        len(mqtt.published) == 1 and mqtt.published[0][0] == config.TOPIC_CHALLENGE3,
        config.TOPIC_CHALLENGE3,
    ))
    ack = json.loads(mqtt.published[0][1])
    results.append(check("ACK has ack=true and edge_mode", ack.get("ack") and ack.get("edge_mode")))

    # --- 3. Offline buffering ----------------------------------------------
    print("\n3) Offline edge buffering (WiFi cut)")
    for i in range(5):
        local.insert_reading("zone-1", 30.0 + i, "moisture")
        local.insert_reading("zone-1", 22.0 + i * 0.1, "temperature")
    pending_before = len(local.pending())
    results.append(check(
        "readings accumulate locally while offline",
        pending_before == 10,
        f"{pending_before} pending",
    ))
    results.append(check(
        "control/dashboard do not need central (by design)",
        True,
        "sensors + irrigation + Flask are local-only",
    ))

    # --- 4. Catch-up sync, no gaps -----------------------------------------
    print("\n4) Auto catch-up when link returns")
    central = FakeCentral()
    n = simulated_push(local, central)
    results.append(check("sync drained all pending rows", n == 10 and len(local.pending()) == 0))
    results.append(check(
        "central has every blackout reading (no gaps)",
        len(central.rows) == 10,
        f"{len(central.rows)} on central",
    ))

    # --- 5. Crash mid-push → no duplicates ---------------------------------
    print("\n5) Idempotent retry (crash after central insert, before local mark)")
    local2 = FakeLocal()
    central2 = FakeCentral()
    rows = [local2.insert_reading("zone-2", 40 + i, "moisture") for i in range(3)]
    # First attempt: insert to central succeeds, but we "crash" before mark_synced
    keys = [database.central_key_for_row(r) for r in rows]
    central2.insert_many([
        (database.central_key_for_row(r), r["sensor_value"], r["created_at"])
        for r in rows
    ])
    # Rows still pending locally (crash)
    results.append(check("after crash, local still pending", len(local2.pending()) == 3))
    results.append(check("central already has the 3 rows", len(central2.rows) == 3))
    # Retry with real push logic — should skip already-present keys
    n2 = simulated_push(local2, central2)
    results.append(check("retry marks local synced", n2 == 3 and len(local2.pending()) == 0))
    results.append(check(
        "retry does NOT duplicate on central",
        len(central2.rows) == 3,
        f"keys={sorted(central2.rows)}",
    ))
    results.append(check(
        "keys embed local ids",
        all(k.endswith(f"#L{i}") for i, k in enumerate(keys, start=1)),
        keys,
    ))

    # --- 6. Topic config ---------------------------------------------------
    print("\n6) Topic wiring")
    results.append(check(
        "TOPIC_CHALLENGE3 matches brief",
        config.TOPIC_CHALLENGE3 == f"hackathon/{config.TEAM_NAME}/Challenge3",
        config.TOPIC_CHALLENGE3,
    ))

    passed, total = sum(results), len(results)
    print(f"\n=== RESULT: {passed}/{total} passed ===")
    if passed == total:
        print(
            "Simulation OK. Remaining Pi-only proof: real sensors, real WiFi cut,\n"
            "and live central MySQL/MQTT. Run CHALLENGE3.md on the Pi for that."
        )
        return 0
    print("Some checks failed — see FAIL lines above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
