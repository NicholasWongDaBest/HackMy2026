"""Two-way Pi <-> central synchronisation.

PUSH  (Pi -> central): local readings with synced=0 are drained upward.
PULL  (central -> Pi): rows central has that we have not seen are pulled
                       DOWN, and every one is range-validated on the way
                       in. Impossible values -- the Challenge 2 attack
                       (temperature 888-999, moisture -20, ...) -- are
                       REJECTED into rejected_messages and never stored.
                       Legitimate new rows are stored locally as origin
                       'central' and are never pushed back up (no loop).

The pull is the security gate the brief asks for: the attack is injected
into central, so the only way to catch it is to inspect what central
sends us. A push-only sync can never see it.

Run:  python3 -m app.sync      (ONE instance only)
"""
import json
import logging
import signal
import time

import mysql.connector

from . import config, database, validation

log = logging.getLogger("sync")


# ---------------------------------------------------------------------
# schema: an origin column + a tiny high-water-mark table. Idempotent,
# so it is safe to run on every start.
# ---------------------------------------------------------------------
def ensure_schema() -> None:
    with database.local() as conn:
        cur = conn.cursor()
        cur.execute(
            "ALTER TABLE sensor_data "
            "ADD COLUMN IF NOT EXISTS origin VARCHAR(16) NOT NULL DEFAULT 'local'"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS sync_state ("
            " k VARCHAR(32) PRIMARY KEY, v BIGINT NOT NULL DEFAULT 0)"
        )
        conn.commit()


def _get_hwm() -> int:
    with database.local() as conn:
        cur = conn.cursor()
        cur.execute("SELECT v FROM sync_state WHERE k = 'central_hwm'")
        row = cur.fetchone()
        return int(row[0]) if row else 0


def _set_hwm(value: int) -> None:
    with database.local() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sync_state (k, v) VALUES ('central_hwm', %s)"
            " ON DUPLICATE KEY UPDATE v = %s",
            (value, value),
        )
        conn.commit()


def _split_position(pos: str):
    """Central stores the measurand folded into the position as
    'zone-1/moisture'. Split it back into (base_position, sensor_type)."""
    pos = (pos or "").strip()
    if "/" in pos:
        base, stype = pos.rsplit("/", 1)
        return base or "central", stype.strip().lower()
    # No type marker: treat the whole thing as the type if it names a known
    # sensor, else leave the type unknown so validation rejects it.
    return "central", pos.lower()


# ---------------------------------------------------------------------
# PUSH: Pi -> central
# ---------------------------------------------------------------------
def push_batch() -> int:
    with database.local() as lconn:
        lcur = lconn.cursor(dictionary=True)
        lcur.execute(
            "SELECT id, sensor_position, sensor_value, created_at, sensor_type"
            " FROM sensor_data WHERE synced = 0 ORDER BY id LIMIT %s",
            (config.SYNC_BATCH,),
        )
        rows = lcur.fetchall()
        if not rows:
            return 0

        with database.central() as cconn:
            ccur = cconn.cursor()
            ccur.executemany(
                f"INSERT INTO {config.CENTRAL_TABLE}"
                " (sensor_position, sensor_value, created_at) VALUES (%s, %s, %s)",
                [
                    (f"{r['sensor_position']}/{r['sensor_type']}",
                     r["sensor_value"], r["created_at"])
                    for r in rows
                ],
            )
            cconn.commit()

        ids = [r["id"] for r in rows]
        ph = ",".join(["%s"] * len(ids))
        lcur2 = lconn.cursor()
        lcur2.execute(
            f"UPDATE sensor_data SET synced = 1, synced_at = NOW() WHERE id IN ({ph})",
            ids,
        )
        lconn.commit()
        return len(rows)


# ---------------------------------------------------------------------
# PULL: central -> Pi, validating every row
# ---------------------------------------------------------------------
def _is_our_echo(base_pos, stype, value, created_at) -> bool:
    """A row we pushed comes back on pull. Recognise it so we don't store
    a duplicate: same position, type, value and timestamp already local."""
    with database.local() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM sensor_data WHERE sensor_position=%s AND sensor_type=%s"
            " AND sensor_value=%s AND created_at=%s LIMIT 1",
            (base_pos, stype, value, created_at),
        )
        return cur.fetchone() is not None


def _store_from_central(base_pos, stype, value, created_at) -> None:
    with database.local() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sensor_data"
            " (sensor_position, sensor_value, sensor_type, created_at, synced, origin)"
            " VALUES (%s, %s, %s, %s, 1, 'central')",
            (base_pos, value, stype, created_at),
        )
        conn.commit()


def pull_batch() -> tuple:
    """Returns (stored, rejected, skipped). Rejected == attacks caught."""
    hwm = _get_hwm()
    with database.central() as cconn:
        ccur = cconn.cursor(dictionary=True)
        ccur.execute(
            f"SELECT id, sensor_position, sensor_value, created_at"
            f" FROM {config.CENTRAL_TABLE} WHERE id > %s ORDER BY id LIMIT %s",
            (hwm, config.SYNC_BATCH),
        )
        rows = ccur.fetchall()
    if not rows:
        return (0, 0, 0)

    stored = rejected = skipped = 0
    new_hwm = hwm
    for r in rows:
        new_hwm = max(new_hwm, int(r["id"]))
        base_pos, stype = _split_position(r["sensor_position"])
        try:
            value = float(r["sensor_value"])
        except (TypeError, ValueError):
            database.record_rejection(
                f"central:{config.CENTRAL_TABLE}",
                f"non-numeric sensor_value '{r['sensor_value']}'",
                json.dumps(r, default=str).encode(),
            )
            rejected += 1
            continue

        if _is_our_echo(base_pos, stype, value, r["created_at"]):
            skipped += 1
            continue

        # New data from central. Validate it exactly like an MQTT reading.
        try:
            validation.check_range(stype, value)
        except validation.Rejected as exc:
            # THE ATTACK IS CAUGHT HERE.
            database.record_rejection(
                f"central:{config.CENTRAL_TABLE}",
                str(exc),
                json.dumps(r, default=str).encode(),
            )
            rejected += 1
            continue

        _store_from_central(base_pos, stype, value, r["created_at"])
        stored += 1

    _set_hwm(new_hwm)
    return (stored, rejected, skipped)


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    ensure_schema()
    log.info("two-way sync started (push up, pull down + validate)")

    running = {"on": True}
    signal.signal(signal.SIGINT, lambda *_: running.update(on=False))
    signal.signal(signal.SIGTERM, lambda *_: running.update(on=False))

    while running["on"]:
        # --- push ---
        try:
            n = push_batch()
            if n:
                database.log_sync(n, "ok", "push")
                log.info("PUSH  %d rows -> central", n)
        except mysql.connector.Error as exc:
            database.log_sync(0, "error", f"push: {exc}")
            log.error("push failed, will retry: %s", exc)
        except Exception as exc:
            database.log_sync(0, "error", f"push: {exc}")
            log.exception("unexpected push error")

        # --- pull + validate ---
        try:
            stored, rejected, skipped = pull_batch()
            if stored or rejected:
                database.log_sync(stored, "ok", f"pull stored={stored} rejected={rejected}")
                log.info("PULL  central -> Pi: stored %d, REJECTED %d anomalies, skipped %d echoes",
                         stored, rejected, skipped)
        except mysql.connector.Error as exc:
            database.log_sync(0, "error", f"pull: {exc}")
            log.error("pull failed, will retry: %s", exc)
        except Exception as exc:
            database.log_sync(0, "error", f"pull: {exc}")
            log.exception("unexpected pull error")

        for _ in range(config.SYNC_INTERVAL_S):
            if not running["on"]:
                break
            time.sleep(1)

    log.info("stopped")


if __name__ == "__main__":
    main()
