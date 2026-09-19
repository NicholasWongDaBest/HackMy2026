"""Pi -> Central upload plus validated, display-only Central monitoring.

Readings are written locally first and flagged synced=0. This worker
drains the backlog to central on an interval. Pull the LAN cable and
readings keep accumulating; plug it back in and they catch up.

Run:  python3 -m farm.sync
"""
import logging
import argparse
import signal
import time

from . import config, database, central_pull

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
                f"INSERT INTO {central_pull.identifier(config.CENTRAL_TABLE)}"
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


def safe_error(exc):
    # Driver error text can include SQL, credentials, or connection details.
    if isinstance(exc, central_pull.ConfigurationError):
        return str(exc)
    code = getattr(exc, "errno", None)
    return f"{type(exc).__name__}" + (f" errno={code}" if code is not None else "")


def pull_batch():
    with database.local() as local_conn:
        central_pull.ensure_schema(local_conn)
        try:
            with database.central() as central_conn:
                return central_pull.scan(local_conn, central_conn)
        except central_pull.ScanBusy:
            log.warning("Another Central scanner is running; skipping duplicate pull")
            return None
        except Exception as exc:
            local_conn.rollback()
            central_pull.save_status(local_conn, "error", safe_error(exc) +
                                     "; scan incomplete, retrying from all IDs", {})
            raise


def run_cycle(pull_only=False):
    ok = True
    if not pull_only:
        try:
            n = push_batch()
            if n:
                database.log_sync(n, "ok", "push")
                log.info("PUSH %d rows -> Central", n)
        except Exception as exc:
            ok = False
            log.error("Upload failed (%s); local readings remain queued", safe_error(exc))
    # An upload/log failure must never prevent the independent pull.
    try:
        pull_batch()
    except Exception as exc:
        ok = False
        log.error("Pull failed (%s); next cycle rescans all IDs. "
                  "Use --inspect-central to check the actual schema.", safe_error(exc))
    return ok


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="one cycle, then exit")
    parser.add_argument("--pull-only", action="store_true", help="do not upload")
    parser.add_argument("--inspect-central", action="store_true",
                        help="print columns and five latest rows; no database writes")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    if args.inspect_central:
        try:
            with database.central() as conn:
                print(central_pull.raw_json(central_pull.inspect_central(conn)))
            return 0
        except Exception as exc:
            log.error("Central inspection failed (%s)", safe_error(exc))
            return 1
    running = {"on": True}
    signal.signal(signal.SIGINT, lambda *_: running.update(on=False))
    signal.signal(signal.SIGTERM, lambda *_: running.update(on=False))

    log.info("Sync started: %s; Central rows cannot enter irrigation control",
             "pull only" if args.pull_only else "push + validated pull")
    while running["on"]:
        ok = run_cycle(args.pull_only)
        if args.once:
            return 0 if ok else 1

        for _ in range(config.SYNC_INTERVAL_S):
            if not running["on"]:
                break
            time.sleep(1)

    log.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
