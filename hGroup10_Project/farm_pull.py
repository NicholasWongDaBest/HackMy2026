#!/usr/bin/env python3
"""
farm_pull.py  --  self-diagnosing PULL + validate for hGroup10.

WHY THIS EXISTS
---------------
The two-way sync only ever logged PUSH lines, never PULL.  This script
pulls central's rows DOWN, range-checks every value, and REJECTS the
impossible ones (that is the Challenge 2 attack: temp 888/999, moisture -20).

It is deliberately standalone and LOUD:
  * it reuses your project's own DB connections (the ones PUSH already uses,
    so credentials are guaranteed correct),
  * it introspects table columns instead of assuming them,
  * it prints a full plain-English report to the screen AND to ~/pull.log,
  * it never crashes the loop -- every error is caught and logged.

So even with NO internet on the Pi you can run it, read the report, and see
exactly what is happening.

HOW TO RUN (on the Pi, from the project folder)
-----------------------------------------------
    cd ~/hackathon/hGroup10_Project
    python3 farm_pull.py           # run ONCE, print a report, exit
    python3 farm_pull.py loop      # keep pulling every 15s
    tail -f ~/pull.log             # watch it in another window

Read the report.  It literally tells you the next thing to check.
"""

import os
import sys
import time
import re
import logging
import datetime

# ----------------------------------------------------------------------
# logging: screen + ~/pull.log
# ----------------------------------------------------------------------
LOG_PATH = os.path.expanduser("~/pull.log")
log = logging.getLogger("pull")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
for _h in (logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH)):
    _h.setFormatter(_fmt)
    log.addHandler(_h)


def banner(msg):
    log.info("=" * 60)
    log.info(msg)
    log.info("=" * 60)


# ----------------------------------------------------------------------
# find the project package so `import app.*` works no matter where we run
# ----------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (HERE, os.path.join(HERE, "app"), os.getcwd()):
    if cand not in sys.path:
        sys.path.insert(0, cand)

# ----------------------------------------------------------------------
# load config (for the central table name + any DB settings)
# ----------------------------------------------------------------------
C = None
for modname in ("app.config", "config"):
    try:
        C = __import__(modname, fromlist=["*"])
        log.info("loaded config from %s", modname)
        break
    except Exception as e:  # noqa
        log.info("could not import %s (%s)", modname, e)

def cfg(name, default):
    return getattr(C, name, default) if C else default

CENTRAL_TABLE = cfg("CENTRAL_TABLE", "Sensor_data_team10")
LOCAL_TABLE   = cfg("LOCAL_TABLE", "sensor_data")
REJECT_TABLE  = cfg("REJECT_TABLE", "rejected_messages")
TEAM_NAME     = cfg("TEAM_NAME", "hGroup10")

# ----------------------------------------------------------------------
# plausible ranges.  A value outside its range is an attack / bad reading.
# ----------------------------------------------------------------------
DEFAULT_RANGES = {
    "moisture":        (0.0, 100.0),
    "temperature":     (-40.0, 85.0),
    "ec":              (0.0, 20000.0),
    "humidity":        (0.0, 100.0),
    "ph":              (0.0, 14.0),
    "air_temperature": (-40.0, 80.0),
    "light":           (0.0, 100.0),
    "water_level":     (0.0, 100.0),
    "rainfall":        (0.0, 100.0),
}
RANGES = dict(DEFAULT_RANGES)
try:
    RANGES.update({k.lower(): tuple(v) for k, v in cfg("SENSOR_RANGES", {}).items()})
except Exception:
    pass

# normalise sensor-type spellings coming from central positions
TYPE_ALIASES = {
    "temp": "temperature",
    "temperature": "temperature",
    "moist": "moisture",
    "moisture": "moisture",
    "soil_moisture": "moisture",
    "ec": "ec",
    "conductivity": "ec",
    "hum": "humidity",
    "humidity": "humidity",
    "ph": "ph",
    "air_temp": "air_temperature",
    "air_temperature": "air_temperature",
    "light": "light",
    "lux": "light",
    "water": "water_level",
    "water_level": "water_level",
    "rain": "rainfall",
    "rainfall": "rainfall",
}


def normalise_type(raw):
    if not raw:
        return None
    t = re.sub(r"[^a-z0-9_]+", "_", str(raw).strip().lower()).strip("_")
    return TYPE_ALIASES.get(t, t)


def parse_position(pos):
    """central sensor_position -> (sensor_type or None).  Handles
    'zone-1/moisture', 'zone-2-canopy/temperature', bare 'moisture', etc."""
    if pos is None:
        return None
    s = str(pos)
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    # also handle 'zone-2-canopy-temperature'
    s = s.replace("-", "_")
    # take the trailing word if it names a known type
    parts = [p for p in s.split("_") if p]
    for p in reversed(parts):
        t = normalise_type(p)
        if t in RANGES:
            return t
    return normalise_type(s)


# ----------------------------------------------------------------------
# DB connections -- reuse the project's own, since PUSH already works
# ----------------------------------------------------------------------
def _try_callables(mod, names):
    for n in names:
        fn = getattr(mod, n, None)
        if callable(fn):
            try:
                conn = fn()
                if conn is not None:
                    log.info("connected via %s.%s()", mod.__name__, n)
                    return conn
            except Exception as e:  # noqa
                log.info("%s.%s() failed: %s", mod.__name__, n, e)
    return None


def _import(modname):
    try:
        return __import__(modname, fromlist=["*"])
    except Exception as e:  # noqa
        log.info("no module %s (%s)", modname, e)
        return None


DB_MOD   = _import("app.database") or _import("database")
SYNC_MOD = _import("app.sync") or _import("sync")


def _find_conn_dicts():
    """Find dict-shaped connection configs in config.py, e.g.
    LOCAL_DB = {'host':..,'user':..,'password':..,'database':..}."""
    found = {}
    if not C:
        return found
    for name in dir(C):
        if name.startswith("_"):
            continue
        try:
            v = getattr(C, name)
        except Exception:
            continue
        if isinstance(v, dict) and any(k in v for k in
                                       ("host", "user", "database", "password")):
            found[name] = v
    return found


def _is_local(d):
    h = str(d.get("host", "")).lower()
    db = str(d.get("database", "")).lower()
    return h in ("127.0.0.1", "localhost", "::1") or "local" in db


def connect_local():
    for mod in (DB_MOD, SYNC_MOD):
        if mod:
            c = _try_callables(mod, ("connect", "get_conn", "get_connection",
                                     "connection", "open_local", "_connect",
                                     "local_conn", "conn"))
            if c:
                return c
    dicts = _find_conn_dicts()
    # prefer a dict named *LOCAL*, else one that looks local, else any
    chosen = None
    for name, d in dicts.items():
        if "LOCAL" in name.upper():
            chosen = (name, d); break
    if not chosen:
        for name, d in dicts.items():
            if _is_local(d):
                chosen = (name, d); break
    if not chosen and dicts:
        chosen = next(iter(dicts.items()))
    return _connect_dict("LOCAL", chosen,
                         fallback=dict(host="127.0.0.1", user="farm",
                                       password="farm", database="farm_local"))


def connect_central():
    for mod in (SYNC_MOD, DB_MOD):
        if mod:
            c = _try_callables(mod, ("connect_central", "_connect_central",
                                     "central_conn", "open_central",
                                     "get_central", "_central"))
            if c:
                return c
    dicts = _find_conn_dicts()
    chosen = None
    for name, d in dicts.items():
        if any(k in name.upper() for k in ("CENTRAL", "REMOTE", "ADMIN")):
            chosen = (name, d); break
    if not chosen:  # any dict that is NOT the local one
        for name, d in dicts.items():
            if not _is_local(d):
                chosen = (name, d); break
    if not chosen and dicts:
        chosen = next(iter(dicts.items()))
    return _connect_dict("CENTRAL", chosen, fallback=None)


def _connect_dict(label, chosen, fallback):
    import mysql.connector
    if chosen:
        name, params = chosen
        log.info("%s: using config['%s']  host=%s db=%s user=%s", label, name,
                 params.get("host"), params.get("database"), params.get("user"))
        return mysql.connector.connect(**params)
    if fallback:
        log.info("%s: no config dict found, trying fallback host=%s db=%s",
                 label, fallback.get("host"), fallback.get("database"))
        return mysql.connector.connect(**fallback)
    raise RuntimeError("no %s connection settings found in config.py" % label)


# ----------------------------------------------------------------------
# schema introspection -- adapt to whatever the tables actually look like
# ----------------------------------------------------------------------
def columns(conn, table):
    cur = conn.cursor()
    try:
        cur.execute("SHOW COLUMNS FROM `%s`" % table)
        cols = [r[0] for r in cur.fetchall()]
        return cols
    except Exception as e:  # noqa
        log.info("SHOW COLUMNS %s failed: %s", table, e)
        return []
    finally:
        cur.close()


def pick(cols, *cands):
    low = {c.lower(): c for c in cols}
    for cand in cands:
        if cand.lower() in low:
            return low[cand.lower()]
    return None


# ----------------------------------------------------------------------
# high-water mark, stored locally so we process each central row once
# ----------------------------------------------------------------------
def ensure_state(conn):
    cur = conn.cursor()
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS sync_state "
                    "(k VARCHAR(64) PRIMARY KEY, v BIGINT)")
        conn.commit()
    except Exception as e:  # noqa
        log.info("ensure_state: %s", e)
    finally:
        cur.close()


def get_hwm(conn):
    cur = conn.cursor()
    try:
        cur.execute("SELECT v FROM sync_state WHERE k='central_hwm'")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0
    finally:
        cur.close()


def set_hwm(conn, val):
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO sync_state(k,v) VALUES('central_hwm',%s) "
                    "ON DUPLICATE KEY UPDATE v=%s", (val, val))
        conn.commit()
    except Exception as e:  # noqa
        log.info("set_hwm: %s", e)
    finally:
        cur.close()


# ----------------------------------------------------------------------
# record a rejection into rejected_messages (adapt to its columns)
# ----------------------------------------------------------------------
def record_rejection(local, source, reason, payload):
    cols = columns(local, REJECT_TABLE)
    if not cols:
        # create a minimal table so rejections are never lost
        cur = local.cursor()
        try:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS `%s` ("
                "id INT AUTO_INCREMENT PRIMARY KEY,"
                "source VARCHAR(128), reason VARCHAR(255),"
                "payload TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
                % REJECT_TABLE)
            local.commit()
            cols = columns(local, REJECT_TABLE)
        except Exception as e:  # noqa
            log.info("could not create %s: %s", REJECT_TABLE, e)
            return
        finally:
            cur.close()

    src_c = pick(cols, "source", "origin", "src", "sender")
    rsn_c = pick(cols, "reason", "error", "message", "detail", "note")
    pay_c = pick(cols, "payload", "raw", "data", "body", "value")
    tim_c = pick(cols, "created_at", "ts", "timestamp", "time")

    fields, vals = [], []
    if src_c: fields.append(src_c); vals.append(source)
    if rsn_c: fields.append(rsn_c); vals.append(reason)
    if pay_c: fields.append(pay_c); vals.append(payload)
    if tim_c: fields.append(tim_c); vals.append(datetime.datetime.now())
    if not fields:
        return
    sql = "INSERT INTO `%s` (%s) VALUES (%s)" % (
        REJECT_TABLE, ",".join("`%s`" % f for f in fields),
        ",".join(["%s"] * len(fields)))
    cur = local.cursor()
    try:
        cur.execute(sql, vals)
        local.commit()
    except Exception as e:  # noqa
        log.info("record_rejection insert failed: %s", e)
    finally:
        cur.close()


# ----------------------------------------------------------------------
# one pull cycle
# ----------------------------------------------------------------------
def pull_once(local, central):
    ccols = columns(central, CENTRAL_TABLE)
    if not ccols:
        log.info("!! cannot see central table `%s` -- wrong name or no access",
                 CENTRAL_TABLE)
        return

    id_c  = pick(ccols, "id", "ID", "row_id")
    pos_c = pick(ccols, "sensor_position", "position", "sensor", "node", "topic")
    val_c = pick(ccols, "sensor_value", "value", "reading", "val")
    tim_c = pick(ccols, "created_at", "timestamp", "ts", "time")

    log.info("central `%s` columns=%s  (id=%s pos=%s val=%s time=%s)",
             CENTRAL_TABLE, ccols, id_c, pos_c, val_c, tim_c)
    if not (id_c and pos_c and val_c):
        log.info("!! central table missing id/position/value column -- stop")
        return

    hwm = get_hwm(local)

    cur = central.cursor()
    try:
        cur.execute("SELECT COUNT(*), COALESCE(MAX(`%s`),0) FROM `%s`"
                    % (id_c, CENTRAL_TABLE))
        total, maxid = cur.fetchone()
    except Exception as e:  # noqa
        log.info("!! count on central failed: %s", e)
        cur.close()
        return
    log.info("central has %s rows total, max id=%s, our hwm=%s",
             total, maxid, hwm)

    order_cols = "`%s`,`%s`,`%s`" % (id_c, pos_c, val_c) + (
        (",`%s`" % tim_c) if tim_c else "")
    try:
        cur.execute("SELECT %s FROM `%s` WHERE `%s` > %%s ORDER BY `%s` ASC"
                    % (order_cols, CENTRAL_TABLE, id_c, id_c), (hwm,))
        rows = cur.fetchall()
    except Exception as e:  # noqa
        log.info("!! select new rows failed: %s", e)
        cur.close()
        return
    finally:
        cur.close()

    if not rows:
        log.info("PULL  0 new rows (nothing above hwm=%s yet)", hwm)
        if maxid > hwm:  # shouldn't happen, but never get stuck
            set_hwm(local, maxid)
        return

    pulled = rejected = accepted = 0
    new_hwm = hwm
    for r in rows:
        rid, pos, val = r[0], r[1], r[2]
        new_hwm = max(new_hwm, int(rid))
        pulled += 1
        stype = parse_position(pos)
        try:
            fval = float(val)
        except Exception:
            rejected += 1
            record_rejection(local, "central:%s" % CENTRAL_TABLE,
                             "non-numeric value",
                             "id=%s pos=%s val=%r" % (rid, pos, val))
            log.info("  REJECT id=%s pos=%s val=%r  (not a number)", rid, pos, val)
            continue
        lo_hi = RANGES.get(stype)
        if lo_hi and not (lo_hi[0] <= fval <= lo_hi[1]):
            rejected += 1
            record_rejection(
                local, "central:%s" % CENTRAL_TABLE,
                "%s reading %s outside [%s,%s]" % (stype, fval, lo_hi[0], lo_hi[1]),
                "id=%s pos=%s val=%s" % (rid, pos, fval))
            log.info("  REJECT id=%s %s=%s  OUTSIDE [%s,%s]  <-- ATTACK CAUGHT",
                     rid, stype, fval, lo_hi[0], lo_hi[1])
        else:
            accepted += 1

    set_hwm(local, new_hwm)
    log.info("PULL  %s new rows  ->  %s ok, %s REJECTED   (hwm now %s)",
             pulled, accepted, rejected, new_hwm)
    if rejected:
        log.info(">> %s bad value(s) logged to `%s` -- check the dashboard "
                 "Rejection Log / Challenge 2 chart", rejected, REJECT_TABLE)


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------
def main():
    loop = len(sys.argv) > 1 and sys.argv[1].lower().startswith("loop")
    banner("farm_pull  team=%s  central_table=%s" % (TEAM_NAME, CENTRAL_TABLE))

    try:
        local = connect_local()
    except Exception as e:  # noqa
        log.info("!! LOCAL DB connection FAILED: %s", e)
        log.info("   -> pull cannot store rejections. Fix local DB creds in "
                 "app/config.py, then rerun.")
        return
    try:
        central = connect_central()
    except Exception as e:  # noqa
        log.info("!! CENTRAL DB connection FAILED: %s", e)
        log.info("   -> we can't read admin's data. Check CENTRAL_* settings "
                 "in app/config.py and that the Pi can reach central.")
        return

    ensure_state(local)
    log.info("local table columns: %s", columns(local, LOCAL_TABLE))

    if not loop:
        pull_once(local, central)
        banner("done (one shot).  run 'python3 farm_pull.py loop' to keep pulling")
        return

    log.info("looping every 15s -- Ctrl-C to stop")
    while True:
        try:
            pull_once(local, central)
        except Exception as e:  # noqa  -- never let the loop die
            log.info("cycle error (continuing): %s", e)
        time.sleep(15)


if __name__ == "__main__":
    main()
