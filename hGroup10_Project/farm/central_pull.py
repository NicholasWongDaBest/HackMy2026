"""Read-only Central scanner and durable, isolated validation ledger.

No Central row is copied into sensor_data or sent to the controller. Every
cycle streams the entire table again, so UPDATEs to old IDs are visible.
Only changed fingerprints create audit events; state survives restarts.
"""
import hashlib
import json
import logging
import math
import os
import re

from . import config, validation

log = logging.getLogger("sync.pull")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Observed Central positions include "zone-2-canopy/humidity#L3283".
# Recognize only this exact trailing shape; retain the original for auditing.
_TYPE_ROW_SUFFIX = re.compile(r"#L[0-9]+\Z")
_VALIDATOR_VERSION = 2
_ALIASES = {"temp": "temperature", "moist": "moisture",
            "soil_moisture": "moisture", "air_temp": "air_temperature"}


class ScanBusy(RuntimeError):
    """Another copy of this worker owns the scan lock."""


class ConfigurationError(ValueError):
    """Safe, actionable diagnostics generated here, not raw driver errors."""


def position_types():
    # Optional config attribute for embedding/tests; otherwise no config.py
    # edits are needed on the Pi (preserve its working credentials).
    mapping = getattr(config, "CENTRAL_POSITION_TYPES", None)
    if mapping is None:
        try:
            mapping = json.loads(os.getenv("CENTRAL_POSITION_TYPES", "{}"))
        except ValueError:
            raise ConfigurationError("CENTRAL_POSITION_TYPES must be a valid JSON object")
    if not isinstance(mapping, dict):
        raise ConfigurationError("CENTRAL_POSITION_TYPES must be a JSON object")
    if any(not isinstance(v, str) or v not in config.SENSOR_RANGES for v in mapping.values()):
        raise ConfigurationError("CENTRAL_POSITION_TYPES contains an unknown sensor type")
    return mapping


def identifier(name):
    if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
        raise ConfigurationError("Central table/column must be a simple SQL identifier")
    return "`" + name + "`"


def source_key():
    # Credentials deliberately excluded from both identity and logs.
    source = [config.CENTRAL_DB["host"], config.CENTRAL_DB["database"],
              config.CENTRAL_TABLE]
    return hashlib.sha256(json.dumps(source).encode()).hexdigest()


def raw_json(row):
    # Only the selected sensor fields, never arbitrary server columns/config.
    return json.dumps(row, default=str, sort_keys=True, ensure_ascii=True)


def finite_number(value):
    if isinstance(value, bool):
        raise validation.Rejected("sensor_value is a boolean, not a measurement")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise validation.Rejected("sensor_value is not numeric")
    if not math.isfinite(number):
        raise validation.Rejected("sensor_value is NaN or infinite")
    return number


def sensor_identity(row):
    position = validation.sanitize_text(row.get("sensor_position"), 255)
    explicit = row.get("sensor_type")
    if explicit is not None:
        explicit = validation.sanitize_text(explicit, 32).lower()
        explicit = _ALIASES.get(explicit, explicit)
        if explicit not in config.SENSOR_RANGES:
            raise validation.Rejected("unknown explicit sensor_type")
    folded = None
    base = position
    if "/" in position:
        base, folded = position.rsplit("/", 1)
        base = validation.sanitize_text(base, 255)
        folded = _TYPE_ROW_SUFFIX.sub("", folded.strip())
        folded = _ALIASES.get(folded.strip().lower(), folded.strip().lower())
        if folded not in config.SENSOR_RANGES:
            raise validation.Rejected("unknown sensor type in sensor_position")
    elif position.lower() in config.SENSOR_RANGES or position.lower() in _ALIASES:
        folded = _ALIASES.get(position.lower(), position.lower())
        base = "central"
    mapping = position_types()
    mapped = mapping.get(position)
    if mapped is not None and (not isinstance(mapped, str) or
                               mapped not in config.SENSOR_RANGES):
        raise ConfigurationError("CENTRAL_POSITION_TYPES contains an unknown sensor type")
    candidates = [item for item in (explicit, folded, mapped) if item is not None]
    if not candidates:
        raise validation.Rejected(
            "missing/unknown sensor type; use zone/type, sensor_type, or a confirmed position mapping"
        )
    if len(set(candidates)) != 1:
        raise validation.Rejected("conflicting sensor type declarations")
    return base, candidates[0]


def inspect_row(row):
    raw = raw_json(row)
    revision = raw_json({"row": row, "ranges": config.SENSOR_RANGES,
                         "mapping": position_types(), "validator": _VALIDATOR_VERSION})
    result = {
        "central_id": row["id"],
        "fingerprint": hashlib.sha256(revision.encode()).hexdigest(),
        "position": str(row.get("sensor_position", ""))[:255],
        "raw_value": str(row.get("sensor_value", ""))[:128],
        "source_time": str(row.get("created_at", ""))[:64],
        "sensor_type": None, "numeric_value": None,
        "verdict": "accepted", "reason": "Within configured physical range; display only",
        "raw": raw,
    }
    try:
        # Numeric validation also applies when the type is unrecognised.
        result["numeric_value"] = finite_number(row.get("sensor_value"))
        _, result["sensor_type"] = sensor_identity(row)
        validation.check_range(result["sensor_type"], result["numeric_value"])
    except validation.Rejected as exc:
        result.update(verdict="rejected", reason=str(exc))
    return result


def ensure_schema(conn):
    # Additive local-only schema; no ALTER to sensor_data or Central.
    cur = conn.cursor()
    fields = (
        "source_key CHAR(64) NOT NULL, central_id BIGINT NOT NULL,"
        "fingerprint CHAR(64) NOT NULL, position VARCHAR(255) NOT NULL,"
        "raw_value VARCHAR(128) NOT NULL, source_time VARCHAR(64) NOT NULL,"
        "sensor_type VARCHAR(32) NULL, numeric_value DOUBLE NULL,"
        "verdict VARCHAR(16) NOT NULL, reason VARCHAR(255) NOT NULL,"
        "observed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
    )
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS central_rows (" + fields +
                    ", PRIMARY KEY (source_key, central_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
        cur.execute("CREATE TABLE IF NOT EXISTS central_changes ("
                    "event_id BIGINT AUTO_INCREMENT PRIMARY KEY," + fields +
                    ", INDEX idx_central_events (source_key, event_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS central_pull_status ("
            "source_key CHAR(64) PRIMARY KEY, status VARCHAR(16) NOT NULL,"
            "detail VARCHAR(255) NOT NULL, scanned INT NOT NULL DEFAULT 0,"
            "accepted INT NOT NULL DEFAULT 0, rejected INT NOT NULL DEFAULT 0,"
            "unchanged INT NOT NULL DEFAULT 0,"
            "checked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "successful_at TIMESTAMP NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        conn.commit()
    finally:
        cur.close()


def central_columns(conn, strict=True):
    cur = conn.cursor()
    try:
        cur.execute("SHOW COLUMNS FROM " + identifier(config.CENTRAL_TABLE))
        columns = [r[0] for r in cur.fetchall()]
    finally:
        cur.close()
    required = {"id", "sensor_position", "sensor_value", "created_at"}
    missing = required - set(columns)
    if not strict:
        return columns
    if missing:
        raise ConfigurationError("Central schema missing required sensor columns: " +
                         ", ".join(sorted(missing)))
    selected = ["id", "sensor_position", "sensor_value", "created_at"]
    if "sensor_type" in columns:
        selected.append("sensor_type")
    return selected


def row_query(columns):
    return ("SELECT " + ", ".join(identifier(c) for c in columns) +
            " FROM " + identifier(config.CENTRAL_TABLE) + " ORDER BY `id`")


def inspect_central(conn, limit=5):
    """Read-only diagnostic; reveals actual selected fields, not credentials."""
    columns = central_columns(conn, strict=False)
    selected = [c for c in ("id", "sensor_position", "sensor_value", "created_at", "sensor_type")
                if c in columns]
    result = {"table": config.CENTRAL_TABLE, "columns": columns, "sample": []}
    if not selected:
        return result
    cur = conn.cursor(dictionary=True)
    try:
        query = "SELECT " + ",".join(identifier(c) for c in selected)
        query += " FROM " + identifier(config.CENTRAL_TABLE)
        query += " ORDER BY `id` DESC" if "id" in selected else ""
        cur.execute(query + " LIMIT %s", (limit,))
        result["sample"] = cur.fetchall()
        return result
    finally:
        cur.close()


_FIELDS = ("source_key", "central_id", "fingerprint", "position", "raw_value",
           "source_time", "sensor_type", "numeric_value", "verdict", "reason")


def save_changed_batch(conn, rows, key):
    """Commit fingerprints, change history and rejections atomically."""
    counts = {"scanned": len(rows), "accepted": 0, "rejected": 0, "unchanged": 0}
    cur = conn.cursor(dictionary=True)
    messages = []
    try:
        ids = [r["id"] for r in rows]
        placeholders = ",".join(["%s"] * len(ids))
        cur.execute("SELECT central_id, fingerprint FROM central_rows"
                    " WHERE source_key=%s AND central_id IN (" + placeholders + ")",
                    [key] + ids)
        known = {r["central_id"]: r["fingerprint"] for r in cur.fetchall()}
        for row in rows:
            item = inspect_row(row)
            if known.get(item["central_id"]) == item["fingerprint"]:
                counts["unchanged"] += 1
                continue
            item["source_key"] = key
            values = tuple(item[field] for field in _FIELDS)
            insert = " (" + ",".join(_FIELDS) + ") VALUES (" + ",".join(["%s"] * len(_FIELDS)) + ")"
            updates = ",".join(f"{field}=VALUES({field})" for field in _FIELDS[2:])
            cur.execute("INSERT INTO central_rows" + insert +
                        " ON DUPLICATE KEY UPDATE " + updates + ", observed_at=NOW()", values)
            cur.execute("INSERT INTO central_changes" + insert, values)
            if item["verdict"] == "rejected":
                cur.execute(
                    "INSERT INTO rejected_messages (topic, reason, raw_excerpt, payload_len)"
                    " VALUES (%s, %s, %s, %s)",
                    ("central:" + config.CENTRAL_TABLE, item["reason"][:255],
                     item["raw"][:512], len(item["raw"].encode())),
                )
            counts[item["verdict"]] += 1
            messages.append(item)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    for item in messages:
        # JSON quoting blocks control-character/log-line injection.
        log.log(logging.WARNING if item["verdict"] == "rejected" else logging.INFO,
                "Central %s id=%s type=%s position=%s value=%s reason=%s",
                item["verdict"], item["central_id"], item["sensor_type"],
                json.dumps(item["position"], ensure_ascii=True),
                json.dumps(item["raw_value"], ensure_ascii=True), item["reason"])
    return counts


def save_status(conn, status, detail, counts):
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO central_pull_status"
            " (source_key,status,detail,scanned,accepted,rejected,unchanged,successful_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s," + ("NOW()" if status == "ok" else "NULL") + ")"
            " ON DUPLICATE KEY UPDATE status=VALUES(status),detail=VALUES(detail),"
            " scanned=VALUES(scanned),accepted=VALUES(accepted),rejected=VALUES(rejected),"
            " unchanged=VALUES(unchanged),checked_at=NOW()" +
            (",successful_at=NOW()" if status == "ok" else ""),
            (source_key(), status, detail[:255], *(counts.get(k, 0) for k in
              ("scanned", "accepted", "rejected", "unchanged"))),
        )
        conn.commit()
    finally:
        cur.close()


def scan(local_conn, central_conn):
    key = source_key()
    lock = local_conn.cursor()
    cur = None
    acquired = False
    counts = dict(scanned=0, accepted=0, rejected=0, unchanged=0)
    try:
        # All entry points use the same lock; duplicate processes cannot
        # create duplicate rejection events for the same observed revision.
        lock.execute("SELECT GET_LOCK(%s, 0)", ("farm-pull-" + key[:48],))
        acquired = lock.fetchone()[0] == 1
        if not acquired:
            raise ScanBusy("another Central scan is already running")
        save_status(local_conn, "scanning", "Full rescan in progress", counts)
        columns = central_columns(central_conn)
        log.info("Central scan table=%s columns=%s (all IDs, including updates)",
                 config.CENTRAL_TABLE, ",".join(columns))
        cur = central_conn.cursor(dictionary=True)
        cur.execute(row_query(columns))
        while True:
            rows = cur.fetchmany(getattr(config, "CENTRAL_PULL_BATCH", 200))
            if not rows:
                break
            batch = save_changed_batch(local_conn, rows, key)
            for name, count in batch.items():
                counts[name] += count
        save_status(local_conn, "ok", "Full scan completed; Central data is display-only", counts)
        log.info("PULL scanned=%d accepted_changes=%d rejected_changes=%d unchanged=%d",
                 *(counts[k] for k in ("scanned", "accepted", "rejected", "unchanged")))
        return counts
    finally:
        # A failed/unread Central cursor is disposed by its connection context.
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if acquired:
            lock.execute("SELECT RELEASE_LOCK(%s)", ("farm-pull-" + key[:48],))
            lock.fetchone()
        lock.close()
