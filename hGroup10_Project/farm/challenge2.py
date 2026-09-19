"""Explicit Task2 trigger. Running without --start only prints the request."""
import argparse
import json
import threading

from . import config


def request():
    return (f"hackathon/{config.TEAM_NAME}/Challenge2",
            {"type": "start_challenge", "message": "Please start Challenge 2"})


def publish_trigger():
    import paho.mqtt.client as mqtt

    connected = threading.Event()
    result = {"rc": None}
    client = mqtt.Client(client_id=f"{config.TEAM_NAME}-challenge2", clean_session=True)

    def on_connect(client, userdata, flags, rc):
        result["rc"] = rc
        connected.set()

    client.on_connect = on_connect
    client.connect_async(config.MQTT_HOST, config.MQTT_PORT, keepalive=30)
    client.loop_start()
    try:
        if not connected.wait(10) or result["rc"] != 0:
            raise RuntimeError("Broker connection not acknowledged within 10 seconds")
        topic, payload = request()
        message = client.publish(topic, json.dumps(payload), qos=1, retain=False)
        if message.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError("Broker publish could not be queued")
        message.wait_for_publish(timeout=10)
        if not message.is_published():
            raise RuntimeError("Trigger delivery unconfirmed; check worker logs before retrying")
    finally:
        client.disconnect()
        client.loop_stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true", help="send the real challenge trigger once")
    args = parser.parse_args(argv)
    topic, payload = request()
    print(topic, json.dumps(payload))
    if not args.start:
        print("Preview only. Use --start when the monitor is running and you are ready for the judge's injections.")
        return 0
    try:
        publish_trigger()
    except Exception as exc:
        # Do not dump connection config/driver error strings.
        print(f"Trigger not confirmed ({type(exc).__name__}). Check the broker and worker logs.")
        return 1
    print("Broker acknowledged the trigger. This is NOT proof that Task2 has passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
