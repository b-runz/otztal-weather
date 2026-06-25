"""
Ötztal Trek — temperature + elevation profile graph
Samples ~10 points per stage, fetches live weather from Open-Meteo,
plots temp line over elevation silhouette with peak & overnight markers.
"""

import glob
import math
import os
import time

import requests
import gpxpy
import matplotlib
matplotlib.use("Agg")  # headless — must be before pyplot import
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

matplotlib.rcParams["font.family"] = "sans-serif"


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
    """count evenly-spaced indices into a list of length n."""
    if count >= n:
        return list(range(n))
    step = n / count
    return [int(i * step) for i in range(count)]


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def get_weather_batch(points):
    """
    Fetch current temperature for a list of (lat, lon, ele, km) tuples.
    Open-Meteo supports multiple lat/lon in one request.
    Returns list of temps in same order.
    """
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
    # When multiple locations are requested, response is a list
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

    # --- Parse all stages, build a single distance-aware track ---
    stage_data = []  # per stage: {name, pts_with_dist, start_km, end_km}
    all_pts = []     # (lat, lon, ele, cum_km) across all stages

    offset = 0.0
    for filepath in gpx_files:
        raw = parse_gpx(filepath)
        pts = add_distances(raw, offset_km=offset)
        offset = pts[-1][3]

        # Short name
        base = os.path.basename(filepath).replace(".gpx", "")
        num = base.split(" - ")[0].strip()  # "Stage 1"
        # extract hut names from parentheses
        if "(" in base and ")" in base:
            inner = base[base.index("(") + 1 : base.rindex(")")]
            parts = inner.split(" - ")
            short_name = f"{num}\n{parts[-1].replace('_ ', ', ')}" if len(parts) > 1 else f"{num}\n{inner}"
        else:
            short_name = num

        stage_data.append({
            "name": short_name,
            "filepath": filepath,
            "pts": pts,
            "start_km": pts[0][3],
            "end_km": pts[-1][3],
        })
        all_pts.extend(pts)

    total_km = all_pts[-1][3]
    print(f"Total route: {total_km:.1f} km across {len(gpx_files)} stages")

    # --- Identify key points ---
    overnight_pts = []  # (lat, lon, ele, km, label)
    peak_pts = []       # (lat, lon, ele, km, label)
    valley_pts = []     # (lat, lon, ele, km, label)

    for i, sd in enumerate(stage_data):
        pts = sd["pts"]
        start = pts[0]
        end = pts[-1]
        peak = max(pts, key=lambda p: p[2])
        valley = min(pts[1:-1], key=lambda p: p[2]) if len(pts) > 2 else pts[len(pts) // 2]

        stage_num = i + 1
        if i == 0:
            overnight_pts.append((*start[:3], start[3], f"Hotel Stern\nLängenfeld"))
        overnight_pts.append((*end[:3], end[3], sd["name"].split("\n")[-1].strip()))
        peak_pts.append((*peak[:3], peak[3], f"{peak[2]:.0f}m"))
        # only add valley if it's notably lower than the stage (skip flat stages)
        if (peak[2] - valley[2]) > 400:
            valley_pts.append((*valley[:3], valley[3], f"{valley[2]:.0f}m"))

    # --- Sample points for weather fetching (~10 per stage) ---
    sample_pts = []  # (lat, lon, ele, km)
    SAMPLES_PER_STAGE = 10

    for sd in stage_data:
        pts = sd["pts"]
        idxs = sample_indices(len(pts), SAMPLES_PER_STAGE)
        for idx in idxs:
            sample_pts.append(pts[idx])

    # Add key points to samples (avoid duplicates by proximity)
    def already_sampled(lat, lon, threshold_km=0.5):
        for sp in sample_pts:
            if haversine_km(lat, lon, sp[0], sp[1]) < threshold_km:
                return True
        return False

    for kp in peak_pts + overnight_pts + valley_pts:
        if not already_sampled(kp[0], kp[1]):
            sample_pts.append(kp[:4])

    # Sort by km
    sample_pts.sort(key=lambda p: p[3])

    print(f"Fetching weather for {len(sample_pts)} points...")

    # Fetch in batches of 10 (API limit per request for free tier)
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

    # Interpolate temps for the full elevation profile
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

    # Thin the full track to ~500 pts for plotting
    plot_pts = all_pts[::max(1, len(all_pts) // 500)]
    plot_km = [p[3] for p in plot_pts]
    plot_ele = [p[2] for p in plot_pts]
    plot_temp = [interp_temp(k) for k in plot_km]

    # --- Get temps at key points ---
    def temp_at_km(km):
        closest = min(temps_by_km.keys(), key=lambda k: abs(k - km))
        if abs(closest - km) < 2.0:
            return temps_by_km[closest]
        return interp_temp(km)

    # ---------------------------------------------------------------------------
    # Plot
    # ---------------------------------------------------------------------------
    fig, ax1 = plt.subplots(figsize=(14, 6))
    ax2 = ax1.twinx()

    # Elevation silhouette
    ax2.fill_between(plot_km, plot_ele, alpha=0.18, color="#8B7355", zorder=1)
    ax2.plot(plot_km, plot_ele, color="#8B7355", linewidth=0.8, alpha=0.5, zorder=2)
    ax2.set_ylabel("Elevation (m)", color="#8B7355", fontsize=10)
    ax2.tick_params(axis="y", labelcolor="#8B7355")
    ax2.set_ylim(0, max(plot_ele) * 1.35)

    # Temperature line
    ax1.plot(plot_km, plot_temp, color="#E84B3A", linewidth=2.5, zorder=5, label="Temperature")
    ax1.fill_between(plot_km, plot_temp, min(plot_temp) - 1, alpha=0.12, color="#E84B3A", zorder=4)
    ax1.set_ylabel("Temperature (°C)", color="#E84B3A", fontsize=10)
    ax1.tick_params(axis="y", labelcolor="#E84B3A")
    ax1.set_xlabel("Distance along route (km)", fontsize=10)
    ax1.set_xlim(0, total_km)

    # Stage dividers + labels
    for sd in stage_data[:-1]:
        ax1.axvline(sd["end_km"], color="#aaaaaa", linewidth=1, linestyle="--", zorder=3)
    for sd in stage_data:
        mid_km = (sd["start_km"] + sd["end_km"]) / 2
        ax1.text(mid_km, 0.98, sd["name"], transform=ax1.get_xaxis_transform(),
                 ha="center", va="top", fontsize=7.5, color="#555555", style="italic")

    # --- Peak markers ---
    for lat, lon, ele, km, label in peak_pts:
        t = temp_at_km(km)
        ax1.plot(km, t, marker="^", markersize=11, color="#1a6b3c",
                 markeredgecolor="white", markeredgewidth=1.2, zorder=8)
        ax1.annotate(f"▲ {label}\n{t:.1f}°C",
                     xy=(km, t), xytext=(0, 14), textcoords="offset points",
                     ha="center", fontsize=7.5, color="#1a6b3c",
                     arrowprops=dict(arrowstyle="-", color="#1a6b3c", lw=0.8))

    # --- Overnight markers ---
    for lat, lon, ele, km, label in overnight_pts:
        t = temp_at_km(km)
        ax1.plot(km, t, marker="s", markersize=10, color="#2255aa",
                 markeredgecolor="white", markeredgewidth=1.2, zorder=8)
        ax1.annotate(f"{label}\n{t:.1f}°C",
                     xy=(km, t), xytext=(0, -28), textcoords="offset points",
                     ha="center", fontsize=7.5, color="#2255aa",
                     arrowprops=dict(arrowstyle="-", color="#2255aa", lw=0.8))

    # Legend
    legend_elements = [
        Line2D([0], [0], color="#E84B3A", linewidth=2.5, label="Temperature (°C)"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#1a6b3c",
               markersize=10, label="Stage high point"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#2255aa",
               markersize=10, label="Overnight stay"),
        mpatches.Patch(facecolor="#8B7355", alpha=0.4, label="Elevation profile"),
    ]
    ax1.legend(handles=legend_elements, loc="upper right", fontsize=8.5, framealpha=0.9)

    ax1.set_title("Ötztal Trek — Current Weather Along Route", fontsize=13, fontweight="bold", pad=12)
    ax1.grid(axis="x", linestyle=":", alpha=0.4, zorder=0)
    ax1.grid(axis="y", linestyle=":", alpha=0.25, zorder=0)

    plt.tight_layout()
    out = "otztal_weather.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\nSaved: {out}")

    # Build return data for callers (e.g. build_site.py)
    peaks_out = [(lat, lon, ele, km, label, temp_at_km(km)) for lat, lon, ele, km, label in peak_pts]
    overnights_out = [(lat, lon, ele, km, label, temp_at_km(km)) for lat, lon, ele, km, label in overnight_pts]

    fetched = [(temps_by_km[k], k, min(sample_pts, key=lambda p: abs(p[3] - k))) for k in temps_by_km]
    hottest = max(fetched, key=lambda x: x[0])
    coldest = min(fetched, key=lambda x: x[0])

    return {
        "peaks": peaks_out,          # [(lat,lon,ele,km,label,temp), ...]
        "overnights": overnights_out, # [(lat,lon,ele,km,label,temp), ...]
        "hottest": {"temp": hottest[0], "km": hottest[1], "ele": hottest[2][2]},
        "coldest": {"temp": coldest[0], "km": coldest[1], "ele": coldest[2][2]},
        "total_km": total_km,
        "stages": [{"name": sd["name"], "start_km": sd["start_km"], "end_km": sd["end_km"]}
                   for sd in stage_data],
    }


if __name__ == "__main__":
    main()
