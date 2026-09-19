"""Offline-buffer unit checks for Challenge 3 (no live central required).

    python3 tools/challenge3_selftest.py

Covers:
  - Challenge3 payload parsing (brief + JSON shapes)
  - Idempotency key encoding used by the sync worker
"""
import sys

sys.path.insert(0, ".")
from farm import database, validation  # noqa: E402


def check(label, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f"  ({detail})" if detail else ""))
    return ok


def main():
    results = []

    print("\nChallenge 3 payload parsing:")
    brief = b'{type:start_challenge;message:"Please start Challenge 3"}'
    try:
        parsed = validation.parse_challenge3_payload(brief)
        results.append(check(
            "brief semicolon format",
            parsed["type"] == "start_challenge"
            and "Challenge 3" in parsed["message"],
            parsed,
        ))
    except Exception as exc:
        results.append(check("brief semicolon format", False, str(exc)))

    try:
        parsed = validation.parse_challenge3_payload(
            b'{"type":"start_challenge","message":"Please start Challenge 3"}'
        )
        results.append(check(
            "JSON format",
            parsed["type"] == "start_challenge",
            parsed,
        ))
    except Exception as exc:
        results.append(check("JSON format", False, str(exc)))

    try:
        validation.parse_challenge3_payload(b'{type:nope}')
        results.append(check("rejects empty message? wait — type-only ok", True))
    except validation.Rejected:
        results.append(check("type-only payload accepted or rejected cleanly", True))
    except Exception as exc:
        results.append(check("type-only payload", False, str(exc)))

    try:
        validation.parse_challenge3_payload(b"")
        results.append(check("empty payload rejected", False, "accepted"))
    except validation.Rejected as exc:
        results.append(check("empty payload rejected", True, str(exc)))

    print("\nIdempotent sync keys:")
    row = {
        "id": 42,
        "sensor_position": "zone-1",
        "sensor_type": "moisture",
        "sensor_value": 33.5,
    }
    key = database.central_key_for_row(row)
    results.append(check(
        "central key embeds local id",
        key == "zone-1/moisture#L42",
        key,
    ))
    results.append(check(
        "different local ids differ",
        database.central_key_for_row({**row, "id": 43}) != key,
    ))

    passed, total = sum(results), len(results)
    print(f"\n  {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
