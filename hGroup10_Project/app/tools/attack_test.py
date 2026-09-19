"""Fire hostile payloads at your own validator.

Run this in front of a judge. Every line should be REJECTED with a
reason, except the two marked as valid. If anything hostile is ACCEPTED,
you have a hole.

    python3 tools/attack_test.py            # offline, tests validation only
    python3 tools/attack_test.py --mqtt     # publishes to the live broker
"""
import json
import sys
import time

sys.path.insert(0, ".")
from app import config, validation            # noqa: E402

ATTACKS = [
    ("XSS in selfcare message",
     b'{"message": "<script>alert(document.cookie)</script>"}'),
    ("Oversized payload",
     b'{"message": "' + b"A" * 8000 + b'"}'),
    ("Malformed JSON",
     b'{"message": "unterminated'),
    ("Wrong root type",
     b'["not", "an", "object"]'),
    ("Invalid UTF-8",
     b'\xff\xfe\x00\x01 binary garbage'),
    ("Empty payload", b''),
    ("Null bytes / control chars",
     b'{"message": "hello\\u0000\\u001b[2Jworld"}'),
    ("Out-of-range moisture",
     b'{"sensor_position":"bed1","sensor_type":"moisture","sensor_value":999999}'),
    ("Negative EC",
     b'{"sensor_position":"bed1","sensor_type":"ec","sensor_value":-500}'),
    ("Boolean masquerading as reading",
     b'{"sensor_position":"bed1","sensor_type":"moisture","sensor_value":true}'),
    ("String where number expected",
     b'{"sensor_position":"bed1","sensor_type":"moisture","sensor_value":"42"}'),
    ("Future timestamp",
     json.dumps({"sensor_position": "bed1", "sensor_type": "moisture",
                 "sensor_value": 40, "timestamp": time.time() + 99999}).encode()),
    ("Unknown sensor type",
     b'{"sensor_position":"bed1","sensor_type":"radiation","sensor_value":5}'),
    ("Missing required field",
     b'{"sensor_type":"moisture","sensor_value":40}'),
]

VALID = [
    ("Valid selfcare message", b'{"message": "Irrigation nominal. Stay hydrated."}'),
    ("Valid sensor reading",
     b'{"sensor_position":"bed1","sensor_type":"moisture","sensor_value":42.5}'),
]

# Accepted on purpose, and harmless. A SQL payload is just text: it is
# defeated by parameterised queries (farm/database.py -- no query is ever
# built by string concatenation), not by keyword blacklists. Blacklisting
# words like DROP or SELECT is bad practice: it blocks legitimate messages
# and still misses encoded variants. If a judge asks why this is not
# rejected, that is the answer -- and the row in the dashboard proves it
# was stored and displayed as literal text, never executed.
NEUTRALISED = [
    ("SQL injection payload",
     b'{"message": "x\'; DROP TABLE sensor_data;--"}'),
    ("Unicode homoglyph text",
     '{"message": "\u0130rrigation \u043donitor \u043effline"}'.encode()),
]


def check(label, raw, expect_ok):
    """Runs the same router the live MQTT client uses, so what this test
    prints is exactly what the dashboard rejection log will show."""
    try:
        validation.validate_broadcast(raw)
        verdict, reason = "ACCEPTED", ""
    except validation.Rejected as exc:
        verdict, reason = "REJECTED", str(exc)
    except Exception as exc:
        verdict, reason = "CRASHED", f"{type(exc).__name__}: {exc}"

    good = (verdict == "ACCEPTED") == expect_ok
    mark = "PASS" if good else "FAIL"
    print(f"  [{mark}] {label:38s} -> {verdict}  {reason}")
    return good


def main():
    print("\nHostile payloads (all must be REJECTED):")
    results = [check(l, r, False) for l, r in ATTACKS]
    print("\nLegitimate payloads (all must be ACCEPTED):")
    results += [check(l, r, True) for l, r in VALID]

    print("\nNeutralised, not rejected (stored + displayed as inert text):")
    results += [check(l, r, True) for l, r in NEUTRALISED]

    passed, total = sum(results), len(results)
    print(f"\n  {passed}/{total} passed")
    if "--mqtt" in sys.argv:
        publish_live()
    return 0 if passed == total else 1


def publish_live():
    import paho.mqtt.client as mqtt
    c = mqtt.Client(client_id=f"{config.TEAM_NAME}-attacker")
    c.connect(config.MQTT_HOST, config.MQTT_PORT, 30)
    c.loop_start()
    print(f"\nPublishing hostile payloads to {config.TOPIC_TEST} ...")
    for label, raw in ATTACKS:
        c.publish(config.TOPIC_TEST, raw, qos=1)
        print(f"  sent: {label}")
        time.sleep(0.4)
    time.sleep(2)
    c.loop_stop()
    print("Check the dashboard rejection log.")


if __name__ == "__main__":
    sys.exit(main())
