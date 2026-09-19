"""Input validation gates.

Every byte that arrives from the network is hostile until it has passed
through validate_payload(). Nothing reaches the database or the dashboard
without a verdict.

Design rule: reject loudly, never crash, never silently swallow. Each
rejection carries a human-readable reason so the dashboard can show a
judge exactly what was caught and why.
"""
import json
import re
import time
from datetime import datetime, timezone

from . import config


class Rejected(Exception):
    """Raised with the reason a payload failed validation."""


# Control characters have no place in a farm message and are a classic way
# to smuggle terminal escape sequences or forge log lines. We REJECT rather
# than strip: silently mutating a payload means the dashboard shows
# something different from what was sent, which hides the attack.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Markup has no place in a status message either. Rendering is escaped as
# well (Jinja autoescape) -- this is the outer of two independent layers.
_MARKUP = re.compile(
    r"(<\s*/?\s*[a-zA-Z])"      # <script  </div  < img
    r"|(javascript\s*:)"
    r"|(\bon[a-z]{3,15}\s*=)",  # onerror=  onload=
    re.IGNORECASE,
)


def _utcnow() -> float:
    return datetime.now(timezone.utc).timestamp()


# ---------------------------------------------------------------------
# Gate 1 -- size
# ---------------------------------------------------------------------
def check_size(raw: bytes) -> None:
    if not raw:
        raise Rejected("empty payload")
    if len(raw) > config.MAX_PAYLOAD_BYTES:
        raise Rejected(
            f"payload too large ({len(raw)} bytes > {config.MAX_PAYLOAD_BYTES})"
        )


# ---------------------------------------------------------------------
# Gate 2 -- decode and parse
# ---------------------------------------------------------------------
def parse_json(raw: bytes) -> dict:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Rejected("payload is not valid UTF-8")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Rejected(f"malformed JSON: {exc.msg}")

    if not isinstance(data, dict):
        raise Rejected(f"expected a JSON object, got {type(data).__name__}")
    return data


# ---------------------------------------------------------------------
# Gate 3 -- schema
# ---------------------------------------------------------------------
def require_fields(data: dict, required: dict) -> None:
    """required maps field name -> tuple of acceptable python types."""
    for field, types in required.items():
        if field not in data:
            raise Rejected(f"missing required field '{field}'")
        if isinstance(data[field], bool) and bool not in types:
            # bool is a subclass of int in Python; a True moisture reading
            # is corrupt data, not the number 1.
            raise Rejected(f"field '{field}' is a boolean, expected number")
        if not isinstance(data[field], types):
            raise Rejected(
                f"field '{field}' has type {type(data[field]).__name__}, "
                f"expected {'/'.join(t.__name__ for t in types)}"
            )


# ---------------------------------------------------------------------
# Gate 4 -- physical range
# ---------------------------------------------------------------------
def check_range(sensor_type: str, value: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise Rejected(f"sensor_value '{value}' is not numeric")

    if value != value or value in (float("inf"), float("-inf")):
        raise Rejected("sensor_value is NaN or infinite")

    bounds = config.SENSOR_RANGES.get(sensor_type)
    if bounds is None:
        raise Rejected(f"unknown sensor_type '{sensor_type}'")

    low, high = bounds
    if not (low <= value <= high):
        raise Rejected(
            f"{sensor_type} reading {value} outside plausible range {low}..{high}"
        )
    return value


# ---------------------------------------------------------------------
# Gate 5 -- timestamp sanity
# ---------------------------------------------------------------------
def check_timestamp(ts) -> float:
    """Accepts a unix epoch or ISO-8601 string. Returns epoch seconds.

    The wire timestamp is never trusted as the record's created_at -- it
    is kept for reference only and the server stamps its own time.
    """
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        epoch = float(ts)
    elif isinstance(ts, str):
        try:
            epoch = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            raise Rejected(f"unparseable timestamp '{ts[:40]}'")
    else:
        raise Rejected(f"timestamp has type {type(ts).__name__}")

    now = _utcnow()
    if epoch > now + config.CLOCK_SKEW_FUTURE_S:
        raise Rejected("timestamp is in the future")
    if epoch < now - config.CLOCK_SKEW_PAST_S:
        raise Rejected("timestamp is implausibly old")
    return epoch


# ---------------------------------------------------------------------
# Gate 6 -- text sanitisation
# ---------------------------------------------------------------------
def sanitize_text(value: str, max_chars: int = None) -> str:
    """Validate a free-text field for storage and display.

    Rejects control characters and markup outright. It deliberately does
    NOT html-escape: escaping happens at render time (Jinja autoescape),
    so the database holds the true received value and the dashboard is
    what renders it inert. Escaping in both places would double-encode
    and hide what was actually sent.
    """
    if not isinstance(value, str):
        raise Rejected(f"expected text, got {type(value).__name__}")

    if _CONTROL_CHARS.search(value):
        raise Rejected("text contains control characters or escape sequences")

    match = _MARKUP.search(value)
    if match:
        raise Rejected(f"text contains markup or script content: '{match.group(0)}'")

    cleaned = value.strip()
    if not cleaned:
        raise Rejected("text field is empty")

    cap = max_chars or config.MAX_MESSAGE_CHARS
    if len(cleaned) > cap:
        raise Rejected(f"text too long ({len(cleaned)} chars > {cap})")
    return cleaned


# ---------------------------------------------------------------------
# Composed validators
# ---------------------------------------------------------------------
def validate_sensor_message(raw: bytes) -> dict:
    """A sensor reading arriving over MQTT. Raises Rejected on any failure."""
    check_size(raw)
    data = parse_json(raw)
    require_fields(data, {
        "sensor_position": (str,),
        "sensor_value": (int, float),
        "sensor_type": (str,),
    })

    sensor_type = sanitize_text(data["sensor_type"], max_chars=32).lower()
    position = sanitize_text(data["sensor_position"], max_chars=255)
    value = check_range(sensor_type, data["sensor_value"])

    wire_ts = None
    if "timestamp" in data:
        wire_ts = check_timestamp(data["timestamp"])

    return {
        "sensor_position": position,
        "sensor_type": sensor_type,
        "sensor_value": value,
        "wire_timestamp": wire_ts,
        "server_timestamp": time.time(),
    }


def validate_selfcare_message(raw: bytes) -> dict:
    """The selfcare message from broadcast. Accepts a bare string or
    a JSON object with a 'message' field -- the brief does not pin the
    shape down, so handle both rather than rejecting a valid message."""
    check_size(raw)

    looks_like_json = raw.lstrip()[:1] in (b"{", b"[")

    try:
        data = parse_json(raw)
    except Rejected:
        # A payload that opens with { or [ is claiming to be JSON. If it
        # then fails to parse it is malformed, not plain text -- accepting
        # it as text would let any broken or truncated object through.
        if looks_like_json:
            raise
        text = raw.decode("utf-8", errors="strict") if _is_utf8(raw) else None
        if text is None:
            raise Rejected("payload is not valid UTF-8")
        return {"message": sanitize_text(text)}

    for key in ("message", "selfcare_message", "selfcare", "text"):
        if key in data:
            return {"message": sanitize_text(data[key])}

    raise Rejected("no message field found in payload")


def _is_utf8(raw: bytes) -> bool:
    try:
        raw.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


# ---------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------
def validate_broadcast(raw: bytes) -> dict:
    """Validate an untrusted broadcast payload.

    The broadcast topic carries both selfcare messages and sensor
    readings, so we pick the validator by the shape of the payload. This
    matters for the rejection reason: a malformed sensor reading should
    be reported as a bad reading, not as 'no message field found'. A
    wrong reason in the log is a wrong diagnosis at 3am.

    Returns {'kind': 'selfcare'|'sensor', ...}. Raises Rejected.
    """
    check_size(raw)

    looks_like_sensor = b"sensor_value" in raw or b"sensor_position" in raw
    order = (
        [("sensor", validate_sensor_message), ("selfcare", validate_selfcare_message)]
        if looks_like_sensor
        else [("selfcare", validate_selfcare_message), ("sensor", validate_sensor_message)]
    )

    first_error = None
    for kind, validator in order:
        try:
            result = validator(raw)
            result["kind"] = kind
            return result
        except Rejected as exc:
            if first_error is None:
                first_error = exc
    raise first_error
