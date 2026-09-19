"""Pi -> central synchronisation worker.

Readings are written locally first and flagged synced=0. This worker
drains the backlog to central on an interval. Pull the LAN / WiFi and
readings keep accumulating; plug it back in and they catch up -- the
Alien Attack (Challenge 3) bonus: automatic sync, no manual trigger.

Idempotency: each row is pushed with a central key that includes the
local id (`zone-1/moisture#L42`). Already-present keys are skipped, so a
crash between central commit and local flag cannot create duplicates.

Run:  python3 -m farm.sync
"""
import logging
import signal
import time

import mysql.connector

from . import config, database

log = logging.getLogger("sync")


def push_batch() -> int:
    """Move up to SYNC_BATCH unsynced rows to central. Returns row count.

    Rows are only flagged synced after central commits (or after we confirm
    they are already present), so a failure mid-push means they are
    retried, never lost, and never duplicated.
    """
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

        keys = [database.central_key_for_row(r) for r in rows]
        key_by_id = {r["id"]: database.central_key_for_row(r) for r in rows}

        with database.central() as cconn:
            ccur = cconn.cursor()
            placeholders = ",".join(["%s"] * len(keys))
            ccur.execute(
                f"SELECT sensor_position FROM {config.CENTRAL_TABLE}"
                f" WHERE sensor_position IN ({placeholders})",
                keys,
            )
            already = {r[0] for r in ccur.fetchall()}

            to_insert = [r for r in rows if key_by_id[r["id"]] not in already]
            if to_insert:
                ccur.executemany(
                    f"INSERT INTO {config.CENTRAL_TABLE}"
                    " (sensor_position, sensor_value, created_at)"
                    " VALUES (%s, %s, %s)",
                    [
                        (key_by_id[r["id"]], r["sensor_value"], r["created_at"])
                        for r in to_insert
                    ],
                )
                cconn.commit()
                log.info(
                    "inserted %d new rows (%d already on central)",
                    len(to_insert),
                    len(rows) - len(to_insert),
                )
            else:
                log.info("all %d pending rows already on central; marking synced", len(rows))

        ids = [r["id"] for r in rows]
        id_placeholders = ",".join(["%s"] * len(ids))
        lcur2 = lconn.cursor()
        lcur2.execute(
            f"UPDATE sensor_data SET synced = 1, synced_at = NOW()"
            f" WHERE id IN ({id_placeholders})",
            ids,
        )
        lconn.commit()
        return len(rows)


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    running = {"on": True}
    signal.signal(signal.SIGINT, lambda *_: running.update(on=False))
    signal.signal(signal.SIGTERM, lambda *_: running.update(on=False))

    while running["on"]:
        try:
            n = push_batch()
            if n:
                database.log_sync(n, "ok")
                log.info("pushed/confirmed %d rows to central", n)
            else:
                # Heartbeat so the dashboard can tell "online, idle" from
                # "never synced". Cheap SELECT of zero rows still proves
                # the central link is up.
                try:
                    with database.central() as cconn:
                        cconn.cursor().execute("SELECT 1")
                    database.log_sync(0, "ok", "heartbeat")
                except mysql.connector.Error as exc:
                    database.log_sync(0, "error", str(exc))
                    log.error("central unreachable, buffering locally: %s", exc)
        except mysql.connector.Error as exc:
            database.log_sync(0, "error", str(exc))
            log.error("sync failed, will retry: %s", exc)
        except Exception as exc:
            database.log_sync(0, "error", str(exc))
            log.exception("unexpected sync error")

        for _ in range(config.SYNC_INTERVAL_S):
            if not running["on"]:
                break
            time.sleep(1)

    log.info("stopped")


if __name__ == "__main__":
    main()
