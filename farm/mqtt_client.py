"""MQTT client: subscribes to the three topics, validates everything,
and publishes the self-verification signal to central.

Run:  python3 -m farm.mqtt_client
"""
import json
import logging
import signal
import socket
import time

import paho.mqtt.client as mqtt

from . import config, database, validation

log = logging.getLogger("mqtt")


def _client_id() -> str:
    return f"{config.TEAM_NAME}-pi-{int(time.time())}"


def on_connect(client, userdata, flags, rc):
    if rc != 0:
        log.error("connect failed rc=%s", rc)
        return
    log.info("connected to %s:%s", config.MQTT_HOST, config.MQTT_PORT)
    for topic in (config.TOPIC_BROADCAST, config.TOPIC_TEST, config.TOPIC_VERIFY):
        client.subscribe(topic, qos=1)
        log.info("subscribed %s", topic)
    publish_verify(client, reason="startup")


def on_message(client, userdata, msg):
    """Single entry point for untrusted data. Nothing below this line
    assumes the payload is well formed."""
    raw = msg.payload
    try:
        if msg.topic == config.TOPIC_BROADCAST:
            handle_broadcast(raw)
        elif msg.topic == config.TOPIC_TEST:
            handle_test(client, raw)
        elif msg.topic == config.TOPIC_VERIFY:
            log.info("verify echo: %s", raw[:120])
        else:
            database.record_rejection(msg.topic, "unexpected topic", raw)
    except validation.Rejected as exc:
        database.record_rejection(msg.topic, str(exc), raw)
    except Exception as exc:                      # never let a bad message kill the loop
        log.exception("handler error")
        database.record_rejection(msg.topic, f"handler error: {exc}", raw)


def handle_broadcast(raw: bytes) -> None:
    """Broadcast carries the selfcare message -- and whatever a judge
    decides to inject. validate_broadcast() picks the right validator by
    payload shape and raises with the reason that actually describes the
    failure."""
    result = validation.validate_broadcast(raw)

    if result["kind"] == "selfcare":
        database.save_selfcare(result["message"], source="mqtt")
        log.info("selfcare message accepted (%d chars)", len(result["message"]))
    else:
        database.insert_reading(
            result["sensor_position"], result["sensor_value"], result["sensor_type"]
        )
        log.info("broadcast sensor reading accepted")


def handle_test(client, raw: bytes) -> None:
    data = validation.parse_json(raw) if raw.strip().startswith(b"{") else {}
    log.info("test message: %s", raw[:120])
    client.publish(
        config.TOPIC_TEST,
        json.dumps({"team": config.TEAM_NAME, "ack": True, "ts": time.time()}),
        qos=1,
    )


def publish_verify(client, reason: str = "heartbeat") -> None:
    """Self-verification signal to central. Includes live health figures
    so 'verified' means the system is actually working, not just alive."""
    try:
        pending, _ = database.sync_status()
        total_rejected, _ = database.rejection_summary(limit=1)
    except Exception:
        pending, total_rejected = -1, -1

    payload = {
        "team": config.TEAM_NAME,
        "node": socket.gethostname(),
        "status": "online",
        "reason": reason,
        "pending_sync_rows": pending,
        "rejected_messages": total_rejected,
        "timestamp": time.time(),
    }
    client.publish(config.TOPIC_VERIFY, json.dumps(payload), qos=1)
    log.info("published verify signal (%s)", reason)


def build_client() -> mqtt.Client:
    client = mqtt.Client(client_id=_client_id(), clean_session=True)
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    client = build_client()
    client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
    client.loop_start()

    running = {"on": True}
    signal.signal(signal.SIGINT, lambda *_: running.update(on=False))
    signal.signal(signal.SIGTERM, lambda *_: running.update(on=False))

    last_verify = 0.0
    while running["on"]:
        if time.time() - last_verify > 30:
            publish_verify(client)
            last_verify = time.time()
        time.sleep(1)

    client.loop_stop()
    client.disconnect()
    log.info("stopped")


if __name__ == "__main__":
    main()
