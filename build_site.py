"""
Generates site/index.html with an interactive Plotly weather chart,
and site/forecast.html with an interactive Jul 6-9 forecast page.
"""

import json
import math
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import weather_graph


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
    <p style="margin-top:.6rem">
      <a href="forecast.html" style="display:inline-block;padding:.35rem .8rem;background:#2255aa;color:#fff;border-radius:7px;font-size:.85rem;font-weight:600;text-decoration:none;letter-spacing:.01em">Jul 6–9 Forecast →</a>
      &nbsp;
      <a href="history.html" style="display:inline-block;padding:.35rem .8rem;background:#555;color:#fff;border-radius:7px;font-size:.85rem;font-weight:600;text-decoration:none;letter-spacing:.01em">10-Day History →</a>
    </p>
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


# ---------------------------------------------------------------------------
# Forecast page
# ---------------------------------------------------------------------------

FORECAST_START_DATE = "2026-07-06"
FORECAST_END_DATE   = "2026-07-09"
WINDOW_EARLY_H = 6    # earliest reasonable start (06:00)
WINDOW_LATE_H  = 12   # latest reasonable start (12:00)
FORECAST_BATCH = 10


def _get_hourly_window_batch(waypoints, stages):
    """Fetch hourly forecast for a batch of waypoints.
    Returns one dict per waypoint with keys 'temps', 'precip', 'precip_prob',
    each a {ISO_hour: value} mapping covering only the arrival window.
    """
    lats = ",".join(f"{w['lat']:.5f}" for w in waypoints)
    lons = ",".join(f"{w['lon']:.5f}" for w in waypoints)
    r = _get_with_retry(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lats, "longitude": lons,
            "hourly": "temperature_2m,precipitation,precipitation_probability",
            "timezone": "Europe/Vienna",
            "start_date": FORECAST_START_DATE, "end_date": FORECAST_END_DATE,
        },
    )
    data = r.json()
    if not isinstance(data, list):
        data = [data]

    results = []
    for w, d in zip(waypoints, data):
        by_temp  = dict(zip(d["hourly"]["time"], d["hourly"]["temperature_2m"]))
        by_prec  = dict(zip(d["hourly"]["time"], d["hourly"]["precipitation"]))
        by_prob  = dict(zip(d["hourly"]["time"], d["hourly"]["precipitation_probability"]))
        stage_date = stages[w["stage_index"]]["date"]
        early = int(WINDOW_EARLY_H + w["tobler_h"])
        late  = math.ceil(WINDOW_LATE_H + w["tobler_h"])
        temps = {}
        precip = {}
        precip_prob = {}
        for h in range(early, late + 1):
            iso = f"{stage_date}T{h:02d}:00"
            v = by_temp.get(iso)
            if v is not None:
                temps[iso] = round(v, 1)
            v = by_prec.get(iso)
            if v is not None:
                precip[iso] = round(v, 2)
            v = by_prob.get(iso)
            if v is not None:
                precip_prob[iso] = v
        results.append({"temps": temps, "precip": precip, "precip_prob": precip_prob})
    return results

_FORECAST_HEAD = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ötztal Trek — Jul 6–9 Forecast</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
           background: #f0f0f0; color: #1a1a1a; min-height: 100dvh; }
    .page { max-width: 1100px; margin: 0 auto; padding: 1.25rem 1rem 2rem; }
    header { margin-bottom: 1.1rem; display: flex; justify-content: space-between; align-items: flex-start; }
    .header-left h1 { font-size: clamp(1.25rem, 4vw, 1.7rem); font-weight: 700; letter-spacing: -0.02em; }
    .sub { color: #555; margin-top: 0.2rem; font-size: 0.92rem; }
    .updated { color: #aaa; font-size: 0.78rem; margin-top: 0.35rem; }
    .back-link { font-size: .85rem; color: #2255aa; text-decoration: none; white-space: nowrap; padding-top: .2rem; }
    .back-link:hover { text-decoration: underline; }
    .card { background: #fff; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.07);
            padding: 1rem; margin-bottom: 1rem; }
    .controls-card { display: flex; align-items: center; gap: 1rem; padding: .75rem 1rem; flex-wrap: wrap; }
    .controls-card label { font-size: .88rem; color: #444; display: flex; align-items: center; gap: .5rem; }
    .controls-card input[type=time],
    .controls-card select { font-size: 1rem; padding: .3rem .5rem;
                            border: 1px solid #ddd; border-radius: 6px; color: #1a1a1a; }
    .chart-card { padding: .5rem 0 0; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .chart-card::-webkit-scrollbar { height: 6px; }
    .chart-card::-webkit-scrollbar-track { background: #f0f0f0; border-radius: 3px; }
    .chart-card::-webkit-scrollbar-thumb { background: #ccc; border-radius: 3px; }
    h2 { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: #888; margin-bottom: .7rem; }
    .table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
    table { width: 100%; border-collapse: collapse; font-size: .86rem; white-space: nowrap; }
    thead th { text-align: left; padding: .35rem .7rem; background: #f8f8f8;
               font-size: .72rem; text-transform: uppercase; letter-spacing: .06em;
               color: #999; border-bottom: 1px solid #eee; }
    tbody td { padding: .5rem .7rem; border-bottom: 1px solid #f2f2f2; }
    tbody tr:last-child td { border-bottom: none; }
    tbody tr:hover td { background: #fafafa; }
    .badge { display: inline-block; padding: .2rem .5rem; border-radius: 5px; font-size: .8rem; font-weight: 600; }
    .badge-hot  { background: #fce8e6; color: #c0392b; }
    .badge-cold { background: #e8edf8; color: #1a4488; }
    .badge-mid  { background: #f0f0f0; color: #555; }
    .extremes { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; margin-bottom: 1rem; }
    @media (max-width: 600px) { .extremes { grid-template-columns: 1fr; gap: .75rem; } }
    .extreme-label { font-size: .68rem; text-transform: uppercase; letter-spacing: .08em; color: #999; margin-bottom: .2rem; }
    .temp-big { font-size: clamp(2rem, 8vw, 2.8rem); font-weight: 700; line-height: 1; }
    .hot  { color: #e84b3a; }
    .cold { color: #2255aa; }
    .detail { color: #777; font-size: .8rem; margin-top: .35rem; }
    .complete-msg { padding: 3rem; text-align: center; color: #888; font-size: 1rem; }
    footer { margin-top: 1.5rem; color: #ccc; font-size: .72rem; text-align: center; line-height: 1.8; }
    footer a { color: #bbb; text-decoration: none; }
    footer a:hover { text-decoration: underline; }
  </style>
</head>
<body>
<div class="page">
  <header>
    <div class="header-left">
      <h1>Ötztal Trek — Jul 6–9 Forecast</h1>
      <p class="sub">Select a stage and start time to see forecast temperatures for that day</p>
      <p class="updated">Forecast data built __BUILT__ &nbsp;·&nbsp; __TOTAL_KM__ km total</p>
    </div>
    <a href="index.html" class="back-link">← Current conditions</a>
  </header>

  <div class="card controls-card">
    <label>Stage:
      <select id="start-stage"></select>
    </label>
    <label>Start time:
      <input type="time" id="start-time" min="06:00" max="12:00" value="09:00" step="1800">
    </label>
  </div>

  <div class="card chart-card">
    <div id="forecast-chart"></div>
  </div>

  <div class="extremes">
    <div class="card">
      <div class="extreme-label">Hottest point on route</div>
      <div class="temp-big hot" id="hottest-temp">—</div>
      <div class="detail" id="hottest-detail"></div>
    </div>
    <div class="card">
      <div class="extreme-label">Coldest point on route</div>
      <div class="temp-big cold" id="coldest-temp">—</div>
      <div class="detail" id="coldest-detail"></div>
    </div>
    <div class="card">
      <div class="extreme-label">Highest rain probability</div>
      <div class="temp-big" style="color:#2255aa" id="max-precip-prob">—</div>
      <div class="detail" id="max-precip-detail"></div>
    </div>
  </div>

  <div class="card" style="margin-bottom:1rem">
    <h2>Stage high points</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Stage</th><th>Date</th><th>Est. arrival</th><th>Elevation</th><th>Temperature</th></tr></thead>
        <tbody id="peaks-body"></tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <h2>Overnight stays</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Location</th><th>Stage</th><th>Date</th><th>Est. arrival</th><th>Elevation</th><th>Temperature</th></tr></thead>
        <tbody id="overnights-body"></tbody>
      </table>
    </div>
  </div>

  <div class="card chart-card">
    <div id="precip-chart"></div>
  </div>

  <footer>
    Weather: <a href="https://open-meteo.com/">Open-Meteo</a> &nbsp;·&nbsp;
    Routes: Ötztal Trek Highlights via RideWithGPS &nbsp;·&nbsp;
    Hiking speed: Tobler's function
  </footer>
</div>

<script>
const ROUTE = __ROUTE_JSON__;
const WAYPOINTS = __WAYPOINTS_JSON__;
</script>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>
"""

_FORECAST_JS = r"""
(function () {
  const todayStr = new Date().toLocaleDateString('sv');
  const stages = ROUTE.stages;

  const stageSel = document.getElementById('start-stage');
  stages.forEach((s, i) => {
    const opt = document.createElement('option');
    opt.value = i;
    opt.textContent = s.name + ' · ' + s.date;
    stageSel.appendChild(opt);
  });
  const autoFirst = Math.max(0, stages.findIndex(s => s.date >= todayStr));
  stageSel.value = autoFirst;

  let activeStages, activeWaypoints, activeProfile, activePeaks, activeOvernights;

  function refreshActive() {
    const first = parseInt(stageSel.value, 10);
    const stage = stages[first];
    activeStages     = stages.slice(first, first + 1);
    activeWaypoints  = WAYPOINTS.filter(w => w.stage_index === first);
    activeProfile    = ROUTE.route_profile.filter(p => p.stage_index === first);
    activePeaks      = ROUTE.peaks.filter(p => p.stage_index === first);
    activeOvernights = ROUTE.overnights
      .filter(p => p.cum_km >= stage.start_km - 0.5 && p.cum_km <= stage.end_km + 0.5)
      .map(p => p.stage_index < first
        ? {...p, tobler_h: 0, stage_index: first, isStartPoint: true}
        : p);
  }

  function fmtH(totalH) {
    const h = Math.floor(totalH), m = Math.round((totalH - h) * 60);
    return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
  }

  function getField(w, field, startH) {
    const src = w[field];
    if (!src) return null;
    const roundedH = Math.round(startH + w.tobler_h);
    const iso = stages[w.stage_index].date + 'T' + String(roundedH).padStart(2, '0') + ':00';
    if (src[iso] !== undefined) return src[iso];
    let best = null, bestDiff = Infinity;
    for (const [k, v] of Object.entries(src)) {
      const diff = Math.abs(parseInt(k.slice(11, 13), 10) - roundedH);
      if (diff < bestDiff) { bestDiff = diff; best = v; }
    }
    return best;
  }

  const getTemp       = (w, h) => getField(w, 'temps',       h);
  const getPrecipMM   = (w, h) => getField(w, 'precip',      h);
  const getPrecipProb = (w, h) => getField(w, 'precip_prob', h);

  function getTempForKP(pt, startH) {
    const stageWps = WAYPOINTS.filter(w => w.stage_index === pt.stage_index);
    if (!stageWps.length) return null;
    const nearest = stageWps.reduce((a, b) =>
      Math.abs(a.cum_km - pt.cum_km) < Math.abs(b.cum_km - pt.cum_km) ? a : b
    );
    return getTemp({...nearest, tobler_h: pt.tobler_h}, startH);
  }

  function interp(km, wpSorted, byKm) {
    if (!wpSorted.length) return null;
    if (km <= wpSorted[0].cum_km) return byKm[wpSorted[0].cum_km];
    const last = wpSorted[wpSorted.length - 1];
    if (km >= last.cum_km) return byKm[last.cum_km];
    for (let i = 0; i < wpSorted.length - 1; i++) {
      const a = wpSorted[i], b = wpSorted[i + 1];
      if (a.cum_km <= km && km <= b.cum_km) {
        const t = (km - a.cum_km) / (b.cum_km - a.cum_km);
        return byKm[a.cum_km] * (1 - t) + byKm[b.cum_km] * t;
      }
    }
    return byKm[last.cum_km];
  }

  function tempBadge(t) {
    if (t == null) return '—';
    const cls = t >= 20 ? 'badge-hot' : t <= 13 ? 'badge-cold' : 'badge-mid';
    return `<span class="badge ${cls}">${t.toFixed(1)}°C</span>`;
  }

  function stageForKm(km) {
    for (const s of activeStages)
      if (km >= s.start_km && km <= s.end_km) return s.name;
    return activeStages[activeStages.length - 1]?.name ?? '';
  }

  let tempInitialized = false;
  let precipInitialized = false;

  function redraw() {
    refreshActive();

    const val = document.getElementById('start-time').value || '09:00';
    const [hh, mm] = val.split(':').map(Number);
    const startH = hh + mm / 60;

    // ── Temperature ──
    const byKm = {};
    for (const w of activeWaypoints) {
      const t = getTemp(w, startH);
      if (t != null) byKm[w.cum_km] = t;
    }
    const wpSorted = activeWaypoints.filter(w => byKm[w.cum_km] != null);

    const xArr    = activeProfile.map(p => p.cum_km);
    const eleArr  = activeProfile.map(p => p.ele);
    const tmpArr  = activeProfile.map(p => interp(p.cum_km, wpSorted, byKm));
    const custArr = activeProfile.map(p => [Math.round(p.ele), stageForKm(p.cum_km)]);

    const tempTraces = [
      {
        x: xArr, y: eleArr, type: 'scatter',
        fill: 'tozeroy', fillcolor: 'rgba(139,115,85,0.15)',
        line: {color: 'rgba(139,115,85,0.35)', width: 1},
        name: 'Elevation', yaxis: 'y2',
        hovertemplate: '⛰ %{y:.0f} m<extra>Elevation</extra>'
      },
      {
        x: xArr, y: tmpArr, type: 'scatter',
        line: {color: '#E84B3A', width: 2.5},
        fill: 'tonexty', fillcolor: 'rgba(232,75,58,0.07)',
        name: 'Forecast temp', customdata: custArr,
        hovertemplate: '<b>%{x:.1f} km</b><br>🌡 %{y:.1f}°C<br>⛰ %{customdata[0]} m<br><span style="color:#999">%{customdata[1]}</span><extra>Route</extra>'
      }
    ];

    if (activePeaks.length) tempTraces.push({
      x: activePeaks.map(p => p.cum_km),
      y: activePeaks.map(p => getTempForKP(p, startH)),
      mode: 'markers', type: 'scatter',
      marker: {symbol: 'triangle-up', size: 15, color: '#1a6b3c', line: {color: 'white', width: 1.5}},
      name: 'Stage peak',
      customdata: activePeaks.map(p => [p.name, p.ele, fmtH(startH + p.tobler_h), stages[p.stage_index].date]),
      hovertemplate: '<b>▲ %{customdata[0]}</b><br>🌡 %{y:.1f}°C<br>⛰ %{customdata[1]:.0f} m<br>~%{customdata[2]} on %{customdata[3]}<extra>Peak</extra>'
    });

    if (activeOvernights.length) tempTraces.push({
      x: activeOvernights.map(p => p.cum_km),
      y: activeOvernights.map(p => getTempForKP(p, startH)),
      mode: 'markers', type: 'scatter',
      marker: {symbol: 'square', size: 12, color: '#2255aa', line: {color: 'white', width: 1.5}},
      name: 'Overnight stay',
      customdata: activeOvernights.map(p => [p.name, p.ele, fmtH(startH + p.tobler_h), stages[p.stage_index].date]),
      hovertemplate: '<b>🏠 %{customdata[0]}</b><br>🌡 %{y:.1f}°C<br>⛰ %{customdata[1]:.0f} m<br>~%{customdata[2]} on %{customdata[3]}<extra>Overnight</extra>'
    });

    const maxEle = Math.max(...eleArr.filter(Number.isFinite));
    const stageShapes = activeStages.slice(0, -1).map(s => ({
      type: 'line', x0: s.end_km, x1: s.end_km, y0: 0, y1: 1, yref: 'paper',
      line: {dash: 'dash', color: 'rgba(0,0,0,0.18)', width: 1}
    }));
    const stageAnnotations = activeStages.map(s => ({
      x: (s.start_km + s.end_km) / 2, y: 1.0, xref: 'x', yref: 'paper',
      text: s.name + ' · ' + s.date, showarrow: false,
      font: {size: 9, color: '#888'}, align: 'center',
      yanchor: 'bottom', bgcolor: 'rgba(255,255,255,0.7)'
    }));

    const tempLayout = {
      xaxis: {title: 'Distance along route (km)', showgrid: true, gridcolor: 'rgba(0,0,0,0.06)', zeroline: false},
      yaxis: {
        title: {text: 'Forecast temperature (°C)', font: {color: '#E84B3A'}},
        tickfont: {color: '#E84B3A'}, showgrid: true, gridcolor: 'rgba(0,0,0,0.06)', zeroline: false
      },
      yaxis2: {
        title: {text: 'Elevation (m)', font: {color: '#8B7355'}},
        tickfont: {color: '#8B7355'}, overlaying: 'y', side: 'right',
        showgrid: false, range: [0, maxEle * 1.5]
      },
      hovermode: 'x unified', dragmode: false,
      legend: {orientation: 'h', yanchor: 'bottom', y: 1.06, xanchor: 'left', x: 0, font: {size: 11}},
      plot_bgcolor: 'white', paper_bgcolor: 'white',
      margin: {l: 55, r: 65, t: 90, b: 50}, height: 440, width: 1000, autosize: false,
      shapes: stageShapes, annotations: stageAnnotations
    };

    const cfg = {responsive: true, displayModeBar: false, scrollZoom: false};
    if (!tempInitialized) { Plotly.newPlot('forecast-chart', tempTraces, tempLayout, cfg); tempInitialized = true; }
    else                   { Plotly.react('forecast-chart', tempTraces, tempLayout, cfg); }

    // ── Precipitation ──
    const byKmProb = {}, byKmMM = {};
    for (const w of activeWaypoints) {
      const p = getPrecipProb(w, startH);  if (p != null) byKmProb[w.cum_km] = p;
      const m = getPrecipMM(w, startH);    if (m != null) byKmMM[w.cum_km]   = m;
    }
    const wpSortedProb = activeWaypoints.filter(w => byKmProb[w.cum_km] != null);
    const wpSortedMM   = activeWaypoints.filter(w => byKmMM[w.cum_km]   != null);

    const probArr = activeProfile.map(p => interp(p.cum_km, wpSortedProb, byKmProb));
    const mmArr   = activeProfile.map(p => interp(p.cum_km, wpSortedMM,   byKmMM));

    const precipTraces = [
      {
        x: xArr, y: eleArr, type: 'scatter',
        fill: 'tozeroy', fillcolor: 'rgba(139,115,85,0.15)',
        line: {color: 'rgba(139,115,85,0.35)', width: 1},
        name: 'Elevation', yaxis: 'y2',
        hovertemplate: '⛰ %{y:.0f} m<extra>Elevation</extra>'
      },
      {
        x: xArr, y: probArr, type: 'scatter',
        line: {color: '#2255aa', width: 2.5},
        fill: 'tozeroy', fillcolor: 'rgba(34,85,170,0.12)',
        name: 'Precip probability',
        customdata: mmArr.map((m, i) => [m ?? 0, custArr[i][0], custArr[i][1]]),
        hovertemplate: '<b>%{x:.1f} km</b><br>🌧 %{y:.0f}% · %{customdata[0]:.1f} mm/h<br>⛰ %{customdata[1]} m<br><span style="color:#999">%{customdata[2]}</span><extra>Route</extra>'
      }
    ];

    const precipLayout = {
      xaxis: {title: 'Distance along route (km)', showgrid: true, gridcolor: 'rgba(0,0,0,0.06)', zeroline: false},
      yaxis: {
        title: {text: 'Precipitation probability (%)', font: {color: '#2255aa'}},
        tickfont: {color: '#2255aa'}, showgrid: true, gridcolor: 'rgba(0,0,0,0.06)',
        zeroline: false, range: [0, 100]
      },
      yaxis2: {
        title: {text: 'Elevation (m)', font: {color: '#8B7355'}},
        tickfont: {color: '#8B7355'}, overlaying: 'y', side: 'right',
        showgrid: false, range: [0, maxEle * 1.5]
      },
      hovermode: 'x unified', dragmode: false,
      legend: {orientation: 'h', yanchor: 'bottom', y: 1.06, xanchor: 'left', x: 0, font: {size: 11}},
      plot_bgcolor: 'white', paper_bgcolor: 'white',
      margin: {l: 55, r: 65, t: 55, b: 50}, height: 280, width: 1000, autosize: false,
      shapes: stageShapes,
      annotations: stageAnnotations.map(a => ({...a, xref: 'x', yref: 'paper'}))
    };

    if (!precipInitialized) { Plotly.newPlot('precip-chart', precipTraces, precipLayout, cfg); precipInitialized = true; }
    else                     { Plotly.react('precip-chart', precipTraces, precipLayout, cfg); }

    // ── Peaks table ──
    document.getElementById('peaks-body').innerHTML =
      activePeaks.map(p => {
        const s = stages[p.stage_index];
        return `<tr><td>${s.name}</td><td>${s.date}</td><td>~${fmtH(startH + p.tobler_h)}</td><td>${p.ele.toFixed(0)} m</td><td>${tempBadge(getTempForKP(p, startH))}</td></tr>`;
      }).join('') || '<tr><td colspan="5" style="color:#aaa">—</td></tr>';

    // ── Overnights table ──
    document.getElementById('overnights-body').innerHTML =
      activeOvernights.map(p => {
        const s = stages[p.stage_index];
        const stageLbl = p.cum_km < 0.5 ? 'Route start' : p.isStartPoint ? 'Day start' : s.name;
        return `<tr><td>${p.name}</td><td>${stageLbl}</td><td>${s.date}</td><td>~${fmtH(startH + p.tobler_h)}</td><td>${p.ele.toFixed(0)} m</td><td>${tempBadge(getTempForKP(p, startH))}</td></tr>`;
      }).join('') || '<tr><td colspan="6" style="color:#aaa">—</td></tr>';

    // ── Extremes ──
    const entries = wpSorted.map(w => ({km: w.cum_km, ele: w.ele, temp: byKm[w.cum_km]}));
    if (entries.length) {
      const hot  = entries.reduce((a, b) => a.temp > b.temp ? a : b);
      const cold = entries.reduce((a, b) => a.temp < b.temp ? a : b);
      document.getElementById('hottest-temp').textContent = hot.temp.toFixed(1) + '°C';
      document.getElementById('hottest-detail').textContent =
        `${Math.round(hot.ele)} m elevation · ${hot.km.toFixed(1)} km into route`;
      document.getElementById('coldest-temp').textContent = cold.temp.toFixed(1) + '°C';
      document.getElementById('coldest-detail').textContent =
        `${Math.round(cold.ele)} m elevation · ${cold.km.toFixed(1)} km into route`;
    }

    const precipEntries = activeWaypoints
      .map(w => ({km: w.cum_km, ele: w.ele, prob: getPrecipProb(w, startH), mm: getPrecipMM(w, startH), arrH: startH + w.tobler_h}))
      .filter(e => e.prob != null);
    if (precipEntries.length) {
      const wettest = precipEntries.reduce((a, b) => a.prob > b.prob ? a : b);
      document.getElementById('max-precip-prob').textContent = Math.round(wettest.prob) + '%';
      document.getElementById('max-precip-detail').textContent =
        `~${fmtH(wettest.arrH)} · ${Math.round(wettest.ele)} m · ${wettest.mm != null ? wettest.mm.toFixed(1) + ' mm/h' : ''}`;
    }
  }

  document.getElementById('start-time').addEventListener('input', redraw);
  stageSel.addEventListener('change', redraw);
  redraw();
})();
"""

_FORECAST_FOOT = """\
</script>
</body>
</html>
"""


def build_forecast_site():
    route_path = "route_data.json"
    if not os.path.exists(route_path):
        print(f"Skipping forecast: {route_path} not found (run compute_route.py first)")
        return

    with open(route_path, encoding="utf-8") as f:
        route = json.load(f)

    stages    = route["stages"]
    waypoints = route["waypoints"]

    print(f"Fetching forecast weather for {len(waypoints)} waypoints...")
    weather_list = [None] * len(waypoints)
    time.sleep(2)
    for i in range(0, len(waypoints), FORECAST_BATCH):
        batch = waypoints[i : i + FORECAST_BATCH]
        try:
            batch_weather = _get_hourly_window_batch(batch, stages)
            for j, t in enumerate(batch_weather):
                weather_list[i + j] = t
            print(f"  batch {i // FORECAST_BATCH + 1}/{math.ceil(len(waypoints) / FORECAST_BATCH)} done")
        except Exception as e:
            print(f"  batch failed: {e}")
            for j in range(len(batch)):
                weather_list[i + j] = {}
        time.sleep(1.0)

    def _w(entry, key):
        if not entry:
            return {}
        return entry.get(key, {}) if isinstance(entry, dict) else entry

    waypoints_out = [
        {**w,
         "temps":       _w(t, "temps"),
         "precip":      _w(t, "precip"),
         "precip_prob": _w(t, "precip_prob")}
        for w, t in zip(waypoints, weather_list)
    ]
    route_out = {
        "total_km":      route["total_km"],
        "stages":        stages,
        "route_profile": route["route_profile"],
        "peaks":         route["peaks"],
        "overnights":    route["overnights"],
    }

    now   = datetime.now(VIENNA)
    built = now.strftime("%d %b %Y %H:%M CEST")

    route_json     = json.dumps(route_out,      ensure_ascii=False, separators=(",", ":"))
    waypoints_json = json.dumps(waypoints_out,  ensure_ascii=False, separators=(",", ":"))

    head = (
        _FORECAST_HEAD
        .replace("__BUILT__",         built)
        .replace("__TOTAL_KM__",      f"{route['total_km']:.1f}")
        .replace("__ROUTE_JSON__",    route_json)
        .replace("__WAYPOINTS_JSON__", waypoints_json)
    )

    html = head + _FORECAST_JS + _FORECAST_FOOT

    out = "site/forecast.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    size_kb = os.path.getsize(out) / 1024
    print(f"Saved: {out}  ({size_kb:.0f} KB)")


# ---------------------------------------------------------------------------
# Index page
# ---------------------------------------------------------------------------

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
    route_start_km = data["stages"][0]["start_km"]
    for lat, lon, ele, km, label, temp in data["overnights"]:
        key = round(km, 1)
        if key in seen_km:
            continue
        seen_km.add(key)
        stage = "Route start" if abs(km - route_start_km) < 0.5 else stage_name_for_km(km)
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

    print("\nGenerating forecast page...")
    build_forecast_site()



if __name__ == "__main__":
    main()
