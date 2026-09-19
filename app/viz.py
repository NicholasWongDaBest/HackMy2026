"""Dependency-free inline-SVG anomaly chart for the dashboard.

Draws the stable, in-range sensor line against the impossible values the
validator rejected -- the "stable vs malicious" comparison Challenge 2
asks for. Pure server-rendered SVG: no JavaScript, no CDN, so it renders
on a Pi with no internet. The shaded band is the physically plausible
range from config.SENSOR_RANGES; every red mark falls outside it, which
is exactly why it was discarded before automation ever saw it.
"""
from datetime import datetime

W, H = 920, 300
PAD_L, PAD_R, PAD_T, PAD_B = 56, 18, 16, 34


def _ts(v):
    return v.timestamp() if isinstance(v, datetime) else 0.0


def _fmt(v):
    return f"{v:.0f}" if abs(v) >= 100 else f"{v:.1f}"


def anomaly_chart_svg(good, bad, sensor_type, band=(None, None), unit=""):
    """good: [{sensor_value, created_at}]  bad: [{value, rejected_at}]"""
    gpts = [(_ts(r["created_at"]), float(r["sensor_value"])) for r in good]
    bpts = [(_ts(r["rejected_at"]), float(r["value"])) for r in bad]
    allpts = gpts + bpts
    if not allpts:
        return ('<div style="color:#9aa0aa;padding:28px;text-align:center">'
                'No readings yet. Trigger Challenge 2 &mdash; stable values and '
                'rejected spikes will plot here live.</div>')

    ts = [p[0] for p in allpts]
    vs = [p[1] for p in allpts]
    tmin, tmax = min(ts), max(ts)
    vmin, vmax = min(vs), max(vs)
    if tmax == tmin:
        tmax = tmin + 1
    span = (vmax - vmin) or 1.0
    vmin -= span * 0.08
    vmax += span * 0.08

    def X(t):
        return PAD_L + (t - tmin) / (tmax - tmin) * (W - PAD_L - PAD_R)

    def Y(v):
        return H - PAD_B - (v - vmin) / (vmax - vmin) * (H - PAD_T - PAD_B)

    s = [f'<svg viewBox="0 0 {W} {H}" width="100%" preserveAspectRatio="xMidYMid meet" '
         f'font-family="ui-sans-serif,system-ui,sans-serif" font-size="11">']

    # plausible band
    low, high = band
    if low is not None and high is not None:
        yhi, ylo = Y(min(high, vmax)), Y(max(low, vmin))
        s.append(f'<rect x="{PAD_L:.1f}" y="{yhi:.1f}" width="{W-PAD_L-PAD_R:.1f}" '
                 f'height="{max(0,ylo-yhi):.1f}" fill="#3ddc84" fill-opacity="0.10"/>')
        s.append(f'<line x1="{PAD_L}" y1="{yhi:.1f}" x2="{W-PAD_R}" y2="{yhi:.1f}" '
                 f'stroke="#3ddc84" stroke-opacity="0.5" stroke-dasharray="4 4"/>')
        s.append(f'<line x1="{PAD_L}" y1="{ylo:.1f}" x2="{W-PAD_R}" y2="{ylo:.1f}" '
                 f'stroke="#3ddc84" stroke-opacity="0.5" stroke-dasharray="4 4"/>')

    # y gridlines + labels
    for i in range(5):
        v = vmin + (vmax - vmin) * i / 4
        y = Y(v)
        s.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" '
                 f'stroke="#272b35"/>')
        s.append(f'<text x="{PAD_L-8}" y="{y+4:.1f}" text-anchor="end" '
                 f'fill="#9aa0aa">{_fmt(v)}</text>')

    # good line + dots
    if gpts:
        gpts.sort()
        pts = " ".join(f"{X(t):.1f},{Y(v):.1f}" for t, v in gpts)
        s.append(f'<polyline points="{pts}" fill="none" stroke="#3ddc84" stroke-width="2"/>')
        for t, v in gpts:
            s.append(f'<circle cx="{X(t):.1f}" cy="{Y(v):.1f}" r="2.5" fill="#3ddc84"/>')

    # bad markers with drop line to baseline
    baseline = Y(vmin)
    for t, v in bpts:
        x, y = X(t), Y(v)
        s.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{baseline:.1f}" '
                 f'stroke="#ff5c5c" stroke-opacity="0.35" stroke-width="1"/>')
        s.append(f'<path d="M{x-5:.1f},{y-5:.1f} l10,10 M{x+5:.1f},{y-5:.1f} l-10,10" '
                 f'stroke="#ff5c5c" stroke-width="2.5"/>')
        s.append(f'<text x="{x:.1f}" y="{y-9:.1f}" text-anchor="middle" '
                 f'fill="#ff5c5c" font-weight="700">{_fmt(v)}</text>')

    # axes frame
    s.append(f'<line x1="{PAD_L}" y1="{PAD_T}" x2="{PAD_L}" y2="{H-PAD_B}" stroke="#3a3f4b"/>')
    s.append(f'<line x1="{PAD_L}" y1="{H-PAD_B}" x2="{W-PAD_R}" y2="{H-PAD_B}" stroke="#3a3f4b"/>')

    # legend
    lx, ly = PAD_L + 6, PAD_T + 4
    s.append(f'<line x1="{lx}" y1="{ly}" x2="{lx+18}" y2="{ly}" stroke="#3ddc84" stroke-width="2"/>')
    s.append(f'<text x="{lx+24}" y="{ly+4}" fill="#e8eaed">stable (in-range) readings</text>')
    s.append(f'<path d="M{lx+185},{ly-4} l8,8 M{lx+193},{ly-4} l-8,8" stroke="#ff5c5c" stroke-width="2.5"/>')
    s.append(f'<text x="{lx+205}" y="{ly+4}" fill="#e8eaed">rejected impossible values</text>')

    unit_lbl = f" ({unit})" if unit else ""
    s.append(f'<text x="{W-PAD_R}" y="{H-8}" text-anchor="end" fill="#9aa0aa">'
             f'time &#8594; &#183; y = {sensor_type}{unit_lbl}</text>')
    s.append('</svg>')
    return "".join(s)
