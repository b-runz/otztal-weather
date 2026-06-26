"""
Ötztal Trek — interactive weather chart via Plotly.
Reads pre-computed route data from route_data.json, fetches live weather
from Open-Meteo, and returns a Plotly chart div + summary data for build_site.py.
"""

import json
import math
import time

import requests
import plotly.graph_objects as go


def _get_with_retry(url, params, retries=4):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=60)
            r.raise_for_status()
            return r
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** (attempt + 1)
            print(f"  request error ({exc}), retrying in {wait}s...")
            time.sleep(wait)
        except requests.exceptions.HTTPError:
            if r.status_code == 429:
                wait = 2 ** (attempt + 1)
                print(f"  rate limited (429), retrying in {wait}s...")
                time.sleep(wait)
                if attempt == retries - 1:
                    raise
            else:
                raise


def get_weather_batch(waypoints):
    """Fetch current temperature for a list of waypoint dicts with lat/lon."""
    lats = ",".join(f"{w['lat']:.5f}" for w in waypoints)
    lons = ",".join(f"{w['lon']:.5f}" for w in waypoints)
    r = _get_with_retry(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lats,
            "longitude": lons,
            "current": "temperature_2m,weathercode",
            "timezone": "Europe/Vienna",
            "forecast_days": 1,
        },
    )
    data = r.json()
    if isinstance(data, list):
        return [d["current"]["temperature_2m"] for d in data]
    return [data["current"]["temperature_2m"]]


def main():
    with open("route_data.json", encoding="utf-8") as f:
        route = json.load(f)

    waypoints     = route["waypoints"]       # [{lat, lon, ele, cum_km, stage_index, ...}]
    route_profile = route["route_profile"]   # [{cum_km, ele, stage_index}]
    stages        = route["stages"]          # [{name, start_km, end_km, date}]
    peaks         = route["peaks"]           # [{cum_km, ele, name, stage_index}]
    overnights    = route["overnights"]      # [{cum_km, ele, name, stage_index}]
    total_km      = route["total_km"]

    print(f"Total route: {total_km:.1f} km across {len(stages)} stages")
    print(f"Fetching weather for {len(waypoints)} waypoints...")
    time.sleep(2)

    BATCH = 10
    temps_by_km = {}
    for i in range(0, len(waypoints), BATCH):
        batch = waypoints[i:i + BATCH]
        try:
            temps = get_weather_batch(batch)
            for w, t in zip(batch, temps):
                temps_by_km[w["cum_km"]] = t
            print(f"  batch {i // BATCH + 1}/{math.ceil(len(waypoints) / BATCH)} done")
        except Exception as e:
            print(f"  batch failed: {e}")
        time.sleep(1.0)

    sorted_kms   = sorted(temps_by_km.keys())
    sorted_temps = [temps_by_km[k] for k in sorted_kms]

    def interp_temp(km):
        if not sorted_kms:
            return None
        if km <= sorted_kms[0]:
            return sorted_temps[0]
        if km >= sorted_kms[-1]:
            return sorted_temps[-1]
        for j in range(len(sorted_kms) - 1):
            if sorted_kms[j] <= km <= sorted_kms[j + 1]:
                t = (km - sorted_kms[j]) / (sorted_kms[j + 1] - sorted_kms[j])
                return sorted_temps[j] * (1 - t) + sorted_temps[j + 1] * t
        return sorted_temps[-1]

    def stage_for_km(km):
        for s in stages:
            if s["start_km"] <= km <= s["end_km"]:
                return s["name"]
        return min(stages, key=lambda s: abs(s["end_km"] - km))["name"]

    plot_km     = [p["cum_km"] for p in route_profile]
    plot_ele    = [p["ele"]    for p in route_profile]
    plot_temp   = [interp_temp(k) for k in plot_km]
    plot_custom = [[round(e), stage_for_km(k)] for k, e in zip(plot_km, plot_ele)]

    # peaks/overnights use (0,0) for lat/lon — build_site.py unpacks but never reads them
    peaks_out = [
        (0.0, 0.0, p["ele"], p["cum_km"], p["name"], interp_temp(p["cum_km"]))
        for p in peaks
    ]
    overnights_out = [
        (0.0, 0.0, p["ele"], p["cum_km"], p["name"], interp_temp(p["cum_km"]))
        for p in overnights
    ]

    fetched = [(temps_by_km[k], k) for k in temps_by_km]
    hottest = max(fetched, key=lambda x: x[0])
    coldest = min(fetched, key=lambda x: x[0])
    hottest_wp = min(waypoints, key=lambda w: abs(w["cum_km"] - hottest[1]))
    coldest_wp = min(waypoints, key=lambda w: abs(w["cum_km"] - coldest[1]))

    # ---------------------------------------------------------------------------
    # Build Plotly figure
    # ---------------------------------------------------------------------------
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=plot_km, y=plot_ele,
        fill="tozeroy",
        fillcolor="rgba(139,115,85,0.15)",
        line=dict(color="rgba(139,115,85,0.35)", width=1),
        name="Elevation",
        yaxis="y2",
        hovertemplate="⛰ %{y:.0f} m<extra>Elevation</extra>",
    ))

    fig.add_trace(go.Scatter(
        x=plot_km, y=plot_temp,
        line=dict(color="#E84B3A", width=2.5),
        fill="tonexty",
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

    fig.add_trace(go.Scatter(
        x=[p[3] for p in peaks_out],
        y=[p[5] for p in peaks_out],
        mode="markers",
        marker=dict(symbol="triangle-up", size=15, color="#1a6b3c",
                    line=dict(color="white", width=1.5)),
        name="Stage peak",
        customdata=[[p[4], p[2]] for p in peaks_out],
        hovertemplate=(
            "<b>▲ %{customdata[0]}</b><br>"
            "🌡 %{y:.1f}°C<br>"
            "⛰ %{customdata[1]:.0f} m<br>"
            "%{x:.1f} km"
            "<extra>Peak</extra>"
        ),
    ))

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
        customdata=[[p[4], p[2]] for p in ov_dedup],
        hovertemplate=(
            "<b>🏠 %{customdata[0]}</b><br>"
            "🌡 %{y:.1f}°C<br>"
            "⛰ %{customdata[1]:.0f} m<br>"
            "%{x:.1f} km"
            "<extra>Overnight</extra>"
        ),
    ))

    for s in stages[:-1]:
        fig.add_vline(x=s["end_km"], line_dash="dash",
                      line_color="rgba(0,0,0,0.18)", line_width=1)

    for s in stages:
        mid = (s["start_km"] + s["end_km"]) / 2
        fig.add_annotation(
            x=mid, y=1.0, xref="x", yref="paper",
            text=s["name"],
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
        "chart_html":  chart_html,
        "peaks":       peaks_out,
        "overnights":  overnights_out,
        "hottest":     {"temp": hottest[0], "km": hottest[1], "ele": hottest_wp["ele"]},
        "coldest":     {"temp": coldest[0], "km": coldest[1], "ele": coldest_wp["ele"]},
        "total_km":    total_km,
        "stages":      [{"name": s["name"], "start_km": s["start_km"], "end_km": s["end_km"]}
                        for s in stages],
    }


if __name__ == "__main__":
    main()
