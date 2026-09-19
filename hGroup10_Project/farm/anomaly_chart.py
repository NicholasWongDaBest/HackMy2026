"""Escaping-friendly chart coordinates; never emits raw HTML or fake readings."""
import math
from datetime import datetime


_LABELS = {
    "temperature": ("Soil temperature", "degC"),
    "air_temperature": ("Air temperature", "degC"),
    "moisture": ("Soil moisture", "%"),
    "humidity": ("Humidity", "%"),
    "light": ("Light", "%"),
    "water_level": ("Water level", "%"),
    "rainfall": ("Rainfall", "%"),
    "ec": ("Electrical conductivity", "uS/cm"),
    "ph": ("pH", "pH"),
}


def comparison(sensor_type, physical, rejected, limits=None):
    def points(rows, time_key):
        out = []
        for row in rows:
            try:
                if isinstance(row["value"], bool):
                    continue
                value = float(row["value"])
                stamp = row[time_key]
                if not isinstance(stamp, datetime):
                    stamp = datetime.fromisoformat(str(stamp))
                # Unplottable/huge attacks still appear in the rejection table.
                if math.isfinite(value) and abs(value) <= 1e12:
                    if time_key == "created_at" and limits and not limits[0] <= value <= limits[1]:
                        continue
                    out.append({"time": stamp.timestamp(), "value": value,
                                "at": stamp.strftime("%Y-%m-%d %H:%M:%S"),
                                "position": str(row.get("sensor_position", row.get("position", "local sensor"))),
                                "central_id": row.get("central_id"),
                                "reason": str(row.get("reason", ""))})
            except (TypeError, ValueError, OverflowError, OSError, KeyError):
                continue
        return sorted(out, key=lambda point: point["time"])

    good = points(physical, "created_at")
    bad = points(rejected, "observed_at")
    all_points = good + bad
    title, unit = _LABELS.get(sensor_type, (sensor_type.replace("_", " ").title(), ""))
    result = {"sensor_type": sensor_type, "title": title, "unit": unit,
              "good": [], "bad": [], "line": "", "ticks": [], "series": [],
              "start": "", "end": "", "has_data": bool(all_points),
              "good_count": len(good), "bad_count": len(bad),
              "omitted_bad": len(rejected) - len(bad), "stable": None,
              "first_bad_x": None, "last_local": good[-1]["at"] if good else None,
              "last_bad": bad[-1]["at"] if bad else None,
              "limits": f"{limits[0]:g} to {limits[1]:g}" if limits else None}
    if not all_points:
        return result
    first = min(p["time"] for p in all_points)
    last = max(p["time"] for p in all_points)

    def project(scale_points, bottom=220, height=190):
        low = min(p["value"] for p in scale_points)
        high = max(p["value"] for p in scale_points)
        padding = max((high - low) * .12, 1)
        low, high = low - padding, high + padding

        def xy(point):
            return {**point, "x": round(60 + (point["time"] - first) / max(last - first, 1) * 580, 2),
                    "y": round(bottom - (point["value"] - low) / (high - low) * height, 2),
                    "label": format(point["value"], ".6g")}

        ticks = [{"y": bottom - n * height / 4, "label": format(low + (high - low) * n / 4, ".4g")}
                 for n in range(5)]
        return xy, ticks

    def series(points):
        # Never join different physical sensor positions into one invented line.
        positions = sorted({p["position"] for p in points})
        return [{"position": position, "line": " ".join(
            f"{p['x']},{p['y']}" for p in points if p["position"] == position
        )} for position in positions]

    xy, result["ticks"] = project(all_points)
    result["good"] = [xy(p) for p in good]
    result["bad"] = [xy(p) for p in bad]
    result["series"] = series(result["good"])
    result["line"] = result["series"][0]["line"] if len(result["series"]) == 1 else ""
    if bad:
        result["first_bad_x"] = result["bad"][0]["x"]
    if good:
        zoom, ticks = project(good, bottom=95, height=70)
        zoom_points = [zoom(p) for p in good]
        result["stable"] = {"points": zoom_points, "series": series(zoom_points), "ticks": ticks[::2],
                            "min": format(min(p["value"] for p in good), ".6g"),
                            "max": format(max(p["value"] for p in good), ".6g")}
    result["start"] = datetime.fromtimestamp(first).strftime("%H:%M:%S")
    result["end"] = datetime.fromtimestamp(last).strftime("%H:%M:%S")
    result["start_date"] = datetime.fromtimestamp(first).strftime("%Y-%m-%d")
    result["end_date"] = datetime.fromtimestamp(last).strftime("%Y-%m-%d")
    return result
