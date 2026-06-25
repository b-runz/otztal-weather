"""
Ötztal Trek — interactive weather chart via Plotly.
Samples ~10 points per stage, fetches live weather from Open-Meteo,
returns a Plotly chart div + summary data for build_site.py.
"""

import glob
import math
import os
import time

import requests
import gpxpy
import plotly.graph_objects as go


# ---------------------------------------------------------------------------
# GPX helpers
# ---------------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def parse_gpx(filepath):
    with open(filepath, encoding="utf-8") as f:
        gpx = gpxpy.parse(f)
    pts = []
    for track in gpx.tracks:
        for seg in track.segments:
            for pt in seg.points:
                pts.append((pt.latitude, pt.longitude, pt.elevation or 0))
    return pts


def add_distances(pts, offset_km=0.0):
    """Return list of (lat, lon, ele, cum_km)."""
    result = []
    cum = offset_km
    for i, (lat, lon, ele) in enumerate(pts):
        if i > 0:
            cum += haversine_km(pts[i-1][0], pts[i-1][1], lat, lon)
        result.append((lat, lon, ele, cum))
    return result


def sample_indices(n, count):
    if count >= n:
        return list(range(n))
    step = n / count
    return [int(i * step) for i in range(count)]


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def get_weather_batch(points):
    """Fetch current temperature for a list of (lat, lon, ele, km) tuples."""
    lats = ",".join(f"{p[0]:.5f}" for p in points)
    lons = ",".join(f"{p[1]:.5f}" for p in points)
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lats,
        "longitude": lons,
        "current": "temperature_2m,weathercode",
        "timezone": "Europe/Vienna",
        "forecast_days": 1,
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        return [d["current"]["temperature_2m"] for d in data]
    else:
        return [data["current"]["temperature_2m"]]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    gpx_files = sorted(glob.glob("*.gpx"))
    if not gpx_files:
        print("No GPX files found.")
        return

    # --- Parse all stages ---
    stage_data = []
    all_pts = []

    offset = 0.0
    for filepath in gpx_files:
        raw = parse_gpx(filepath)
        pts = add_distances(raw, offset_km=offset)
        offset = pts[-1][3]

        base = os.path.basename(filepath).replace(".gpx", "")
        num = base.split(" - ")[0].strip()
        if "(" in base and ")" in base:
            inner = base[base.index("(") + 1 : base.rindex(")")]
            parts = inner.split(" - ")
            short_name = f"{num}: {parts[-1].replace('_ ', ', ')}" if len(parts) > 1 else f"{num}: {inner}"
        else:
            short_name = num

        stage_data.append({
            "name": short_name,
            "pts": pts,
            "start_km": pts[0][3],
            "end_km": pts[-1][3],
        })
        all_pts.extend(pts)

    total_km = all_pts[-1][3]
    print(f"Total route: {total_km:.1f} km across {len(gpx_files)} stages")

    # --- Key points ---
    overnight_pts = []
    peak_pts = []
    valley_pts = []

    for i, sd in enumerate(stage_data):
        pts = sd["pts"]
        start = pts[0]
        end = pts[-1]
        peak = max(pts, key=lambda p: p[2])
        valley = min(pts[1:-1], key=lambda p: p[2]) if len(pts) > 2 else pts[len(pts) // 2]

        if i == 0:
            overnight_pts.append((*start[:3], start[3], "Hotel Stern, Längenfeld"))
        overnight_pts.append((*end[:3], end[3], sd["name"].split(": ", 1)[-1].strip()))
        peak_pts.append((*peak[:3], peak[3], f"{peak[2]:.0f} m"))
        if (peak[2] - valley[2]) > 400:
            valley_pts.append((*valley[:3], valley[3], f"{valley[2]:.0f} m"))

    # --- Sample points for weather fetching ---
    sample_pts = []
    SAMPLES_PER_STAGE = 10

    for sd in stage_data:
        pts = sd["pts"]
        for idx in sample_indices(len(pts), SAMPLES_PER_STAGE):
            sample_pts.append(pts[idx])

    def already_sampled(lat, lon, threshold_km=0.5):
        return any(haversine_km(lat, lon, sp[0], sp[1]) < threshold_km for sp in sample_pts)

    for kp in peak_pts + overnight_pts + valley_pts:
        if not already_sampled(kp[0], kp[1]):
            sample_pts.append(kp[:4])

    sample_pts.sort(key=lambda p: p[3])

    print(f"Fetching weather for {len(sample_pts)} points...")

    BATCH = 10
    temps_by_km = {}
    for i in range(0, len(sample_pts), BATCH):
        batch = sample_pts[i:i + BATCH]
        try:
            temps = get_weather_batch(batch)
            for pt, t in zip(batch, temps):
                temps_by_km[pt[3]] = t
            print(f"  batch {i//BATCH + 1}/{math.ceil(len(sample_pts)/BATCH)} done")
        except Exception as e:
            print(f"  batch failed: {e}")
        time.sleep(0.4)

    sorted_kms = sorted(temps_by_km.keys())
    sorted_temps = [temps_by_km[k] for k in sorted_kms]

    def interp_temp(km):
        if km <= sorted_kms[0]:
            return sorted_temps[0]
        if km >= sorted_kms[-1]:
            return sorted_temps[-1]
        for j in range(len(sorted_kms) - 1):
            if sorted_kms[j] <= km <= sorted_kms[j + 1]:
                t = (km - sorted_kms[j]) / (sorted_kms[j + 1] - sorted_kms[j])
                return sorted_temps[j] * (1 - t) + sorted_temps[j + 1] * t
        return sorted_temps[-1]

    def temp_at_km(km):
        closest = min(temps_by_km.keys(), key=lambda k: abs(k - km))
        if abs(closest - km) < 2.0:
            return temps_by_km[closest]
        return interp_temp(km)

    def stage_for_km(km):
        for sd in stage_data:
            if sd["start_km"] <= km <= sd["end_km"]:
                return sd["name"]
        # Fallback: nearest stage end (handles points exactly at a boundary)
        return min(stage_data, key=lambda s: abs(s["end_km"] - km))["name"]

    # Thin track for plotting (~600 pts is smooth enough)
    plot_pts = all_pts[::max(1, len(all_pts) // 600)]
    plot_km  = [p[3] for p in plot_pts]
    plot_ele = [p[2] for p in plot_pts]
    plot_temp = [interp_temp(k) for k in plot_km]

    # customdata for temperature line hover: [elevation, stage_name]
    plot_custom = [[round(plot_ele[i]), stage_for_km(plot_km[i])] for i in range(len(plot_km))]

    # Key point data with temps
    peaks_out     = [(lat, lon, ele, km, label, temp_at_km(km)) for lat, lon, ele, km, label in peak_pts]
    overnights_out = [(lat, lon, ele, km, label, temp_at_km(km)) for lat, lon, ele, km, label in overnight_pts]

    # Extremes
    fetched = [(temps_by_km[k], k, min(sample_pts, key=lambda p: abs(p[3] - k))) for k in temps_by_km]
    hottest = max(fetched, key=lambda x: x[0])
    coldest = min(fetched, key=lambda x: x[0])

    # ---------------------------------------------------------------------------
    # Build Plotly figure
    # ---------------------------------------------------------------------------
    fig = go.Figure()

    # Elevation area (secondary y-axis, drawn first so it sits behind)
    fig.add_trace(go.Scatter(
        x=plot_km, y=plot_ele,
        fill="tozeroy",
        fillcolor="rgba(139,115,85,0.15)",
        line=dict(color="rgba(139,115,85,0.35)", width=1),
        name="Elevation",
        yaxis="y2",
        hovertemplate="⛰ %{y:.0f} m<extra>Elevation</extra>",
    ))

    # Temperature line (primary y-axis)
    fig.add_trace(go.Scatter(
        x=plot_km, y=plot_temp,
        line=dict(color="#E84B3A", width=2.5),
        fill="tonexty",        # faint fill down toward elevation area
        fillcolor="rgba(232,75,58,0.07)",
        name="Temperature",
        customdata=plot_custom,
        hovertemplate=(
            "<b>%{x:.1f} km</b><br>"
            "🌡 %{y:.1f}°C<br>"
            "⛰ %{customdata[0]} m<br>"
            "<span style='color:#999'>%{customdata[1]}</span>"
            "<extra>Route</extra>"
        ),
    ))

    # Peak markers
    fig.add_trace(go.Scatter(
        x=[p[3] for p in peaks_out],
        y=[p[5] for p in peaks_out],
        mode="markers",
        marker=dict(symbol="triangle-up", size=15, color="#1a6b3c",
                    line=dict(color="white", width=1.5)),
        name="Stage peak",
        customdata=[[p[4], p[2]] for p in peaks_out],  # [label, ele]
        hovertemplate=(
            "<b>▲ %{customdata[0]}</b><br>"
            "🌡 %{y:.1f}°C<br>"
            "⛰ %{customdata[1]:.0f} m<br>"
            "%{x:.1f} km"
            "<extra>Peak</extra>"
        ),
    ))

    # Overnight markers
    # Deduplicate by rounding km to 1 decimal
    seen = set()
    ov_dedup = []
    for p in overnights_out:
        key = round(p[3], 1)
        if key not in seen:
            seen.add(key)
            ov_dedup.append(p)

    fig.add_trace(go.Scatter(
        x=[p[3] for p in ov_dedup],
        y=[p[5] for p in ov_dedup],
        mode="markers",
        marker=dict(symbol="square", size=12, color="#2255aa",
                    line=dict(color="white", width=1.5)),
        name="Overnight stay",
        customdata=[[p[4], p[2]] for p in ov_dedup],  # [label, ele]
        hovertemplate=(
            "<b>🏠 %{customdata[0]}</b><br>"
            "🌡 %{y:.1f}°C<br>"
            "⛰ %{customdata[1]:.0f} m<br>"
            "%{x:.1f} km"
            "<extra>Overnight</extra>"
        ),
    ))

    # Stage boundary lines
    for sd in stage_data[:-1]:
        fig.add_vline(x=sd["end_km"], line_dash="dash",
                      line_color="rgba(0,0,0,0.18)", line_width=1)

    # Stage labels at top of chart
    for sd in stage_data:
        mid = (sd["start_km"] + sd["end_km"]) / 2
        fig.add_annotation(
            x=mid, y=1.0, xref="x", yref="paper",
            text=sd["name"],
            showarrow=False,
            font=dict(size=9, color="#888"),
            align="center",
            yanchor="bottom",
            bgcolor="rgba(255,255,255,0.7)",
        )

    fig.update_layout(
        xaxis=dict(
            title="Distance along route (km)",
            showgrid=True, gridcolor="rgba(0,0,0,0.06)",
            zeroline=False,
        ),
        yaxis=dict(
            title=dict(text="Temperature (°C)", font=dict(color="#E84B3A")),
            tickfont=dict(color="#E84B3A"),
            showgrid=True, gridcolor="rgba(0,0,0,0.06)",
            zeroline=False,
        ),
        yaxis2=dict(
            title=dict(text="Elevation (m)", font=dict(color="#8B7355")),
            tickfont=dict(color="#8B7355"),
            overlaying="y", side="right",
            showgrid=False,
            range=[0, max(plot_ele) * 1.5],
        ),
        hovermode="x unified",
        dragmode=False,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.06,
            xanchor="left", x=0,
            font=dict(size=11),
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=55, r=65, t=90, b=50),
        height=440,
        width=1000,
        autosize=False,
    )

    chart_html = fig.to_html(
        include_plotlyjs="cdn",
        full_html=False,
        config={
            "responsive": True,
            "displayModeBar": False,
            "scrollZoom": False,
            "staticPlot": False,
        },
        div_id="weather-chart",
    )

    print("Chart generated.")

    return {
        "chart_html": chart_html,
        "peaks": peaks_out,
        "overnights": overnights_out,
        "hottest": {"temp": hottest[0], "km": hottest[1], "ele": hottest[2][2]},
        "coldest": {"temp": coldest[0], "km": coldest[1], "ele": coldest[2][2]},
        "total_km": total_km,
        "stages": [{"name": sd["name"], "start_km": sd["start_km"], "end_km": sd["end_km"]}
                   for sd in stage_data],
    }


if __name__ == "__main__":
    main()
