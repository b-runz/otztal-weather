"""
Generates site/index.html with the embedded weather graph and summary tables.
Run this in the directory that contains the GPX files.
"""

import base64
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import weather_graph

VIENNA = ZoneInfo("Europe/Vienna")

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Light showers", 81: "Showers", 82: "Heavy showers",
    85: "Light snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm+hail",
}

HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ötztal Trek — Live Weather</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      background: #f2f2f2;
      color: #1a1a1a;
      padding: 1.5rem;
    }}
    .wrap {{ max-width: 1080px; margin: 0 auto; }}
    header {{ margin-bottom: 1.25rem; }}
    h1 {{ font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em; }}
    .sub {{ color: #555; margin-top: 0.2rem; font-size: 0.95rem; }}
    .updated {{ color: #999; font-size: 0.8rem; margin-top: 0.4rem; }}
    .card {{
      background: #fff;
      border-radius: 10px;
      box-shadow: 0 1px 3px rgba(0,0,0,.08);
      padding: 1rem;
      margin-bottom: 1rem;
    }}
    .graph img {{ width: 100%; height: auto; display: block; border-radius: 4px; }}
    .extremes {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
    .extreme-label {{
      font-size: 0.7rem; text-transform: uppercase; letter-spacing: .08em;
      color: #888; margin-bottom: .25rem;
    }}
    .temp-big {{ font-size: 2.8rem; font-weight: 700; line-height: 1; }}
    .hot {{ color: #e84b3a; }}
    .cold {{ color: #2255aa; }}
    .detail {{ color: #666; font-size: 0.82rem; margin-top: .35rem; }}
    h2 {{ font-size: 0.85rem; text-transform: uppercase; letter-spacing: .07em; color: #666; margin-bottom: .75rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    thead th {{
      text-align: left; padding: .4rem .75rem;
      background: #f7f7f7; font-size: 0.75rem;
      text-transform: uppercase; letter-spacing: .06em; color: #888;
      border-bottom: 1px solid #eee;
    }}
    tbody td {{ padding: .5rem .75rem; border-bottom: 1px solid #f0f0f0; }}
    tbody tr:last-child td {{ border-bottom: none; }}
    .badge {{
      display: inline-block; padding: .15rem .45rem; border-radius: 4px;
      font-size: 0.75rem; font-weight: 600;
    }}
    .badge-hot {{ background: #fce8e6; color: #c0392b; }}
    .badge-cold {{ background: #e8edf8; color: #1a4488; }}
    .badge-mid {{ background: #f0f0f0; color: #555; }}
    footer {{ margin-top: 1.5rem; color: #bbb; font-size: 0.75rem; text-align: center; }}
    @media (max-width: 600px) {{
      .extremes {{ grid-template-columns: 1fr; }}
      .temp-big {{ font-size: 2.2rem; }}
    }}
  </style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Ötztal Trek — Live Weather</h1>
    <p class="sub">Current conditions along the 4-stage route through the Austrian Alps</p>
    <p class="updated">Updated {updated} &nbsp;·&nbsp; {total_km:.1f} km total route</p>
  </header>

  <div class="card graph">
    <img src="data:image/png;base64,{img_b64}" alt="Temperature and elevation profile along the Ötztal Trek">
  </div>

  <div class="extremes" style="margin-bottom:1rem">
    <div class="card">
      <div class="extreme-label">Hottest point now</div>
      <div class="temp-big hot">{hottest_temp:.1f}°C</div>
      <div class="detail">{hottest_ele:.0f} m elevation &nbsp;·&nbsp; {hottest_km:.1f} km into route</div>
    </div>
    <div class="card">
      <div class="extreme-label">Coldest point now</div>
      <div class="temp-big cold">{coldest_temp:.1f}°C</div>
      <div class="detail">{coldest_ele:.0f} m elevation &nbsp;·&nbsp; {coldest_km:.1f} km into route</div>
    </div>
  </div>

  <div class="card">
    <h2>Stage high points</h2>
    <table>
      <thead><tr><th>Stage</th><th>Elevation</th><th>Temperature</th></tr></thead>
      <tbody>{peaks_rows}</tbody>
    </table>
  </div>

  <div class="card" style="margin-top:1rem">
    <h2>Overnight stays</h2>
    <table>
      <thead><tr><th>Location</th><th>Stage</th><th>Elevation</th><th>Temperature</th></tr></thead>
      <tbody>{overnights_rows}</tbody>
    </table>
  </div>

  <footer>
    Data: <a href="https://open-meteo.com/" style="color:#bbb">Open-Meteo</a> &nbsp;·&nbsp;
    Routes: Ötztal Trek Highlights (RideWithGPS) &nbsp;·&nbsp;
    Refreshed hourly 08:00–20:00 CEST
  </footer>
</div>
</body>
</html>
"""


def temp_badge(t):
    if t >= 20:
        return f'<span class="badge badge-hot">{t:.1f}°C</span>'
    elif t <= 13:
        return f'<span class="badge badge-cold">{t:.1f}°C</span>'
    else:
        return f'<span class="badge badge-mid">{t:.1f}°C</span>'


def main():
    os.makedirs("site", exist_ok=True)

    print("Generating weather graph...")
    data = weather_graph.main()

    with open("otztal_weather.png", "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    now = datetime.now(VIENNA)
    updated = now.strftime("%A %d %B %Y, %H:%M CEST")

    # Stage name lookup by km range
    def stage_name_for_km(km):
        for s in data["stages"]:
            if s["start_km"] <= km <= s["end_km"] + 0.5:
                return s["name"].replace("\n", " – ")
        return "—"

    # Peaks table
    peak_rows = []
    for lat, lon, ele, km, label, temp in data["peaks"]:
        stage = stage_name_for_km(km)
        peak_rows.append(
            f"<tr><td>{stage}</td>"
            f"<td>{ele:.0f} m</td>"
            f"<td>{temp_badge(temp)}</td></tr>"
        )

    # Overnights table — deduplicate consecutive same-location entries
    seen_km = set()
    overnight_rows = []
    for lat, lon, ele, km, label, temp in data["overnights"]:
        key = round(km, 1)
        if key in seen_km:
            continue
        seen_km.add(key)
        stage = stage_name_for_km(km)
        overnight_rows.append(
            f"<tr><td>{label}</td>"
            f"<td>{stage}</td>"
            f"<td>{ele:.0f} m</td>"
            f"<td>{temp_badge(temp)}</td></tr>"
        )

    html = HTML.format(
        updated=updated,
        total_km=data["total_km"],
        img_b64=img_b64,
        hottest_temp=data["hottest"]["temp"],
        hottest_ele=data["hottest"]["ele"],
        hottest_km=data["hottest"]["km"],
        coldest_temp=data["coldest"]["temp"],
        coldest_ele=data["coldest"]["ele"],
        coldest_km=data["coldest"]["km"],
        peaks_rows="\n".join(peak_rows),
        overnights_rows="\n".join(overnight_rows),
    )

    out = "site/index.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
