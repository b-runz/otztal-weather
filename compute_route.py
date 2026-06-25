"""
One-time script: parse GPX stages, compute Tobler hiking times,
write route_data.json. Commit the output alongside GPX files.
Re-run only if the route GPX files change.
"""

import glob
import json
import math
import os

import weather_graph as wg

# Dates for each stage (index 0 = stage 1)
STAGE_DATES = ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09"]

SAMPLES_PER_STAGE = 10
ROUTE_PROFILE_PTS = 600

# GPS elevation data can have large noise on short segments; clamp slope to
# a physically plausible maximum (150% grade ≈ 56°) to prevent Tobler
# division-by-near-zero blowing up accumulated time.
SLOPE_MAX = 1.5
MIN_SEGMENT_M = 0.5  # skip horizontal segments shorter than 50 cm


def tobler_speed(slope):
    """Tobler's hiking function: speed in km/h given dimensionless slope."""
    return 6.0 * math.exp(-3.5 * abs(slope + 0.05))


def add_hiking_times(pts):
    """
    Takes list of (lat, lon, ele, cum_km) and returns
    list of (lat, lon, ele, cum_km, tobler_h) where tobler_h is
    cumulative hiking hours from the first point.
    """
    result = []
    elapsed = 0.0
    for i, (lat, lon, ele, cum_km) in enumerate(pts):
        if i > 0:
            prev = pts[i - 1]
            d_km = cum_km - prev[3]
            d_m = d_km * 1000.0
            if d_m >= MIN_SEGMENT_M:
                d_ele = ele - prev[2]
                slope = max(-SLOPE_MAX, min(SLOPE_MAX, d_ele / d_m))
                speed = tobler_speed(slope)
                if speed > 0:
                    elapsed += d_km / speed
        result.append((lat, lon, ele, cum_km, elapsed))
    return result


def _kp_dict(lat, lon, ele, cum_km, tobler_h, stage_index, name):
    return {
        "cum_km":      round(cum_km, 3),
        "ele":         round(ele, 1),
        "name":        name,
        "tobler_h":    round(tobler_h, 4),
        "stage_index": stage_index,
    }


def main():
    gpx_files = sorted(glob.glob("*.gpx"))
    if not gpx_files:
        raise SystemExit("No GPX files found.")

    if len(gpx_files) != len(STAGE_DATES):
        raise SystemExit(
            f"Expected {len(STAGE_DATES)} GPX files, found {len(gpx_files)}."
        )

    stage_data = []
    all_pts_with_time = []  # (lat, lon, ele, cum_km, tobler_h, stage_index)

    offset = 0.0
    for stage_index, filepath in enumerate(gpx_files):
        raw = wg.parse_gpx(filepath)
        pts = wg.add_distances(raw, offset_km=offset)
        offset = pts[-1][3]

        base = os.path.basename(filepath).replace(".gpx", "")
        num = base.split(" - ")[0].strip()
        if "(" in base and ")" in base:
            inner = base[base.index("(") + 1 : base.rindex(")")]
            parts = inner.split(" - ")
            short_name = (
                f"{num}: {parts[-1].replace('_ ', ', ')}"
                if len(parts) > 1
                else f"{num}: {inner}"
            )
        else:
            short_name = num

        stage_data.append({
            "name": short_name,
            "date": STAGE_DATES[stage_index],
            "start_km": pts[0][3],
            "end_km": pts[-1][3],
            "pts": pts,
            "stage_index": stage_index,
        })

        timed = add_hiking_times(pts)
        for lat, lon, ele, cum_km, tobler_h in timed:
            all_pts_with_time.append((lat, lon, ele, cum_km, tobler_h, stage_index))

    total_km = stage_data[-1]["end_km"]
    print(f"Route: {total_km:.1f} km across {len(stage_data)} stages")

    # --- Key points per stage (separate from waypoints sampling) ---
    overnight_pts = []   # list of _kp_dict
    peak_pts = []

    for sd in stage_data:
        pts = sd["pts"]
        si  = sd["stage_index"]
        timed = add_hiking_times(pts)

        start   = timed[0]
        end     = timed[-1]
        peak_t  = max(timed, key=lambda p: p[2])

        if si == 0:
            overnight_pts.append(_kp_dict(*start[:5], si, "Hotel Stern, Längenfeld"))
        overnight_pts.append(_kp_dict(*end[:5], si, sd["name"].split(": ", 1)[-1].strip()))
        peak_pts.append(_kp_dict(*peak_t[:5], si, f"{peak_t[2]:.0f} m"))

    print(f"Key points: {len(peak_pts)} peaks, {len(overnight_pts)} overnights")

    # --- Sample waypoints for weather fetching ---
    # Peaks and overnights are guaranteed to be included so their temps are available.
    sample_waypoints = []

    for sd in stage_data:
        timed = add_hiking_times(sd["pts"])
        si    = sd["stage_index"]
        for idx in wg.sample_indices(len(timed), SAMPLES_PER_STAGE):
            lat, lon, ele, cum_km, tobler_h = timed[idx]
            sample_waypoints.append({
                "lat": lat, "lon": lon, "ele": ele,
                "cum_km": cum_km, "tobler_h": tobler_h,
                "stage_index": si,
            })

    def already_sampled(lat, lon, threshold_km=0.5):
        return any(
            wg.haversine_km(lat, lon, w["lat"], w["lon"]) < threshold_km
            for w in sample_waypoints
        )

    # Add key points that aren't near an existing sample
    for kp in peak_pts + overnight_pts:
        # Reconstruct lat/lon from the timed list for this stage
        timed = add_hiking_times(stage_data[kp["stage_index"]]["pts"])
        # Find the point with matching cum_km (within 0.01 km)
        match = min(timed, key=lambda p: abs(p[3] - kp["cum_km"]))
        lat, lon = match[0], match[1]
        if not already_sampled(lat, lon):
            sample_waypoints.append({
                "lat": lat, "lon": lon, "ele": kp["ele"],
                "cum_km": kp["cum_km"], "tobler_h": kp["tobler_h"],
                "stage_index": kp["stage_index"],
            })

    sample_waypoints.sort(key=lambda w: w["cum_km"])
    print(f"Sampled {len(sample_waypoints)} waypoints for weather fetching")

    # --- Route profile (thinned) ---
    step = max(1, len(all_pts_with_time) // ROUTE_PROFILE_PTS)
    route_profile = [
        {"cum_km": round(p[3], 3), "ele": round(p[2], 1), "stage_index": p[5]}
        for p in all_pts_with_time[::step]
    ]

    # --- Build output ---
    stages_out = [
        {
            "name": sd["name"],
            "date": sd["date"],
            "start_km": round(sd["start_km"], 3),
            "end_km": round(sd["end_km"], 3),
        }
        for sd in stage_data
    ]

    waypoints_out = [
        {
            "lat":         round(w["lat"], 5),
            "lon":         round(w["lon"], 5),
            "ele":         round(w["ele"], 1),
            "cum_km":      round(w["cum_km"], 3),
            "tobler_h":    round(w["tobler_h"], 4),
            "stage_index": w["stage_index"],
        }
        for w in sample_waypoints
    ]

    data = {
        "total_km":     round(total_km, 3),
        "stages":       stages_out,
        "route_profile": route_profile,
        "waypoints":    waypoints_out,
        "peaks":        peak_pts,
        "overnights":   overnight_pts,
    }

    with open("route_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize("route_data.json") / 1024
    print(f"Saved route_data.json ({size_kb:.0f} KB)")
    print(f"  {len(stages_out)} stages, {len(waypoints_out)} waypoints, "
          f"{len(route_profile)} profile points")

    # Sanity-check tobler_h
    all_th = [w["tobler_h"] for w in waypoints_out] + \
             [p["tobler_h"] for p in peak_pts] + \
             [o["tobler_h"] for o in overnight_pts]
    print(f"  tobler_h range: {min(all_th):.2f} – {max(all_th):.2f} hours")


if __name__ == "__main__":
    main()
