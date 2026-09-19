"""Task2 regressions: actual scanner SQL against an in-memory DB adapter.

SQLite supplies real transactions; only MySQL metadata/upsert/lock syntax is
adapted. These are NOT MariaDB, Raspberry Pi or Central verification tests.
No network, hardware, production database, or installed driver is required.
"""
import contextlib
import importlib
import io
import json
import re
import sqlite3
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

PACKAGE = "_task2_farm_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(Path(__file__).resolve().parents[1] / "farm")]
sys.modules[PACKAGE] = package
config = importlib.import_module(PACKAGE + ".config")
pull = importlib.import_module(PACKAGE + ".central_pull")
chart = importlib.import_module(PACKAGE + ".anomaly_chart")
trigger = importlib.import_module(PACKAGE + ".challenge2")

# Import production SQL/read paths with a driver placeholder, never a real
# connection. Preserve other test modules' import state.
class DriverError(Exception):
    errno = 1146


mysql = types.ModuleType("mysql")
mysql.connector = types.ModuleType("mysql.connector")
mysql.connector.Error = DriverError
mysql.connector.connect = mock.Mock(side_effect=AssertionError("real database access forbidden"))
with mock.patch.dict(sys.modules, {"mysql": mysql, "mysql.connector": mysql.connector}):
    database = importlib.import_module(PACKAGE + ".database")
    sync = importlib.import_module(PACKAGE + ".sync")


@contextlib.contextmanager
def connected(conn):
    yield conn


class Cursor:
    def __init__(self, conn, dictionary=False):
        self.conn = conn
        self.cursor = conn.db.cursor()
        self.dictionary = dictionary
        self.synthetic = None

    def execute(self, sql, params=()):
        self.conn.queries.append((sql, params))
        self.synthetic = None
        if sql.startswith("SHOW COLUMNS"):
            self.synthetic = [(r[1],) for r in self.conn.db.execute("PRAGMA table_info(central)")]
            return
        if "GET_LOCK" in sql:
            self.synthetic = [(self.conn.lock_result,)]
            return
        if "RELEASE_LOCK" in sql:
            self.synthetic = [(1,)]
            return
        sql = sql.replace("%s", "?").replace("NOW()", "CURRENT_TIMESTAMP")
        sql = sql.replace("TIMESTAMPDIFF(SECOND, checked_at, CURRENT_TIMESTAMP)", "0")
        if "ON DUPLICATE KEY UPDATE" in sql:
            key = "source_key" if "INSERT INTO central_pull_status" in sql else "source_key,central_id"
            sql = sql.replace("ON DUPLICATE KEY UPDATE", f"ON CONFLICT ({key}) DO UPDATE SET")
            sql = re.sub(r"VALUES\((\w+)\)", r"excluded.\1", sql)
        if self.conn.fail_rejection and sql.startswith("INSERT INTO rejected_messages"):
            raise RuntimeError("simulated local write failure")
        self.cursor.execute(sql, params)

    def executemany(self, sql, params):
        self.conn.queries.append((sql, params))
        self.cursor.executemany(sql.replace("%s", "?"), params)

    def convert(self, row):
        if row is None:
            return None
        return dict(zip([c[0] for c in self.cursor.description], row)) if self.dictionary else row

    def fetchone(self):
        if self.synthetic is not None:
            return self.synthetic.pop(0) if self.synthetic else None
        return self.convert(self.cursor.fetchone())

    def fetchall(self):
        if self.synthetic is not None:
            rows, self.synthetic = self.synthetic, []
            return rows
        return [self.convert(row) for row in self.cursor.fetchall()]

    def fetchmany(self, size):
        self.conn.fetch_sizes.append(size)
        return [self.convert(row) for row in self.cursor.fetchmany(size)]

    def close(self):
        self.cursor.close()


class Connection:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.queries, self.fetch_sizes = [], []
        self.lock_result = 1
        self.fail_rejection = False

    def cursor(self, dictionary=False):
        return Cursor(self, dictionary)

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()


class CentralPullTests(unittest.TestCase):
    def setUp(self):
        self.settings = mock.patch.multiple(config, CENTRAL_TABLE="central", CENTRAL_PULL_BATCH=2,
                                            CENTRAL_POSITION_TYPES={}, create=True)
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.local, self.central = Connection(), Connection()
        self.addCleanup(self.local.db.close)
        self.addCleanup(self.central.db.close)
        fields = ("source_key TEXT, central_id INTEGER, fingerprint TEXT, position TEXT, raw_value TEXT,"
                  "source_time TEXT, sensor_type TEXT, numeric_value REAL, verdict TEXT, reason TEXT,"
                  "observed_at TEXT DEFAULT CURRENT_TIMESTAMP")
        self.local.db.executescript(
            "CREATE TABLE central_rows (" + fields + ", PRIMARY KEY(source_key, central_id));"
            "CREATE TABLE central_changes(event_id INTEGER PRIMARY KEY AUTOINCREMENT," + fields + ");"
            "CREATE TABLE rejected_messages (id INTEGER PRIMARY KEY,topic TEXT,reason TEXT,raw_excerpt TEXT,"
            "payload_len INTEGER, rejected_at TEXT DEFAULT CURRENT_TIMESTAMP);"
            "CREATE TABLE central_pull_status(source_key TEXT PRIMARY KEY,status TEXT,detail TEXT,"
            "scanned INT,accepted INT,rejected INT,unchanged INT,checked_at TEXT DEFAULT CURRENT_TIMESTAMP,"
            "successful_at TEXT);"
            "CREATE TABLE sensor_data(id INTEGER PRIMARY KEY,sensor_position TEXT,sensor_type TEXT,"
            "sensor_value REAL,created_at TEXT,synced INT DEFAULT 0,synced_at TEXT);"
            "INSERT INTO sensor_data VALUES(1,'zone-1','temperature',24.0,'2026-09-20 00:00:00',0,NULL);"
        )
        self.central.db.execute("CREATE TABLE central(id INTEGER PRIMARY KEY, sensor_position TEXT,"
                                "sensor_value, created_at TEXT)")

    def insert(self, rid, value=24, position="zone-1/temperature"):
        self.central.db.execute("INSERT INTO central VALUES(?,?,?,?)",
                                (rid, position, value, "2026-09-20 00:00:00"))
        self.central.commit()

    def scan(self):
        return pull.scan(self.local, self.central)

    def count(self, table):
        return self.local.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def test_update_of_old_id_is_detected_across_batches(self):
        for i in range(1, 6):
            self.insert(i)
        self.assertEqual(self.scan()["accepted"], 5)
        self.central.db.execute("UPDATE central SET sensor_value=999 WHERE id=1")
        counts = self.scan()
        self.assertEqual(counts, dict(scanned=5, accepted=0, rejected=1, unchanged=4))
        self.assertEqual(self.count("rejected_messages"), 1)
        self.assertEqual(self.local.db.execute("SELECT sensor_value FROM sensor_data").fetchone()[0], 24)
        self.assertEqual(self.count("sensor_data"), 1)
        self.assertTrue(all(n == 2 for n in self.central.fetch_sizes))

    def test_unknown_position_is_rejected_even_with_plausible_value(self):
        self.insert(1, 999, "zone-9")
        self.insert(2, 24, "zone-9")
        self.assertEqual(self.scan()["rejected"], 2)
        reason = self.local.db.execute("SELECT reason FROM central_rows LIMIT 1").fetchone()[0]
        self.assertIn("unknown sensor type", reason)

    def test_no_new_or_changed_data_is_not_counted_as_new_rejections(self):
        self.insert(1, 999)
        self.scan()
        self.assertEqual(self.scan()["unchanged"], 1)
        self.assertEqual(self.count("central_changes"), 1)
        self.assertEqual(self.count("rejected_messages"), 1)
        # No process-local dedupe: a second caller reads the persisted ledger.
        with mock.patch.object(pull, "log"):
            self.assertEqual(pull.scan(self.local, self.central)["unchanged"], 1)

    def test_invalid_row_corrected_then_changed_back_has_true_revision_history(self):
        self.insert(1, 999)
        self.scan()
        self.central.db.execute("UPDATE central SET sensor_value=25 WHERE id=1")
        self.assertEqual(self.scan()["accepted"], 1)
        self.central.db.execute("UPDATE central SET sensor_value=999 WHERE id=1")
        self.assertEqual(self.scan()["rejected"], 1)
        self.assertEqual(self.count("central_changes"), 3)
        self.assertEqual(self.count("rejected_messages"), 2)

    def test_valid_update_is_visible_but_never_changes_upload_queue(self):
        self.insert(1, 24)
        self.scan()
        self.central.db.execute("UPDATE central SET sensor_value=26 WHERE id=1")
        self.assertEqual(self.scan()["accepted"], 1)
        self.assertEqual(self.local.db.execute("SELECT numeric_value FROM central_rows").fetchone()[0], 26)
        self.assertEqual(self.local.db.execute("SELECT sensor_value,synced FROM sensor_data").fetchone(), (24, 0))

    def test_rejection_write_failure_rolls_back_fingerprint_and_is_retried(self):
        self.insert(1, 999)
        self.local.fail_rejection = True
        with self.assertRaises(RuntimeError):
            self.scan()
        self.assertEqual(self.count("central_rows"), 0)
        self.assertEqual(self.count("central_changes"), 0)
        self.local.fail_rejection = False
        self.assertEqual(self.scan()["rejected"], 1)

    def test_empty_scan_never_skips_later_low_id(self):
        self.assertEqual(self.scan()["scanned"], 0)
        self.insert(100, 24)
        self.scan()
        self.insert(1, 999)
        self.assertEqual(self.scan()["rejected"], 1)

    def test_explicit_sensor_type_column_is_respected(self):
        self.central.db.execute("ALTER TABLE central ADD COLUMN sensor_type TEXT")
        self.central.db.execute("INSERT INTO central VALUES(1,'zone-9',999,'2026-09-20','temperature')")
        self.assertEqual(self.scan()["rejected"], 1)
        row = self.local.db.execute("SELECT sensor_type,reason FROM central_rows").fetchone()
        self.assertEqual(row[0], "temperature")
        self.assertIn("outside plausible range", row[1])

    def test_mapping_change_revalidates_unchanged_raw_rows(self):
        self.insert(1, 24, "zone-9")
        self.assertEqual(self.scan()["rejected"], 1)
        with mock.patch.object(config, "CENTRAL_POSITION_TYPES", {"zone-9": "temperature"}):
            self.assertEqual(self.scan()["accepted"], 1)

    def test_parser_upgrade_revalidates_old_rejection_once_and_keeps_audit(self):
        position = "zone-2-canopy/humidity#L3283"
        self.insert(151, 60, position)
        # Reproduce the installed v1 parser and its persisted fingerprint.
        with mock.patch.object(pull, "_VALIDATOR_VERSION", 1), \
             mock.patch.object(pull, "_TYPE_ROW_SUFFIX", re.compile(r"(?!)")):
            self.assertEqual(self.scan()["rejected"], 1)
        self.assertEqual(self.scan(), dict(scanned=1, accepted=1, rejected=0, unchanged=0))
        self.assertEqual(self.local.db.execute(
            "SELECT position,sensor_type,verdict FROM central_rows"
        ).fetchone(), (position, "humidity", "accepted"))
        self.assertEqual(self.count("central_changes"), 2)
        self.assertEqual(self.count("rejected_messages"), 1)
        self.assertEqual(self.scan(), dict(scanned=1, accepted=0, rejected=0, unchanged=1))
        self.assertEqual(self.count("central_changes"), 2)
        self.assertEqual(self.count("rejected_messages"), 1)
        self.assertEqual(self.local.db.execute(
            "SELECT sensor_value,synced FROM sensor_data"
        ).fetchone(), (24, 0))

    def test_suffixed_old_id_attack_reaches_warning_graph_not_control_data(self):
        self.insert(1, 24, "zone-1/temperature#L3282")
        self.assertEqual(self.scan()["accepted"], 1)
        self.central.db.execute("UPDATE central SET sensor_value=999 WHERE id=1")
        self.assertEqual(self.scan()["rejected"], 1)
        with mock.patch.object(database, "local", lambda: connected(self.local)):
            result = database.challenge2_state()
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(result["rows"][0]["sensor_type"], "temperature")
        self.assertIn("outside plausible range", result["rows"][0]["reason"])
        self.assertEqual(result["charts"][0]["bad"][0]["label"], "999")
        self.assertEqual(self.local.db.execute(
            "SELECT sensor_value,synced FROM sensor_data"
        ).fetchone(), (24, 0))
        self.assertEqual(self.scan()["unchanged"], 1)
        self.assertEqual(self.count("rejected_messages"), 1)

    def test_inspection_returns_actual_fields_and_performs_no_writes(self):
        self.insert(1, 999, "zone-9")
        result = pull.inspect_central(self.central)
        self.assertEqual(result["sample"][0]["sensor_value"], 999)
        self.assertEqual(result["columns"], ["id", "sensor_position", "sensor_value", "created_at"])
        self.assertTrue(all(sql.startswith(("SHOW", "SELECT")) for sql, _ in self.central.queries))
        self.assertEqual(self.count("central_rows"), 0)

    def test_duplicate_scanner_is_blocked_without_writes(self):
        self.local.lock_result = 0
        self.insert(1, 999)
        with self.assertRaises(pull.ScanBusy):
            self.scan()
        self.assertEqual(self.count("central_rows"), 0)
        self.assertEqual(self.count("central_pull_status"), 0)

    def test_missing_schema_fails_visibly_and_never_marks_scan_ok(self):
        self.central.db.execute("ALTER TABLE central RENAME COLUMN sensor_value TO wrong_value")
        with self.assertRaisesRegex(ValueError, "missing required"):
            self.scan()
        state = self.local.db.execute("SELECT status FROM central_pull_status").fetchone()[0]
        self.assertNotEqual(state, "ok")
        diagnostic = pull.inspect_central(self.central)
        self.assertIn("wrong_value", diagnostic["columns"])

    def test_dashboard_sql_reads_changed_snapshot_and_rejection_graph(self):
        self.insert(1, 24)
        self.scan()
        self.central.db.execute("UPDATE central SET sensor_value=999 WHERE id=1")
        self.scan()
        with mock.patch.object(database, "local", lambda: connected(self.local)):
            result = database.challenge2_state()
        self.assertTrue(result["available"])
        self.assertFalse(result["stale"])
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(result["rows"][0]["raw_value"], "999")
        self.assertEqual(result["charts"][0]["good"][0]["label"], "24")
        self.assertEqual(result["charts"][0]["bad"][0]["label"], "999")

    def test_upload_format_is_unchanged_and_central_rows_are_not_uploaded(self):
        self.insert(10, 26)
        self.scan()
        with mock.patch.object(database, "local", lambda: connected(self.local)), \
             mock.patch.object(database, "central", lambda: connected(self.central)):
            self.assertEqual(sync.push_batch(), 1)
            self.assertEqual(sync.push_batch(), 0)
        rows = self.central.db.execute("SELECT sensor_position,sensor_value FROM central ORDER BY id").fetchall()
        self.assertEqual(rows, [("zone-1/temperature", 26), ("zone-1/temperature", 24)])

    def test_upload_failure_does_not_skip_pull(self):
        with mock.patch.object(sync, "push_batch", side_effect=DriverError("secret credentials")), \
             mock.patch.object(sync, "pull_batch") as scan, \
             self.assertLogs("sync", level="ERROR") as captured:
            self.assertFalse(sync.run_cycle())
        scan.assert_called_once_with()
        self.assertNotIn("secret credentials", " ".join(captured.output))

    def test_connection_failure_records_error_and_keeps_last_successful_scan(self):
        self.insert(1)
        self.scan()
        with mock.patch.object(database, "local", lambda: connected(self.local)), \
             mock.patch.object(database, "central", side_effect=DriverError("secret credentials")), \
             mock.patch.object(pull, "ensure_schema"):
            with self.assertRaises(DriverError):
                sync.pull_batch()
        state = self.local.db.execute("SELECT status,successful_at,detail FROM central_pull_status").fetchone()
        self.assertEqual(state[0], "error")
        self.assertIsNotNone(state[1])
        self.assertNotIn("secret credentials", state[2])
        self.assertEqual(self.count("central_rows"), 1)

    def test_dashboard_without_migration_reports_unavailable(self):
        with mock.patch.object(database, "local", side_effect=DriverError("private DB details")):
            result = database.challenge2_state()
        self.assertFalse(result["available"])
        self.assertIn("1146", result["error"])
        self.assertNotIn("private DB details", result["error"])

    def test_same_id_from_different_central_source_has_independent_state(self):
        self.insert(1, 999)
        self.scan()
        changed_db = dict(config.CENTRAL_DB, database="different_team_database")
        with mock.patch.object(config, "CENTRAL_DB", changed_db):
            self.assertEqual(self.scan()["rejected"], 1)
        self.assertEqual(self.count("central_rows"), 2)

    def test_setup_only_adds_local_ledger_tables(self):
        conn = mock.Mock()
        pull.ensure_schema(conn)
        statements = [call.args[0] for call in conn.cursor.return_value.execute.call_args_list]
        self.assertEqual(len(statements), 3)
        self.assertTrue(all(sql.startswith("CREATE TABLE IF NOT EXISTS central_") for sql in statements))
        self.assertTrue(all("ENGINE=InnoDB" in sql for sql in statements))
        self.assertFalse(any("ALTER TABLE" in sql for sql in statements))


class ValidationTests(unittest.TestCase):
    def row(self, value, pos="zone-1/temperature", **extra):
        return dict(id=1, sensor_value=value, sensor_position=pos, created_at="2026-09-20", **extra)

    def test_nonfinite_boolean_null_and_text_are_rejected(self):
        for value in (True, False, None, "abc", "NaN", "Infinity", float("inf")):
            with self.subTest(value=value):
                self.assertEqual(pull.inspect_row(self.row(value))["verdict"], "rejected")

    def test_known_typed_ranges_are_used_not_one_global_limit(self):
        for value, pos, expected in ((999, "zone-1/temperature", "rejected"),
                                     (-20, "zone-1/moisture", "rejected"),
                                     (999, "zone-1/ec", "accepted"),
                                     (24, "zone-2/air_temperature", "accepted")):
            with self.subTest(pos=pos):
                self.assertEqual(pull.inspect_row(self.row(value, pos))["verdict"], expected)

    def test_observed_canopy_suffixes_keep_raw_position_and_valid_type(self):
        # Exact shapes/values from the user's real Pi rejection query.
        samples = ((154, "rainfall", "0.00", 3286),
                   (153, "water_level", "23.10", 3285),
                   (152, "light", "73.33", 3284),
                   (151, "humidity", "60.00", 3283),
                   (150, "air_temperature", "24.00", 3282))
        for central_id, sensor_type, value, suffix in samples:
            with self.subTest(sensor_type=sensor_type):
                position = f"zone-2-canopy/{sensor_type}#L{suffix}"
                row = self.row(value, position)
                row["id"] = central_id
                item = pull.inspect_row(row)
                self.assertEqual(item["verdict"], "accepted")
                self.assertEqual(item["sensor_type"], sensor_type)
                self.assertEqual(item["position"], position)
                self.assertEqual(item["raw_value"], value)
                self.assertEqual(json.loads(item["raw"])["sensor_position"], position)
                self.assertEqual(pull.sensor_identity(row), ("zone-2-canopy", sensor_type))

    def test_suffixed_types_still_enforce_specific_ranges_and_numeric_checks(self):
        for value, sensor_type, expected in ((999, "temperature", "rejected"),
                                            (-20, "moisture", "rejected"),
                                            (999, "ec", "accepted"),
                                            (101, "rainfall", "rejected"),
                                            (101, "water_level", "rejected"),
                                            ("NaN", "temperature", "rejected"),
                                            (None, "humidity", "rejected")):
            with self.subTest(value=value, sensor_type=sensor_type):
                item = pull.inspect_row(self.row(value, f"zone-1/{sensor_type}#L3282"))
                self.assertEqual(item["verdict"], expected)
        alias = pull.inspect_row(self.row(24, "zone-1/temp#L3282"))
        self.assertEqual((alias["verdict"], alias["sensor_type"]), ("accepted", "temperature"))

    def test_suffix_does_not_accept_unknown_types_or_malformed_suffixes(self):
        positions = ("zone-9#L3282", "zone-1/unknown#L3282",
                     "zone-1/temperature#L", "zone-1/temperature#L-1",
                     "zone-1/temperature#L1extra", "zone-1/temperature#L1.5",
                     "zone-1/temperature#L1#L2", "zone-1/temperature#l1",
                     "zone-1/temperature#L\uff11", "zone-1/temperature#L1/unknown")
        for position in positions:
            with self.subTest(position=position):
                self.assertEqual(pull.inspect_row(self.row(24, position))["verdict"], "rejected")

    def test_suffix_does_not_override_explicit_or_mapped_type(self):
        position = "zone-1/temperature#L3282"
        self.assertEqual(pull.inspect_row(self.row(
            24, position, sensor_type="temperature"))["verdict"], "accepted")
        conflict = pull.inspect_row(self.row(24, position, sensor_type="ec"))
        self.assertEqual(conflict["verdict"], "rejected")
        self.assertIn("conflicting", conflict["reason"])
        with mock.patch.object(config, "CENTRAL_POSITION_TYPES", {position: "ec"}, create=True):
            conflict = pull.inspect_row(self.row(24, position))
            self.assertEqual(conflict["verdict"], "rejected")
            self.assertIn("conflicting", conflict["reason"])

    def test_conflicting_type_and_script_positions_are_rejected(self):
        self.assertEqual(pull.inspect_row(self.row(24, sensor_type="ec"))["verdict"], "rejected")
        self.assertEqual(pull.inspect_row(self.row(24, "<script>/temperature"))["verdict"], "rejected")

    def test_sql_identifier_cannot_include_injected_sql(self):
        with self.assertRaises(ValueError):
            pull.identifier("sensor; DROP TABLE sensor_data")

    def test_chart_is_real_data_only_and_no_invalid_coordinates(self):
        self.assertFalse(chart.comparison("temperature", [], [])["has_data"])
        result = chart.comparison("temperature", [{"value": 24, "created_at": datetime(2026, 9, 20)}],
                                  [{"value": 999, "observed_at": datetime(2026, 9, 20)},
                                   {"value": "NaN", "observed_at": datetime(2026, 9, 20)}])
        self.assertEqual([p["label"] for p in result["good"]], ["24"])
        self.assertEqual([p["label"] for p in result["bad"]], ["999"])

    def test_challenge_trigger_is_preview_only_without_explicit_start(self):
        with mock.patch.object(trigger, "publish_trigger") as send, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(trigger.main([]), 0)
        send.assert_not_called()
        self.assertEqual(trigger.request(), ("hackathon/hGroup10/Challenge2",
                                            {"type": "start_challenge", "message": "Please start Challenge 2"}))

    def test_trigger_publishes_once_qos1_not_retained_and_waits_for_ack(self):
        client = mock.Mock()
        message = client.publish.return_value
        message.rc = 0
        message.is_published.return_value = True
        client.loop_start.side_effect = lambda: client.on_connect(client, None, {}, 0)
        paho = types.ModuleType("paho")
        paho.mqtt = types.ModuleType("paho.mqtt")
        paho.mqtt.client = types.ModuleType("paho.mqtt.client")
        paho.mqtt.client.Client = mock.Mock(return_value=client)
        paho.mqtt.client.MQTT_ERR_SUCCESS = 0
        with mock.patch.dict(sys.modules, {"paho": paho, "paho.mqtt": paho.mqtt,
                                          "paho.mqtt.client": paho.mqtt.client}):
            trigger.publish_trigger()
        client.publish.assert_called_once()
        self.assertEqual(client.publish.call_args.kwargs, {"qos": 1, "retain": False})
        self.assertEqual(client.publish.call_args.args[0], "hackathon/hGroup10/Challenge2")
        message.wait_for_publish.assert_called_once_with(timeout=10)
        client.disconnect.assert_called_once()
        client.loop_stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
