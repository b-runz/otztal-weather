"""
Generates site/index.html with an interactive Plotly weather chart.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import weather_graph

VIENNA = ZoneInfo("Europe/Vienna")

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
      background: #f0f0f0;
      color: #1a1a1a;
      min-height: 100dvh;
    }}

    .page {{ max-width: 1100px; margin: 0 auto; padding: 1.25rem 1rem 2rem; }}

    /* Header */
    header {{ margin-bottom: 1.1rem; }}
    h1 {{ font-size: clamp(1.25rem, 4vw, 1.7rem); font-weight: 700; letter-spacing: -0.02em; line-height: 1.2; }}
    .sub {{ color: #555; margin-top: 0.2rem; font-size: 0.92rem; }}
    .updated {{ color: #aaa; font-size: 0.78rem; margin-top: 0.35rem; }}

    /* Cards */
    .card {{
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 1px 4px rgba(0,0,0,.07);
      padding: 1rem;
      margin-bottom: 1rem;
    }}

    /* Chart — fixed-width Plotly div inside a horizontal scroll container */
    .chart-card {{ padding: 0.5rem 0 0; overflow-x: auto; -webkit-overflow-scrolling: touch; }}
    .chart-card::-webkit-scrollbar {{ height: 6px; }}
    .chart-card::-webkit-scrollbar-track {{ background: #f0f0f0; border-radius: 3px; }}
    .chart-card::-webkit-scrollbar-thumb {{ background: #ccc; border-radius: 3px; }}

    /* Extremes grid */
    .extremes {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
      margin-bottom: 1rem;
    }}
    @media (max-width: 480px) {{
      .extremes {{ grid-template-columns: 1fr; gap: 0.75rem; }}
    }}
    .extreme-label {{
      font-size: 0.68rem; text-transform: uppercase;
      letter-spacing: .08em; color: #999; margin-bottom: .2rem;
    }}
    .temp-big {{ font-size: clamp(2rem, 8vw, 2.8rem); font-weight: 700; line-height: 1; }}
    .hot  {{ color: #e84b3a; }}
    .cold {{ color: #2255aa; }}
    .detail {{ color: #777; font-size: 0.8rem; margin-top: .35rem; }}

    /* Tables */
    h2 {{
      font-size: 0.72rem; text-transform: uppercase;
      letter-spacing: .08em; color: #888; margin-bottom: .7rem;
    }}
    .table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.86rem; white-space: nowrap; }}
    thead th {{
      text-align: left; padding: .35rem .7rem;
      background: #f8f8f8;
      font-size: 0.72rem; text-transform: uppercase;
      letter-spacing: .06em; color: #999;
      border-bottom: 1px solid #eee;
    }}
    tbody td {{ padding: .5rem .7rem; border-bottom: 1px solid #f2f2f2; }}
    tbody tr:last-child td {{ border-bottom: none; }}
    tbody tr:hover td {{ background: #fafafa; }}

    /* Temperature badges */
    .badge {{
      display: inline-block; padding: .2rem .5rem;
      border-radius: 5px; font-size: 0.8rem; font-weight: 600;
    }}
    .badge-hot  {{ background: #fce8e6; color: #c0392b; }}
    .badge-cold {{ background: #e8edf8; color: #1a4488; }}
    .badge-mid  {{ background: #f0f0f0; color: #555;    }}

    footer {{
      margin-top: 1.5rem; color: #ccc;
      font-size: 0.72rem; text-align: center; line-height: 1.8;
    }}
    footer a {{ color: #bbb; text-decoration: none; }}
    footer a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
<div class="page">

  <header>
    <h1>Ötztal Trek — Live Weather</h1>
    <p class="sub">Current conditions along the 4-stage route through the Austrian Alps</p>
    <p class="updated">Updated {updated} &nbsp;·&nbsp; {total_km:.1f} km total</p>
  </header>

  <div class="card chart-card">
    {chart_html}
  </div>

  <div class="extremes">
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

  <div class="card" style="margin-bottom:1rem">
    <h2>Stage high points</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Stage</th><th>Elevation</th><th>Temperature</th></tr></thead>
        <tbody>{peaks_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <h2>Overnight stays</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Location</th><th>Stage</th><th>Elevation</th><th>Temperature</th></tr></thead>
        <tbody>{overnights_rows}</tbody>
      </table>
    </div>
  </div>

  <footer>
    Weather: <a href="https://open-meteo.com/">Open-Meteo</a> &nbsp;·&nbsp;
    Routes: Ötztal Trek Highlights via RideWithGPS &nbsp;·&nbsp;
    Refreshed hourly 08:00–20:00 CEST
  </footer>

</div>
</body>
</html>
"""


def temp_badge(t):
    if t >= 20:
        cls = "badge-hot"
    elif t <= 13:
        cls = "badge-cold"
    else:
        cls = "badge-mid"
    return f'<span class="badge {cls}">{t:.1f}°C</span>'


def main():
    os.makedirs("site", exist_ok=True)

    print("Generating weather data and chart...")
    data = weather_graph.main()

    now = datetime.now(VIENNA)
    updated = now.strftime("%A %d %B %Y, %H:%M CEST")

    def stage_name_for_km(km):
        for s in data["stages"]:
            if s["start_km"] <= km <= s["end_km"] + 0.5:
                return s["name"]
        return "—"

    # Peaks table
    peak_rows = []
    for lat, lon, ele, km, label, temp in data["peaks"]:
        stage = stage_name_for_km(km)
        peak_rows.append(
            f"<tr><td>{stage}</td><td>{ele:.0f} m</td><td>{temp_badge(temp)}</td></tr>"
        )

    # Overnights table — deduplicate by rounded km
    seen_km = set()
    overnight_rows = []
    for lat, lon, ele, km, label, temp in data["overnights"]:
        key = round(km, 1)
        if key in seen_km:
            continue
        seen_km.add(key)
        stage = stage_name_for_km(km)
        overnight_rows.append(
            f"<tr><td>{label}</td><td>{stage}</td>"
            f"<td>{ele:.0f} m</td><td>{temp_badge(temp)}</td></tr>"
        )

    html = HTML.format(
        updated=updated,
        total_km=data["total_km"],
        chart_html=data["chart_html"],
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
    size_kb = os.path.getsize(out) / 1024
    print(f"Saved: {out}  ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
