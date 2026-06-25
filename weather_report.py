"""
Ötztal Trek Weather Reporter
Parses all GPX stages, picks key points (overnight stays, peaks, valleys),
fetches current weather from Open-Meteo, and reports hottest/coldest spots.
"""

import glob
import os
import time
import requests
import gpxpy
import gpxpy.gpx

# WMO weather code descriptions
WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Heavy showers",
    85: "Light snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm+hail", 99: "Heavy thunderstorm+hail",
}


def parse_gpx_stage(filepath):
    """Return list of (lat, lon, ele) for a GPX track."""
    with open(filepath, encoding="utf-8") as f:
        gpx = gpxpy.parse(f)
    points = []
    for track in gpx.tracks:
        for seg in track.segments:
            for pt in seg.points:
                points.append((pt.latitude, pt.longitude, pt.elevation or 0))
    return points


def find_key_points(stage_name, points):
    """
    Extract key points from a track:
    - start (overnight stay from previous stage)
    - end (overnight stay)
    - highest point (mountain pass / peak)
    - lowest point (valley)
    - a few evenly-spaced mid points for coverage
    """
    if not points:
        return []

    n = len(points)
    start = points[0]
    end = points[-1]
    peak = max(points, key=lambda p: p[2])
    valley = min(points[1:-1], key=lambda p: p[2]) if n > 2 else points[n // 2]

    # Sample ~3 evenly spaced mid-route points
    mids = [points[n // 4], points[n // 2], points[3 * n // 4]]

    seen = set()
    key = []
    for pt, label in [
        (start, "Start (overnight)"),
        (mids[0], "¼ route"),
        (mids[1], "½ route"),
        (mids[2], "¾ route"),
        (peak, f"Highest point ({peak[2]:.0f}m)"),
        (valley, f"Lowest point ({valley[2]:.0f}m)"),
        (end, "End (overnight)"),
    ]:
        sig = (round(pt[0], 3), round(pt[1], 3))
        if sig not in seen:
            seen.add(sig)
            key.append((pt, label))

    return key


def get_weather(lat, lon):
    """Fetch current weather from Open-Meteo."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,apparent_temperature,weathercode,windspeed_10m,precipitation,snowfall",
        "timezone": "Europe/Vienna",
        "forecast_days": 1,
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()["current"]


def main():
    gpx_files = sorted(glob.glob("*.gpx"))
    if not gpx_files:
        print("No GPX files found in current directory.")
        return

    all_readings = []  # (temp, stage_name, label, ele, lat, lon, weather)

    for filepath in gpx_files:
        # Extract a clean stage name from filename
        name = os.path.basename(filepath)
        name = name.replace(".gpx", "").replace("_", " ")
        # Shorten: extract just stage number and endpoints
        parts = name.split(" - ", 1)
        stage_num = parts[0].strip()
        if len(parts) > 1:
            route_part = parts[1]
            # Extract just the hut names from parentheses
            if "(" in route_part and ")" in route_part:
                inner = route_part[route_part.index("(") + 1 : route_part.rindex(")")]
                stage_label = f"{stage_num}: {inner}"
            else:
                stage_label = f"{stage_num}: {route_part}"
        else:
            stage_label = stage_num

        print(f"\n{'='*60}")
        print(f"  {stage_label}")
        print(f"{'='*60}")

        points = parse_gpx_stage(filepath)
        print(f"  Track points: {len(points)}, "
              f"Ele range: {min(p[2] for p in points):.0f}m – {max(p[2] for p in points):.0f}m")

        key_points = find_key_points(stage_label, points)

        for (lat, lon, ele), label in key_points:
            try:
                w = get_weather(lat, lon)
                temp = w["temperature_2m"]
                feels = w["apparent_temperature"]
                code = w.get("weathercode", 0)
                wind = w["windspeed_10m"]
                precip = w.get("precipitation", 0)
                snow = w.get("snowfall", 0)
                condition = WMO_CODES.get(int(code), f"Code {code}")

                snow_str = f", snow {snow}cm" if snow and snow > 0 else ""
                precip_str = f", precip {precip}mm" if precip and precip > 0 else ""

                print(f"\n  [{label}]")
                print(f"    Coords : {lat:.4f}°N, {lon:.4f}°E  @ {ele:.0f}m")
                print(f"    Temp   : {temp:.1f}°C (feels {feels:.1f}°C)")
                print(f"    Wind   : {wind:.0f} km/h")
                print(f"    Sky    : {condition}{precip_str}{snow_str}")

                all_readings.append((temp, stage_label, label, ele, lat, lon, w))
                time.sleep(0.3)  # be polite to the API

            except Exception as e:
                print(f"    ! Weather fetch failed: {e}")

    # Summary
    if all_readings:
        all_readings.sort(key=lambda x: x[0])
        coldest = all_readings[0]
        hottest = all_readings[-1]

        print(f"\n{'='*60}")
        print("  SUMMARY: TEMPERATURE EXTREMES ALONG THE ROUTE")
        print(f"{'='*60}")
        print(f"\n  COLDEST: {coldest[0]:.1f}°C")
        print(f"    Stage : {coldest[1]}")
        print(f"    Point : {coldest[2]}")
        print(f"    Elev  : {coldest[3]:.0f}m  ({coldest[4]:.4f}°N, {coldest[5]:.4f}°E)")
        cond = WMO_CODES.get(int(coldest[6].get("weathercode", 0)), "")
        print(f"    Sky   : {cond}")

        print(f"\n  HOTTEST: {hottest[0]:.1f}°C")
        print(f"    Stage : {hottest[1]}")
        print(f"    Point : {hottest[2]}")
        print(f"    Elev  : {hottest[3]:.0f}m  ({hottest[4]:.4f}°N, {hottest[5]:.4f}°E)")
        cond = WMO_CODES.get(int(hottest[6].get("weathercode", 0)), "")
        print(f"    Sky   : {cond}")

        # Overnight stays (start of stage 1 + all ends)
        print(f"\n  OVERNIGHT STAYS:")
        overnights = [r for r in all_readings if "overnight" in r[2].lower()]
        overnights.sort(key=lambda x: x[1])  # sort by stage
        for r in overnights:
            cond = WMO_CODES.get(int(r[6].get("weathercode", 0)), "")
            print(f"    {r[1]} / {r[2]}")
            print(f"      {r[0]:.1f}°C, {r[6]['windspeed_10m']:.0f} km/h wind, {cond}  @ {r[3]:.0f}m")


if __name__ == "__main__":
    main()
