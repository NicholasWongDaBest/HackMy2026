"""Publish the Alien Attack (Challenge 3) start trigger.

    python3 tools/challenge3_trigger.py
    python3 tools/challenge3_trigger.py --json   # JSON shape instead of brief format

Requires network reachability to central MQTT (192.168.98.50:1883).
Run this BEFORE the judges cut WiFi, or ask them to publish the same payload.
"""
import argparse
import json
import sys
import time

sys.path.insert(0, ".")
from farm import config  # noqa: E402

# Exact shape from ALIEN ATTACK.pdf (not valid JSON — intentional).
BRIEF_PAYLOAD = '{type:start_challenge;message:"Please start Challenge 3"}'


def main():
    parser = argparse.ArgumentParser(description="Trigger Challenge 3 / Alien Attack")
    parser.add_argument(
        "--json",
        action="store_true",
        help="publish JSON instead of the brief's semicolon format",
    )
    args = parser.parse_args()

    if args.json:
        payload = json.dumps({
            "type": "start_challenge",
            "message": "Please start Challenge 3",
        })
    else:
        payload = BRIEF_PAYLOAD

    import paho.mqtt.client as mqtt

    topic = config.TOPIC_CHALLENGE3
    client = mqtt.Client(client_id=f"{config.TEAM_NAME}-c3-trigger")
    print(f"Connecting {config.MQTT_HOST}:{config.MQTT_PORT} ...")
    client.connect(config.MQTT_HOST, config.MQTT_PORT, 30)
    client.loop_start()
    info = client.publish(topic, payload, qos=1)
    info.wait_for_publish(timeout=10)
    print(f"Published to {topic}")
    print(f"  payload: {payload}")
    time.sleep(1)
    client.loop_stop()
    client.disconnect()
    print("Done. Watch mqtt_client logs and the dashboard edge banner.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
