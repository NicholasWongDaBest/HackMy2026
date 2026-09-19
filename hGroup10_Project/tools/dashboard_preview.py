"""Run the dashboard UI on Windows without Raspberry Pi hardware or MySQL.

This is intentionally separate from farm.app. It renders the real dashboard
template and serves the real static assets, but supplies safe in-memory demo
data and a simulated pump. Nothing here can operate physical hardware.

Run from the repository root:
    python tools/dashboard_preview.py

Then open http://127.0.0.1:5000
"""
from __future__ import annotations

import math
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, redirect, render_template, url_for


ROOT = Path(__file__).resolve().parents[1]
FARM = ROOT / "farm"

app = Flask(
    __name__,
    template_folder=str(FARM / "templates"),
    static_folder=str(FARM / "static"),
)

pump_running = False
pump_changed_at = time.time() - 82
pump_started_at: float | None = None
manual_until = 0.0
decisions: list[dict] = []


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def demo_values() -> dict[str, float]:
    """Gently moving values make the five-second refresh visible."""
    phase = time.time() / 30
    return {
        "temperature": round(27.4 + math.sin(phase) * 0.4, 2),
        "humidity": round(68.2 + math.sin(phase / 2) * 1.1, 2),
        "light": round(74.9 + math.sin(phase / 3) * 2.0, 2),
        "moisture": round(38.6 + math.sin(phase / 4) * 1.3, 2),
        "water_level": 61.1,
        "rainfall": 4.2,
    }


def enforce_demo_cutoff() -> None:
    global pump_running, pump_changed_at, pump_started_at
    if pump_running and pump_started_at and time.time() - pump_started_at >= 10:
        pump_running = False
        pump_started_at = None
        pump_changed_at = time.time()
        add_decision("pump_off", "local demo safety cutoff at 10s", "safety")


def add_decision(decision: str, reason: str, source: str) -> None:
    values = demo_values()
    decisions.insert(0, {
        "created_at": now_text(),
        "decision": decision,
        "source": source,
        "moisture": values["moisture"],
        "temperature": values["temperature"],
        "ec": None,
        "pump_state": pump_running,
        "reason": reason,
    })
    del decisions[10:]


def page_context() -> dict:
    enforce_demo_cutoff()
    stamp = now_text()
    values = demo_values()
    live = [
        {
            "sensor_type": sensor_type,
            "sensor_value": value,
            "sensor_position": "zone-1",
            "created_at": stamp,
            "synced": False,
        }
        for sensor_type, value in values.items()
    ]
    running_for = time.time() - pump_started_at if pump_running and pump_started_at else 0
    resting_for = None if pump_running else time.time() - pump_changed_at
    latest = decisions[0] if decisions else {
        "decision": "hold",
        "reason": "local preview is inside the 30-45% moisture band",
        "source": "auto",
    }
    return {
        "team": "hGroup10 · LOCAL DEMO",
        "position": "zone-1",
        "live": live,
        "readings": live,
        "status": {
            "pumps": {1: {
                "running": pump_running,
                "pin": 25,
                "run_seconds": round(running_for, 1),
                "rest_seconds": round(resting_for, 1) if resting_for is not None else None,
            }},
            "sensor_error": None,
            "manual_override_s": max(0, round(manual_until - time.time())),
            "thresholds": {
                "poll_interval_s": 60,
                "max_run_s": 10,
                "min_rest_s": 60,
                "on_below": 30,
                "off_above": 45,
            },
            "last_decision": latest,
        },
        "pending": len(live),
        "total_rejected": 0,
        "selfcare": None,
        "rejections": [],
        "decisions": decisions,
    }


@app.get("/")
def dashboard():
    return render_template("dashboard.html", **page_context())


@app.post("/pump/<action>")
def pump(action: str):
    global pump_running, pump_changed_at, pump_started_at, manual_until
    enforce_demo_cutoff()
    if action == "toggle":
        action = "off" if pump_running else "on"
    if action == "on":
        pump_running = True
        pump_started_at = time.time()
        pump_changed_at = pump_started_at
        reason = "local demo operator started pump"
    elif action == "off":
        pump_running = False
        pump_started_at = None
        pump_changed_at = time.time()
        reason = "local demo operator stopped pump"
    else:
        return "Action must be on, off or toggle", 400
    manual_until = time.time() + 120
    add_decision(f"pump_{action}", reason, "manual")
    return redirect(url_for("dashboard"))


@app.post("/auto/resume")
def resume_auto():
    global manual_until
    manual_until = 0
    add_decision("hold", "local demo automation resumed", "auto")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    print("LOCAL DEMO ONLY: no database, ESP32, relay or pump is being controlled.")
    print("Open http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
