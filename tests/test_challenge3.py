"""Challenge 3 / Alien Attack unit tests (no MySQL / MQTT required)."""
import unittest

from farm import database, validation


class Challenge3ParseTests(unittest.TestCase):
    def test_brief_semicolon_format(self):
        raw = b'{type:start_challenge;message:"Please start Challenge 3"}'
        parsed = validation.parse_challenge3_payload(raw)
        self.assertEqual(parsed["type"], "start_challenge")
        self.assertIn("Challenge 3", parsed["message"])

    def test_json_format(self):
        raw = b'{"type":"start_challenge","message":"Please start Challenge 3"}'
        parsed = validation.parse_challenge3_payload(raw)
        self.assertEqual(parsed["type"], "start_challenge")

    def test_empty_rejected(self):
        with self.assertRaises(validation.Rejected):
            validation.parse_challenge3_payload(b"")

    def test_missing_type_rejected(self):
        with self.assertRaises(validation.Rejected):
            validation.parse_challenge3_payload(b'{message:"hi"}')


class IdempotentKeyTests(unittest.TestCase):
    def test_central_key_embeds_local_id(self):
        key = database.central_key_for_row({
            "id": 7,
            "sensor_position": "zone-1",
            "sensor_type": "moisture",
        })
        self.assertEqual(key, "zone-1/moisture#L7")


if __name__ == "__main__":
    unittest.main()
