"""MQTT client: subscribes to the three topics, validates everything,
and answers Central's MQTT verification challenge.

Run:  python3 -m farm.mqtt_client
"""
import json
import logging
import signal
import time

import paho.mqtt.client as mqtt

from . import config, database, validation

log = logging.getLogger("mqtt")

_RESPONSE_KEYS = (
    "response", "expectedResponse", "expected_response",
    "predefinedResponse", "predefined_response",
)
_REPLY_TOPIC_KEYS = ("responseTopic", "response_topic", "replyTopic", "replyTo")
_FAILURE_TYPES = {"mqtt_test_failed", "mqtt_test_failure"}
_SUCCESS_TYPES = {"mqtt_test_passed", "mqtt_test_success"}
_RESPONSE_TYPE = "mqtt_test_response"
_REQUEST_TYPE = "mqtt_test"
_DUPLICATE_WINDOW_S = 120
_responded_request_ids = {}


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
            handle_verify(raw)
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


def _redacted(data):
    """Return a log-safe copy while retaining the complete message shape."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            sensitive = any(word in key.lower() for word in (
                "password", "passwd", "secret", "token", "credential", "auth",
            ))
            result[key] = "<redacted>" if sensitive else _redacted(value)
        return result
    if isinstance(data, list):
        return [_redacted(value) for value in data]
    return data


def _log_payload(level, prefix: str, data: dict) -> None:
    log.log(
        level,
        "%s: %s",
        prefix,
        json.dumps(_redacted(data), ensure_ascii=False, sort_keys=True),
    )


def _parse_control_message(raw: bytes) -> dict:
    validation.check_size(raw)
    return validation.parse_json(raw)


def _request_id(data: dict) -> str:
    request_id = data.get("requestId")
    if not isinstance(request_id, str):
        raise validation.Rejected("mqtt_test requestId must be a string")
    cleaned = validation.sanitize_text(request_id, max_chars=200)
    if cleaned != request_id:
        raise validation.Rejected("mqtt_test requestId has surrounding whitespace")
    return cleaned


def _response_for(data: dict, request_id: str) -> tuple:
    """Return (topic, payload), preferring Central's supplied response."""
    response = None
    for key in _RESPONSE_KEYS:
        if key in data:
            response = data[key]
            break

    topic = None
    for key in _REPLY_TOPIC_KEYS:
        if key in data:
            topic = data[key]
            break

    # Central may supply an envelope: {"topic": "...", "payload": {...}}.
    if isinstance(response, dict) and "payload" in response:
        if topic is None:
            topic = response.get("topic")
        response = response["payload"]

    if response is None:
        response = {
            "type": _RESPONSE_TYPE,
            "team": config.TEAM_NAME,
            "requestId": request_id,
            "status": "ok",
        }
    elif not isinstance(response, dict):
        raise validation.Rejected("mqtt_test predefined response must be an object")

    expected = {
        "type": _RESPONSE_TYPE,
        "team": config.TEAM_NAME,
        "requestId": request_id,
        "status": "ok",
    }
    for field, value in expected.items():
        if response.get(field) != value:
            raise validation.Rejected(
                f"mqtt_test response field '{field}' does not match the request"
            )

    # Central's live mqtt_test request instructs the team to publish its
    # supplied response back to /test. Honour an explicit structured topic
    # when present, otherwise use that observed protocol default.
    topic = topic or config.TOPIC_TEST
    if topic not in {config.TOPIC_TEST, config.TOPIC_VERIFY}:
        raise validation.Rejected(
            f"mqtt_test response topic '{topic}' is not a permitted team topic"
        )
    return topic, response


def _already_responded(request_id: str) -> bool:
    now = time.monotonic()
    expired = [
        key for key, seen_at in _responded_request_ids.items()
        if now - seen_at > _DUPLICATE_WINDOW_S
    ]
    for key in expired:
        del _responded_request_ids[key]
    return request_id in _responded_request_ids


def handle_test(client, raw: bytes) -> bool:
    """Answer exactly one genuine mqtt_test request; ignore all echoes."""
    data = _parse_control_message(raw)
    message_type = data.get("type")

    if message_type in _FAILURE_TYPES:
        _log_payload(logging.ERROR, "Central MQTT verification failure", data)
        return False
    if message_type in _SUCCESS_TYPES:
        _log_payload(logging.INFO, "Central MQTT verification success", data)
        return False
    if message_type == _RESPONSE_TYPE:
        log.debug("ignored MQTT verification response echo")
        return False
    if message_type != _REQUEST_TYPE:
        log.info("ignored non-request message on test topic (type=%r)", message_type)
        return False

    _log_payload(logging.INFO, "Central MQTT verification request", data)

    target_team = data.get("team")
    if target_team is not None and target_team != config.TEAM_NAME:
        raise validation.Rejected(
            f"mqtt_test targets team '{target_team}', not '{config.TEAM_NAME}'"
        )

    request_id = _request_id(data)
    if _already_responded(request_id):
        log.info("ignored duplicate mqtt_test requestId=%s", request_id)
        return False

    topic, response = _response_for(data, request_id)
    payload = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    result = client.publish(topic, payload, qos=1)
    rc = getattr(result, "rc", 0)
    if rc != getattr(mqtt, "MQTT_ERR_SUCCESS", 0):
        raise RuntimeError(f"MQTT publish was not queued (rc={rc})")

    _responded_request_ids[request_id] = time.monotonic()
    log.info("queued mqtt_test_response requestId=%s topic=%s", request_id, topic)
    return True


def handle_verify(raw: bytes) -> None:
    """Log Central's verdict and ignore our own response echo."""
    data = _parse_control_message(raw)
    message_type = data.get("type")
    if message_type in _FAILURE_TYPES:
        _log_payload(logging.ERROR, "Central MQTT verification failure", data)
    elif message_type in _SUCCESS_TYPES:
        _log_payload(logging.INFO, "Central MQTT verification success", data)
    elif message_type == _RESPONSE_TYPE:
        log.debug("ignored MQTT verification response echo")
    else:
        log.info("ignored non-verdict message on verify topic (type=%r)", message_type)


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

    while running["on"]:
        time.sleep(1)

    client.loop_stop()
    client.disconnect()
    log.info("stopped")


if __name__ == "__main__":
    main()
