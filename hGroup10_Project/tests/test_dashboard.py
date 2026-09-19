"""Dashboard HTTP regressions with no database, controller, or hardware access."""
import importlib.util
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


FLASK_AVAILABLE = importlib.util.find_spec("flask") is not None
if FLASK_AVAILABLE:
    # Keep framework modules loaded before patch.dict snapshots sys.modules.
    # Otherwise restoring that dictionary unloads Jinja's Namespace class,
    # while the imported Flask app still holds references to the old class.
    import flask  # noqa: F401
    import jinja2  # noqa: F401

FARM_DIRECTORY = Path(__file__).resolve().parents[1] / "farm"


class PageElements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def by_id(self, element_id):
        return next(attrs for _, attrs in self.elements
                    if attrs.get("id") == element_id)

    def live_regions(self):
        return [attrs["id"] for _, attrs in self.elements
                if "data-live-region" in attrs]


@unittest.skipUnless(FLASK_AVAILABLE, "Flask is not installed in this interpreter")
class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.controller = mock.Mock()
        self.status = {
            "pumps": {1: {
                "running": False, "pin": 25, "run_seconds": 0,
                "rest_seconds": 90,
                "link": {"error": None, "connected": True},
            }},
            "sensor_health": {
                "state": "online", "zone": "zone-1",
                "affected_sensors": ["moisture", "temperature", "ec"],
                "can_irrigate": True, "error": None,
                "seconds_since_success": 1,
            },
            "sensor_error": None,
            "manual_override_s": 0,
            "thresholds": {
                "max_run_s": 10, "on_below": 30,
                "off_above": 45, "min_rest_s": 60,
            },
            "last_decision": None,
        }
        self.controller.status.return_value = self.status
        self.controller.manual.return_value = (True, "started")

        self.database = types.ModuleType("farm.database")
        self.reading = {
            "sensor_position": "zone-1", "sensor_type": "moisture",
            "sensor_value": 42.5, "created_at": "2026-09-20 00:00:00",
            "synced": False,
        }
        self.database.latest_selfcare = mock.Mock(return_value=None)
        self.database.recent_readings = mock.Mock(return_value=[self.reading])
        self.database.rejection_summary = mock.Mock(return_value=(0, []))
        self.database.sync_status = mock.Mock(return_value=(1, None))
        self.database.latest_per_sensor = mock.Mock(return_value=[self.reading])
        self.database.recent_decisions = mock.Mock(return_value=[])
        self.central_state = {
            "available": True, "error": None, "status": {
                "status": "ok", "checked_at": "2026-09-20 00:00:00",
                "scanned": 2, "unchanged": 1, "detail": "Full scan completed",
            }, "stale": False, "accepted": 1, "rejected": 0, "rows": [], "charts": [],
            "evidence": [], "plotted_rejections": 0,
        }
        self.database.challenge2_state = mock.Mock(return_value=self.central_state)

        # Import the real routes and templates against an isolated package.
        # Existing integration tests replace farm modules globally; neither
        # borrow those replacements nor leave ours behind for another test.
        package = types.ModuleType("farm")
        package.__path__ = [str(FARM_DIRECTORY)]
        package.config = types.ModuleType("farm.config")
        package.config.TEAM_NAME = "hGroup10"
        package.config.SENSOR_POSITION = "zone-1"
        package.control = types.ModuleType("farm.control")
        package.control.get_controller = mock.Mock(return_value=self.controller)
        package.database = self.database
        name = "farm._dashboard_http_test"
        spec = importlib.util.spec_from_file_location(name, FARM_DIRECTORY / "app.py")
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {
            "farm": package, "farm.config": package.config,
            "farm.control": package.control, "farm.database": self.database,
            name: module,
        }):
            spec.loader.exec_module(module)
        self.app = module.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_initial_page_has_updates_script_without_forced_refresh(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        elements = PageElements(response.get_data(as_text=True))
        self.assertFalse(any(
            tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh"
            for tag, attrs in elements.elements
        ))
        self.assertTrue(any(
            tag == "script" and attrs.get("src") == "/static/dashboard.js"
            and "defer" in attrs
            for tag, attrs in elements.elements
        ))
        self.assertNotIn("disabled", elements.by_id("pump-start"))
        self.controller.start.assert_not_called()
        self.controller.manual.assert_not_called()

    def test_updates_include_each_live_region_without_shell_or_control_forms(self):
        page = PageElements(self.client.get("/").get_data(as_text=True))
        response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        fragments = PageElements(response.get_data(as_text=True))
        expected = {
            "system-status", "hero-metrics", "status-ribbon", "sensor-alerts",
            "sensor-readings", "pump-status", "override-status",
            "latest-decision", "history-summary", "automation-audit",
            "reading-history", "validation-history",
            "central-monitor",
        }
        self.assertEqual(set(fragments.live_regions()), expected)
        self.assertEqual(len(fragments.live_regions()), len(expected))
        self.assertEqual(set(page.live_regions()), expected)
        self.assertFalse(any(tag in ("html", "head", "body", "script", "form")
                             for tag, _ in fragments.elements))
        self.controller.start.assert_not_called()
        self.controller.manual.assert_not_called()
        self.controller.resume_auto.assert_not_called()

    def test_updates_report_sensor_failure_then_recovery(self):
        health = self.status["sensor_health"]
        health.update(state="offline", can_irrigate=False, error="Modbus timeout")
        self.status["sensor_error"] = "Modbus timeout"
        offline = self.client.get("/api/dashboard").get_data(as_text=True)
        self.assertIn("MODBUS sensor offline", offline)
        self.assertIn("Offline - last known", offline)
        self.assertEqual(PageElements(offline).by_id("pump-status")["data-start-allowed"],
                         "false")
        self.assertIn("danger", PageElements(offline).by_id("system-status")["class"])

        health.update(state="online", can_irrigate=True, error=None)
        self.status["sensor_error"] = None
        self.reading["sensor_value"] = 43.2
        recovered = self.client.get("/api/dashboard").get_data(as_text=True)
        self.assertNotIn("MODBUS sensor offline", recovered)
        self.assertNotIn("Offline - last known", recovered)
        self.assertIn("43.2", recovered)
        self.assertEqual(PageElements(recovered).by_id("pump-status")["data-start-allowed"],
                         "true")
        self.controller.manual.assert_not_called()

    def test_central_update_is_visible_and_escaped_without_changing_physical_readings(self):
        self.central_state.update(rejected=1, rows=[{
            "central_id": 1, "position": "<script>bad()</script>", "sensor_type": None,
            "raw_value": "999", "verdict": "rejected", "reason": "unknown sensor type",
            "observed_at": "now",
        }])
        html = self.client.get("/api/dashboard").get_data(as_text=True)
        self.assertIn("999", html)
        self.assertIn("42.5", html)
        self.assertIn("NOT added to physical sensor data", html)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)
        self.assertNotIn("<script>bad()", html)
        self.central_state["rows"][0].update(raw_value="24.5", verdict="accepted")
        self.central_state.update(rejected=0, accepted=2)
        updated = self.client.get("/api/dashboard").get_data(as_text=True)
        self.assertIn("24.5", updated)
        self.assertNotIn("role=\"alert\"", updated)
        self.controller.manual.assert_not_called()

    def test_central_api_never_reaches_controller_and_missing_schema_does_not_break_page(self):
        self.central_state.update(available=False, error="Start the sync worker", stale=True)
        self.controller.reset_mock()
        response = self.client.get("/api/challenge2")
        self.assertFalse(response.get_json()["available"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.controller.status.assert_not_called()
        self.controller.manual.assert_not_called()
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Start the sync worker", page.get_data(as_text=True))

    def test_submission_report_is_read_only_and_escapes_actual_evidence(self):
        self.central_state["evidence"] = [{
            "central_id": 9, "position": "<script>bad()</script>",
            "sensor_type": None, "raw_value": "<img src=x onerror=alert(1)>",
            "reason": "unknown type", "observed_at": "2026-09-20 02:50:00",
        }]
        response = self.client.get("/task2/report")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("Stable values vs. malicious data insertion", html)
        self.assertIn("hGroup10", html)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
        self.assertNotIn("<script>bad()", html)
        self.assertNotIn("dashboard.js", html)
        self.assertNotIn("/pump/", html)
        self.assertNotIn("http-equiv", html)
        self.controller.status.assert_not_called()
        self.controller.manual.assert_not_called()
        self.controller.start.assert_not_called()
        self.database.latest_per_sensor.assert_not_called()
        self.database.challenge2_state.assert_called_once_with()

    def test_submission_report_shows_missing_or_stale_data_without_success_claim(self):
        self.central_state.update(available=False, error="Monitor unavailable", stale=True)
        self.assertIn("Monitor unavailable", self.client.get("/task2/report").get_data(as_text=True))
        self.central_state.update(available=True)
        html = self.client.get("/task2/report").get_data(as_text=True)
        self.assertIn("incomplete, failed or stale", html)
        self.assertIn("No rejected Central observations recorded", html)
        self.controller.start.assert_not_called()
        self.controller.manual.assert_not_called()

    def test_updates_preserve_selfcare_and_rejection_escaping(self):
        self.database.latest_selfcare.return_value = {
            "message": "<script>alert(1)</script>", "source": "Central",
            "received_at": "2026-09-20 00:00:00",
        }
        self.database.rejection_summary.return_value = (1, [{
            "rejected_at": "2026-09-20 00:00:00", "topic": "broadcast",
            "reason": "Invalid payload",
            "raw_excerpt": "<img src=x onerror=alert(1)>",
        }])
        for endpoint in ("/", "/api/dashboard"):
            with self.subTest(endpoint=endpoint):
                html = self.client.get(endpoint).get_data(as_text=True)
                self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
                self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
                self.assertNotIn("<script>alert(1)</script>", html)
                self.assertNotIn("<img src=x", html)

    def test_json_pump_controls_return_result_without_redirect(self):
        for action, result in (("on", (True, "started")),
                               ("off", (True, "stopped")),
                               ("on", (False, "manual start refused: sensor offline"))):
            with self.subTest(action=action, result=result):
                self.controller.manual.reset_mock()
                self.controller.manual.return_value = result
                response = self.client.post("/pump/" + action,
                                            headers={"Accept": "application/json"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {"ok": result[0], "reason": result[1]})
                self.assertNotIn("Location", response.headers)
                self.controller.manual.assert_called_once_with(action)

    def test_invalid_pump_action_does_not_reach_controller(self):
        response = self.client.post("/pump/invalid", headers={"Accept": "application/json"})
        self.assertEqual(response.status_code, 400)
        self.controller.manual.assert_not_called()

    def test_json_resume_returns_result_without_redirect(self):
        response = self.client.post("/auto/resume", headers={"Accept": "application/json"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "ok": True, "reason": "Automatic control resumed",
        })
        self.assertNotIn("Location", response.headers)
        self.controller.resume_auto.assert_called_once_with()

    def test_controls_keep_normal_form_redirect_fallback(self):
        for endpoint in ("/pump/off", "/auto/resume"):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(endpoint)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/")


def render_browser_fixture():
    """Render actual templates for a browser that intercepts all network I/O."""
    if not FLASK_AVAILABLE:
        raise RuntimeError("Flask is required to render browser fixtures")
    fixture = DashboardTests()
    fixture.setUp()
    render = lambda path="/api/dashboard": fixture.client.get(path).get_data(as_text=True)
    result = {"page": render("/"), "online": render()}

    health = fixture.status["sensor_health"]
    health.update(state="offline", can_irrigate=False, error="Modbus timeout")
    fixture.status["sensor_error"] = "Modbus timeout"
    result["offline"] = render()

    health.update(state="online", can_irrigate=True, error=None)
    fixture.status["sensor_error"] = None
    fixture.reading["sensor_value"] = 43.2
    result["recovered"] = render()

    fixture.status["manual_override_s"] = 60
    result["manual"] = render()

    fixture.database.latest_selfcare.return_value = {
        "message": "<script>window.injected = true</script>", "source": "Central",
        "received_at": "2026-09-20 00:00:00",
    }
    fixture.database.rejection_summary.return_value = (1, [{
        "rejected_at": "2026-09-20 00:00:00", "topic": "broadcast",
        "reason": "Invalid payload", "raw_excerpt": "<img src=x onerror=alert(1)>",
    }])
    result["escaped"] = render()

    # Explicit test-only Central attack/correction data for browser rendering.
    spec = importlib.util.spec_from_file_location("_dashboard_chart_fixture", FARM_DIRECTORY / "anomaly_chart.py")
    chart_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(chart_module)
    fixture.central_state.update(rejected=1, plotted_rejections=1, rows=[{
        "central_id": 7, "position": "zone-1/temperature", "sensor_type": "temperature",
        "raw_value": "999", "verdict": "rejected", "reason": "outside plausible range",
        "observed_at": "2026-09-20 00:06:00",
    }], charts=[chart_module.comparison("temperature",
                           [{"value": value, "created_at": f"2026-09-20 00:0{i}:00", "sensor_position": "zone-1"}
                            for i, value in enumerate([24, 24.2, 24.1, 24.3, 24.2, 24.1])],
                           [{"value": 999, "observed_at": "2026-09-20 00:06:00", "central_id": 7,
                             "position": "zone-1/temperature", "reason": "temperature outside plausible range -40..85"}],
                           (-40, 85))])
    fixture.central_state["evidence"] = [dict(fixture.central_state["rows"][0])]
    result["central_attack"] = render()
    soil_charts = fixture.central_state["charts"]
    fixture.central_state["charts"] = soil_charts + [chart_module.comparison("moisture",
        [{"value": value, "created_at": f"2026-09-20 00:0{i}:00", "sensor_position": "zone-1"}
         for i, value in enumerate([42, 42.2, 42.1, 42, 41.9, 42.1])],
        [{"value": -20, "observed_at": "2026-09-20 00:06:00", "central_id": 8,
          "position": "zone-1/moisture", "reason": "moisture outside plausible range 0..100"}], (0, 100))]
    fixture.central_state.update(rejected=2, plotted_rejections=2)
    fixture.central_state["evidence"].append({
        "central_id": 8, "position": "zone-1/moisture", "raw_value": "-20", "sensor_type": "moisture",
        "reason": "moisture outside plausible range 0..100", "observed_at": "2026-09-20 00:06:00",
    })
    result["report"] = render("/task2/report")
    fixture.central_state["charts"] = soil_charts
    fixture.central_state["plotted_rejections"] = 1
    fixture.central_state.update(rejected=0, accepted=2)
    fixture.central_state["rows"][0].update(raw_value="25", verdict="accepted", reason="within range")
    result["central_corrected"] = render()
    fixture.controller.start.assert_not_called()
    fixture.controller.manual.assert_not_called()
    return result


if __name__ == "__main__":
    if sys.argv[1:] == ["--fixtures"]:
        print(json.dumps(render_browser_fixture()))
    else:
        unittest.main()
