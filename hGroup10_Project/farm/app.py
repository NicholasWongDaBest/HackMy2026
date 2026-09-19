"""Dashboard and manual irrigation control.

The control loop runs as a thread inside this process (see farm/control.py)
so that one process owns the GPIO lines. That is why the manual pump
button on this page actually moves the relay instead of posting into the
void.

Jinja autoescaping is ON for .html templates, so anything rendered from
the database -- including a selfcare message containing <script> -- is
emitted as inert text. That is deliberate and is the last line of
defence behind farm/validation.py.

Run:  python3 -m farm.app      (then http://<pi-ip>:5000)
"""
import logging
import os

from flask import Flask, jsonify, redirect, render_template, request, url_for

from . import config, control, database

app = Flask(__name__)
log = logging.getLogger("app")


def dashboard_context():
    ctl = control.get_controller()
    selfcare = database.latest_selfcare()
    readings = database.recent_readings(20)
    total_rejected, rejections = database.rejection_summary(10)
    pending, last_sync = database.sync_status()
    return dict(
        team=config.TEAM_NAME,
        selfcare=selfcare,
        readings=readings,
        total_rejected=total_rejected,
        rejections=rejections,
        pending=pending,
        last_sync=last_sync,
        live=database.latest_per_sensor(),
        status=ctl.status(),
        decisions=database.recent_decisions(10),
        position=config.SENSOR_POSITION,
        challenge2=database.challenge2_state(),
    )


@app.route("/")
def dashboard():
    return render_template("dashboard.html", **dashboard_context())


@app.get("/api/dashboard")
def dashboard_updates():
    # Reuse the escaped Jinja blocks without resending the page shell/assets.
    return (
        render_template("dashboard_updates.html", **dashboard_context()),
        200,
        {"Cache-Control": "no-store"},
    )


@app.route("/pump/<action>", methods=["POST"])
def pump(action):
    """Manual irrigation control. Judges will press this."""
    if action not in ("on", "off", "toggle"):
        return jsonify({"error": "action must be on, off or toggle"}), 400
    ok, reason = control.get_controller().manual(action)
    log.info("manual pump %s -> %s (%s)", action, ok, reason)
    if request.headers.get("Accept", "").startswith("application/json"):
        return jsonify({"ok": ok, "reason": reason})
    return redirect(url_for("dashboard"))


@app.route("/auto/resume", methods=["POST"])
def resume_auto():
    control.get_controller().resume_auto()
    if request.headers.get("Accept", "").startswith("application/json"):
        return jsonify({"ok": True, "reason": "Automatic control resumed"})
    return redirect(url_for("dashboard"))


@app.route("/api/status")
def api_status():
    ctl = control.get_controller()
    total_rejected, rejections = database.rejection_summary(5)
    pending, last_sync = database.sync_status()
    return jsonify({
        "team": config.TEAM_NAME,
        "selfcare": database.latest_selfcare(),
        "pending_sync_rows": pending,
        "rejected_total": total_rejected,
        "recent_rejections": rejections,
        "last_sync": last_sync,
        "control": ctl.status(),
    })


@app.route("/api/live")
def api_live():
    return jsonify(control.get_controller().status())


@app.get("/api/challenge2")
def challenge2_status():
    # Read-only endpoint: no controller, serial, MQTT, or Central connection.
    return jsonify(database.challenge2_state()), 200, {"Cache-Control": "no-store"}


def create_app():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    # WERKZEUG_RUN_MAIN guards against the dev reloader starting two
    # control loops and two owners of the same GPIO pin.
    if not app.config.get("CONTROL_STARTED"):
        control.get_controller().start()
        app.config["CONTROL_STARTED"] = True
    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=False, threaded=True)
