"""Hardware-free tests for the Task 1 MQTT verification handshake."""
import importlib.util
import json
import pathlib
import sys
import types
import unittest
from unittest import mock


# Keep the test runnable on a laptop without the Pi's installed packages.
fake_mqtt = types.ModuleType("paho.mqtt.client")
fake_mqtt.Client = object
fake_mqtt.MQTT_ERR_SUCCESS = 0
fake_paho_mqtt = types.ModuleType("paho.mqtt")
fake_paho_mqtt.client = fake_mqtt
fake_paho = types.ModuleType("paho")
fake_paho.mqtt = fake_paho_mqtt
sys.modules.setdefault("paho", fake_paho)
sys.modules.setdefault("paho.mqtt", fake_paho_mqtt)
sys.modules.setdefault("paho.mqtt.client", fake_mqtt)

fake_database = types.ModuleType("farm.database")
fake_database.record_rejection = mock.Mock()
fake_database.save_selfcare = mock.Mock()
fake_database.insert_reading = mock.Mock()
sys.modules["farm.database"] = fake_database

# Another hardware-free test module substitutes farm.validation. Load the
# real source explicitly so discovery order cannot weaken these checks.
import farm  # noqa: E402

validation_path = pathlib.Path(__file__).parents[1] / "farm" / "validation.py"
validation_spec = importlib.util.spec_from_file_location(
    "farm._mqtt_validation_test", validation_path
)
real_validation = importlib.util.module_from_spec(validation_spec)
validation_spec.loader.exec_module(real_validation)
farm.database = fake_database
farm.validation = real_validation
sys.modules["farm.validation"] = real_validation

from farm import config, mqtt_client  # noqa: E402

mqtt_client.validation = real_validation
mqtt_client.database = fake_database


class PublishResult:
    rc = 0


class FakeClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))
        return PublishResult()


class MqttVerificationTests(unittest.TestCase):
    def setUp(self):
        mqtt_client._responded_request_ids.clear()
        self.client = FakeClient()

    def test_uses_central_predefined_response_and_topic(self):
        expected = {
            "type": "mqtt_test_response",
            "team": config.TEAM_NAME,
            "requestId": "request-123",
            "status": "ok",
            "centralNonce": "keep-this-field",
        }
        request = {
            "type": "mqtt_test",
            "team": config.TEAM_NAME,
            "requestId": "request-123",
            "response": {
                "topic": config.TOPIC_VERIFY,
                "payload": expected,
            },
        }

        handled = mqtt_client.handle_test(
            self.client, json.dumps(request).encode("utf-8")
        )

        self.assertTrue(handled)
        self.assertEqual(len(self.client.published), 1)
        topic, payload, qos = self.client.published[0]
        self.assertEqual(topic, config.TOPIC_VERIFY)
        self.assertEqual(json.loads(payload), expected)
        self.assertEqual(qos, 1)

    def test_request_without_predefined_response_uses_protocol_response(self):
        request = {
            "type": "mqtt_test",
            "requestId": "request-456",
        }

        mqtt_client.handle_test(self.client, json.dumps(request).encode("utf-8"))

        topic, payload, qos = self.client.published[0]
        self.assertEqual(topic, config.TOPIC_TEST)
        self.assertEqual(json.loads(payload), {
            "type": "mqtt_test_response",
            "team": config.TEAM_NAME,
            "requestId": "request-456",
            "status": "ok",
        })
        self.assertEqual(qos, 1)

    def test_live_central_request_replies_to_test_topic(self):
        request = {
            "message": (
                "Please respond within 30s. Copy the response object below "
                f"and publish it to {config.TOPIC_TEST}."
            ),
            "requestId": "6a0e410d8d3588256f288c05dab505c0",
            "response": {
                "requestId": "6a0e410d8d3588256f288c05dab505c0",
                "status": "ok",
                "team": config.TEAM_NAME,
                "type": "mqtt_test_response",
            },
            "sentAt": "2026-09-19T14:13:26+00:00",
            "team": config.TEAM_NAME,
            "type": "mqtt_test",
        }

        self.assertTrue(mqtt_client.handle_test(
            self.client, json.dumps(request).encode("utf-8")
        ))

        self.assertEqual(len(self.client.published), 1)
        topic, payload, qos = self.client.published[0]
        self.assertEqual(topic, config.TOPIC_TEST)
        self.assertEqual(json.loads(payload), request["response"])
        self.assertEqual(qos, 1)

    def test_duplicate_request_is_published_exactly_once(self):
        raw = json.dumps({
            "type": "mqtt_test",
            "requestId": "request-duplicate",
        }).encode("utf-8")

        self.assertTrue(mqtt_client.handle_test(self.client, raw))
        self.assertFalse(mqtt_client.handle_test(self.client, raw))
        self.assertEqual(len(self.client.published), 1)

    def test_response_echo_and_failure_do_not_publish(self):
        response = {
            "type": "mqtt_test_response",
            "team": config.TEAM_NAME,
            "requestId": "request-echo",
            "status": "ok",
        }
        failure = {
            "type": "mqtt_test_failed",
            "requestId": "request-echo",
            "reason": "response payload did not match",
        }

        self.assertFalse(mqtt_client.handle_test(
            self.client, json.dumps(response).encode("utf-8")
        ))
        with self.assertLogs("mqtt", level="ERROR") as captured:
            self.assertFalse(mqtt_client.handle_test(
                self.client, json.dumps(failure).encode("utf-8")
            ))

        self.assertEqual(self.client.published, [])
        self.assertIn("response payload did not match", "\n".join(captured.output))

    def test_mismatched_predefined_response_is_rejected(self):
        request = {
            "type": "mqtt_test",
            "requestId": "correct-id",
            "response": {
                "type": "mqtt_test_response",
                "team": config.TEAM_NAME,
                "requestId": "wrong-id",
                "status": "ok",
            },
        }

        with self.assertRaises(real_validation.Rejected):
            mqtt_client.handle_test(
                self.client, json.dumps(request).encode("utf-8")
            )
        self.assertEqual(self.client.published, [])


if __name__ == "__main__":
    unittest.main()
