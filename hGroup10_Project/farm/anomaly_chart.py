"""Escaping-friendly chart coordinates; never emits raw HTML or fake readings."""
import math
from datetime import datetime


def comparison(sensor_type, physical, rejected):
    def points(rows, time_key):
        out = []
        for row in rows:
            try:
                value = float(row["value"])
                stamp = row[time_key]
                if not isinstance(stamp, datetime):
                    stamp = datetime.fromisoformat(str(stamp))
                # Unplottable/huge attacks still appear in the rejection table.
                if math.isfinite(value) and abs(value) <= 1e12:
                    out.append((stamp.timestamp(), value))
            except (TypeError, ValueError, OverflowError, KeyError):
                continue
        return sorted(out)

    good = points(physical, "created_at")
    bad = points(rejected, "observed_at")
    all_points = good + bad
    result = {"sensor_type": sensor_type, "good": [], "bad": [], "line": "", "ticks": [],
              "start": "", "end": "", "has_data": bool(all_points)}
    if not all_points:
        return result
    first = min(t for t, v in all_points)
    last = max(t for t, v in all_points)
    low = min(v for t, v in all_points)
    high = max(v for t, v in all_points)
    padding = max((high - low) * .12, 1)
    low, high = low - padding, high + padding

    def xy(point):
        t, v = point
        return {"x": round(60 + (t - first) / max(last - first, 1) * 580, 2),
                "y": round(220 - (v - low) / (high - low) * 190, 2),
                "label": format(v, ".6g")}
    result["good"] = [xy(p) for p in good]
    result["bad"] = [xy(p) for p in bad]
    result["line"] = " ".join(f"{p['x']},{p['y']}" for p in result["good"])
    result["ticks"] = [{"y": 220 - n * 47.5, "label": format(low + (high - low) * n / 4, ".4g")}
                       for n in range(5)]
    result["start"] = datetime.fromtimestamp(first).strftime("%H:%M:%S")
    result["end"] = datetime.fromtimestamp(last).strftime("%H:%M:%S")
    return result
