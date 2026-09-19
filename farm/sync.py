"""Pi -> central synchronisation worker.

Readings are written locally first and flagged synced=0. This worker
drains the backlog to central on an interval. Pull the LAN cable and
readings keep accumulating; plug it back in and they catch up.

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

    Rows are only flagged synced after central commits, so a failure
    mid-push means they are retried, never lost.
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

        with database.central() as cconn:
            ccur = cconn.cursor()
            ccur.executemany(
                # Central has no sensor_type column, so the measurand is
                # folded into sensor_position: "zone-1/moisture".
                f"INSERT INTO {config.CENTRAL_TABLE}"
                " (sensor_position, sensor_value, created_at)"
                " VALUES (%s, %s, %s)",
                [
                    (f"{r['sensor_position']}/{r['sensor_type']}",
                     r["sensor_value"], r["created_at"])
                    for r in rows
                ],
            )
            cconn.commit()

        ids = [r["id"] for r in rows]
        placeholders = ",".join(["%s"] * len(ids))
        lcur2 = lconn.cursor()
        lcur2.execute(
            f"UPDATE sensor_data SET synced = 1, synced_at = NOW()"
            f" WHERE id IN ({placeholders})",
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
                log.info("pushed %d rows to central", n)
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
