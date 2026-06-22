"""
OBS-ready live score dashboard for one football fixture.

Run:
    python -m livestream.live_score_server --fixture-id 123456

Then add this URL as an OBS Browser Source:
    http://127.0.0.1:8000/live-score/fixture/123456
"""
from __future__ import annotations

import argparse
import html
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from clients.api_football import ApiFootballClient, ApiFootballError
from config import settings

app = FastAPI(title="Football Live Score Dashboard")
_client: ApiFootballClient | None = None


def _api() -> ApiFootballClient:
    global _client
    if _client is None:
        _client = ApiFootballClient()
    return _client


def _asset_file(name: str) -> Path:
    return settings.BASE_DIR / "config" / "images" / name


@app.get("/")
def root():
    return RedirectResponse("/live-score/select")


@app.get("/assets/logo.png")
def logo():
    path = _asset_file("logo.png")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Logo not found")
    return FileResponse(path)


@app.get("/assets/worldcup-bg.png")
def worldcup_background():
    path = _asset_file("worldcup_live_bg.png")
    if not path.exists():
        raise HTTPException(status_code=404, detail="World Cup background not found")
    return FileResponse(path)


@app.get("/api/matches/today")
def matches_today(
    match_date: str = Query(default_factory=lambda: date.today().isoformat(), alias="date"),
    league: int | None = None,
    season: int | None = None,
    timezone: str = "UTC",
):
    try:
        matches = _api().fixtures_for_date(match_date, league, season, timezone)
        if not league:
            filtered = [m for m in matches if "world cup" in (m["league"]["name"] or "").lower()]
            if filtered:
                matches = filtered
        return {"matches": matches, "date": match_date}
    except (ApiFootballError, Exception) as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/match/{fixture_id}/live")
def match_live(fixture_id: int):
    try:
        return _api().live_match(fixture_id)
    except (ApiFootballError, Exception) as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/live-score/select", response_class=HTMLResponse)
def select_page():
    return HTMLResponse(_SELECT_HTML.replace("__BRAND__", html.escape(settings.BRAND_NAME)))


@app.get("/live-score/fixture/{fixture_id}", response_class=HTMLResponse)
def fixture_page(fixture_id: int):
    page = (
        _SCOREBOARD_HTML
        .replace("__FIXTURE_ID__", str(fixture_id))
        .replace("__BRAND__", html.escape(settings.BRAND_NAME))
        .replace("__POLL_MS__", str(max(5, settings.LIVE_SCORE_POLL_SECONDS) * 1000))
    )
    return HTMLResponse(page)


_SELECT_HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>World Cup Live Score Match Select</title>
  <style>
    :root {
      --ink: #f5f2e9;
      --muted: #a9b8b1;
      --field: #101713;
      --line: #253d31;
      --green: #9cff2e;
      --red: #ff2f2f;
      --gold: #f4c542;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Impact, Haettenschweiler, "Arial Narrow Bold", sans-serif;
      color: var(--ink);
      background:
        linear-gradient(180deg, rgba(0, 0, 0, .18), rgba(0, 0, 0, .72)),
        radial-gradient(circle at 50% 0%, rgba(156, 255, 46, .16), transparent 30%),
        #05080a;
    }
    .wrap { max-width: 1120px; margin: 0 auto; padding: 42px 24px; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 24px; margin-bottom: 28px; }
    h1 { margin: 0; font-size: 42px; letter-spacing: 1px; text-transform: uppercase; }
    .brand { color: var(--green); }
    .panel {
      border: 1px solid rgba(255,255,255,.18);
      background: rgba(6, 12, 15, .84);
      padding: 20px;
      border-radius: 20px;
      box-shadow: 0 20px 80px rgba(0,0,0,.42);
    }
    .controls { display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 12px; align-items: end; }
    label { display: grid; gap: 6px; color: var(--muted); font-size: 13px; font-family: "Trebuchet MS", Verdana, sans-serif; text-transform: uppercase; }
    input {
      width: 100%;
      border: 1px solid rgba(255,255,255,.12);
      color: var(--ink);
      background: var(--field);
      padding: 12px 13px;
      border-radius: 10px;
      font-size: 16px;
      font-family: "Trebuchet MS", Verdana, sans-serif;
    }
    button, a.button {
      border: 0;
      border-radius: 10px;
      padding: 13px 16px;
      color: #081008;
      background: var(--green);
      font-weight: 800;
      font-family: "Trebuchet MS", Verdana, sans-serif;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .manual { margin-top: 18px; display: flex; gap: 10px; }
    .manual input { max-width: 260px; }
    .matches { display: grid; gap: 10px; margin-top: 22px; }
    .match {
      display: grid;
      grid-template-columns: 1.2fr 70px 1.2fr 140px;
      gap: 14px;
      align-items: center;
      padding: 14px 16px;
      border: 1px solid rgba(255,255,255,.12);
      background: rgba(10, 18, 21, .76);
      border-radius: 14px;
    }
    .team { font-size: 18px; }
    .score { text-align: center; color: var(--gold); font-size: 22px; }
    .meta { color: var(--muted); font-size: 13px; font-family: "Trebuchet MS", Verdana, sans-serif; }
    .empty { margin-top: 22px; color: var(--muted); font-family: "Trebuchet MS", Verdana, sans-serif; }
    @media (max-width: 760px) {
      .controls, .match { grid-template-columns: 1fr; }
      header { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <main class="wrap">
    <header>
      <h1><span class="brand">__BRAND__</span> World Cup live control</h1>
      <div class="meta">Use the fixture page URL in OBS Browser Source at 1080 x 1920.</div>
    </header>
    <section class="panel">
      <div class="controls">
        <label>Date <input id="date" type="date"></label>
        <label>League ID <input id="league" type="number" placeholder="optional"></label>
        <label>Season <input id="season" type="number" placeholder="optional"></label>
        <button id="load">Load matches</button>
      </div>
      <div class="manual">
        <input id="fixture" type="number" placeholder="fixture_id">
        <button id="open">Open fixture</button>
      </div>
      <div id="matches" class="matches"></div>
      <div id="empty" class="empty"></div>
    </section>
  </main>
  <script>
    const dateInput = document.getElementById('date');
    dateInput.valueAsDate = new Date();
    const matches = document.getElementById('matches');
    const empty = document.getElementById('empty');

    document.getElementById('open').onclick = () => {
      const id = document.getElementById('fixture').value.trim();
      if (id) location.href = `/live-score/fixture/${id}`;
    };

    document.getElementById('load').onclick = loadMatches;

    async function loadMatches() {
      matches.innerHTML = '';
      empty.textContent = 'Loading...';
      const params = new URLSearchParams({ date: dateInput.value });
      const league = document.getElementById('league').value.trim();
      const season = document.getElementById('season').value.trim();
      if (league) params.set('league', league);
      if (season) params.set('season', season);
      try {
        const res = await fetch(`/api/matches/today?${params}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'API error');
        empty.textContent = data.matches.length ? '' : 'No World Cup matches found for these filters.';
        for (const match of data.matches) {
          const home = match.teams.home.name;
          const away = match.teams.away.name;
          const score = `${match.goals.home ?? '-'} : ${match.goals.away ?? '-'}`;
          const row = document.createElement('div');
          row.className = 'match';
          row.innerHTML = `
            <div><div class="team">${home}</div><div class="meta">${match.league.round || match.league.name}</div></div>
            <div class="score">${score}</div>
            <div><div class="team">${away}</div><div class="meta">${match.venue.name || match.status.long || match.date || ''}</div></div>
            <a class="button" href="/live-score/fixture/${match.id}">Open</a>
          `;
          matches.appendChild(row);
        }
      } catch (err) {
        empty.textContent = err.message;
      }
    }
  </script>
</body>
</html>
"""


_SCOREBOARD_HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FIFA World Cup 2026 Live Scoreboard</title>
  <style>
    :root {
      --ink: #ffffff;
      --muted: #d4d8dc;
      --accent: #9cff2e;
      --accent-strong: #7dff1f;
      --accent-soft: rgba(156, 255, 46, .18);
      --gold: #f2ffcf;
      --panel: rgba(5, 10, 8, .78);
      --panel-strong: rgba(4, 8, 6, .92);
      --line: rgba(156, 255, 46, .34);
      --shadow: 0 20px 90px rgba(0, 0, 0, .56);
      --live: #ff2d2d;
      --live-shadow: rgba(255, 45, 45, .28);
    }
    * { box-sizing: border-box; }
    html, body { width: 100%; height: 100%; overflow: hidden; }
    body {
      margin: 0;
      font-family: "Trebuchet MS", Verdana, sans-serif;
      color: var(--ink);
      background: #010406;
      display: flex;
      justify-content: center;
      align-items: flex-start;
    }
    .viewport {
      width: 1080px;
      height: 1920px;
      flex: 0 0 auto;
      transform-origin: top center;
    }
    .stage {
      width: 1080px;
      height: 1920px;
      position: relative;
      padding: 24px 36px 36px;
      overflow: hidden;
      background:
        linear-gradient(180deg, rgba(0,0,0,.06), rgba(0,0,0,.18) 20%, rgba(0,0,0,.52) 55%, rgba(0,0,0,.82) 100%),
        url('/assets/worldcup-bg.png') center top / cover no-repeat;
    }
    .stage::before {
      content: "";
      position: absolute;
      inset: 0;
      background:
        radial-gradient(circle at 50% 14%, rgba(156,255,46,.12), transparent 22%),
        linear-gradient(180deg, rgba(0, 0, 0, .08), rgba(0,24,8,.08) 34%, rgba(0,0,0,.48) 70%, rgba(0,0,0,.82) 100%);
      pointer-events: none;
    }
    .stage > * { position: relative; z-index: 1; }
    .topbar {
      position: relative;
      display: grid;
      grid-template-columns: 190px 1fr 180px;
      align-items: start;
      gap: 8px;
    }
    .brand {
      display: flex;
      align-items: center;
      justify-content: flex-start;
      min-width: 0;
      transform: translate(-35px, -20px);
    }
    .brand img {
      width: 170px;
      height: 170px;
      object-fit: contain;
      flex: 0 0 auto;
      filter: drop-shadow(0 8px 24px rgba(0,0,0,.42));
    }
    .title-wrap {
      position: absolute;
      left: 50%;
      top: 6px;
      transform: translateX(-50%);
      width: 100%;
      max-width: 720px;
      text-align: center;
      pointer-events: none;
    }
    .title {
      margin: 0;
      font-family: "Arial Narrow", "Roboto Condensed", "Trebuchet MS", sans-serif;
      text-transform: uppercase;
      font-size: 72px;
      line-height: .92;
      letter-spacing: 1.6px;
      font-weight: 800;
      white-space: nowrap;
      text-shadow: 0 6px 24px rgba(0,0,0,.45);
      -webkit-font-smoothing: antialiased;
      text-rendering: geometricPrecision;
    }
    .subtitle-row {
      margin-top: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 16px;
    }
    .subtitle-line {
      width: 84px;
      height: 3px;
      border-radius: 999px;
      background: linear-gradient(90deg, transparent, var(--accent));
    }
    .subtitle-line:last-child {
      background: linear-gradient(90deg, var(--accent), transparent);
    }
    .subtitle {
      font-family: Impact, Haettenschweiler, "Arial Narrow Bold", sans-serif;
      text-transform: uppercase;
      color: var(--accent);
      font-size: 28px;
      letter-spacing: 5px;
      white-space: nowrap;
      text-shadow: 0 0 18px rgba(156,255,46,.18);
      -webkit-font-smoothing: antialiased;
      text-rendering: geometricPrecision;
    }
    .status-box {
      position: absolute;
      right: 0;
      top: 6px;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 8px;
      z-index: 2;
    }
    .live-pill {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 12px 18px;
      border-radius: 10px;
      background: var(--live);
      font-family: Impact, Haettenschweiler, "Arial Narrow Bold", sans-serif;
      text-transform: uppercase;
      font-size: 28px;
      letter-spacing: .8px;
      box-shadow: 0 10px 26px var(--live-shadow);
    }
    .live-pill .dot {
      width: 14px;
      height: 14px;
      border-radius: 50%;
      background: white;
      animation: blink 1.2s infinite;
    }
    .clock-now {
      font-family: "Arial Narrow", "Roboto Condensed", "Trebuchet MS", sans-serif;
      font-size: 34px;
      letter-spacing: .6px;
      font-weight: 600;
      text-shadow: 0 4px 12px rgba(0,0,0,.35);
    }
    @keyframes blink { 50% { opacity: .35; } }
    .scoreboard {
      margin-top: 48px;
      display: grid;
      grid-template-columns: minmax(0, 250px) minmax(0, 488px) minmax(0, 250px);
      align-items: start;
      justify-content: space-between;
      gap: 10px;
      transform: translateX(0);
      overflow: hidden;
    }
    .team-block {
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
      text-shadow: 0 4px 18px rgba(0,0,0,.5);
      padding-top: 12px;
      min-width: 0;
    }
    .team-logo-slot {
      width: 210px;
      height: 170px;
      display: flex;
      align-items: flex-end;
      justify-content: center;
      margin: 0 auto 4px;
      overflow: hidden;
    }
    .team-logo {
      width: 100%;
      height: 100%;
      display: block;
      object-fit: contain;
      object-position: center bottom;
      filter: drop-shadow(0 14px 30px rgba(0,0,0,.45));
    }
    .team-name {
      margin-top: 0;
      font-family: "Arial Narrow", "Roboto Condensed", "Trebuchet MS", sans-serif;
      font-size: 72px;
      line-height: 1;
      text-transform: uppercase;
      letter-spacing: 1.2px;
      font-weight: 800;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: clip;
      width: 100%;
      padding: 0 6px;
    }
    .center-score {
      text-align: center;
      padding-top: 18px;
      min-width: 0;
      width: 100%;
      overflow: hidden;
    }
    .scoreline {
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 26px;
      font-family: Impact, Haettenschweiler, "Arial Narrow Bold", sans-serif;
      font-size: 208px;
      line-height: .9;
      text-shadow: 0 10px 28px rgba(0,0,0,.55), 0 0 20px rgba(255,255,255,.08);
      transform: translateY(26px);
    }
    .score-sep { transform: translateY(-8px); }
    .meta-line {
      margin-top: 24px;
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 12px;
      flex-wrap: nowrap;
      font-family: "Arial Narrow", "Roboto Condensed", "Trebuchet MS", sans-serif;
      font-size: 22px;
      line-height: 1;
      font-weight: 600;
      text-shadow: none;
      white-space: nowrap;
      overflow: hidden;
      width: 100%;
    }
    .minute-live { color: var(--accent); }
    .minute-live.is-finished {
      color: #f7fff2;
      font-weight: 700;
      background: rgba(8, 22, 8, .76);
      border: 1px solid rgba(156,255,46,.45);
      border-radius: 999px;
      padding: 4px 10px;
      text-shadow: 0 1px 12px rgba(0,0,0,.6);
    }
    .meta-line .pipe { color: rgba(255,255,255,.7); }
    .status-chip {
      display: inline-flex;
      margin-top: 18px;
      padding: 12px 34px;
      border-radius: 999px;
      border: 2px solid var(--accent);
      background: rgba(7, 14, 8, .94);
      color: var(--accent-strong);
      font-family: Impact, Haettenschweiler, "Arial Narrow Bold", sans-serif;
      font-size: 34px;
      line-height: 1;
      box-shadow: inset 0 0 0 1px rgba(156,255,46,.18), 0 10px 24px rgba(0,0,0,.36), 0 0 20px rgba(156,255,46,.08);
    }
    .status-chip.is-finished {
      border-color: rgba(156,255,46,.58);
      background: rgba(8, 18, 8, .98);
      color: #efffe1;
      box-shadow: inset 0 0 0 1px rgba(156,255,46,.24), 0 10px 24px rgba(0,0,0,.5);
    }
    .card {
      margin-top: 16px;
      border-radius: 22px;
      border: 2px solid rgba(255,255,255,.36);
      background: var(--panel);
      box-shadow: var(--shadow);
      backdrop-filter: blur(6px);
    }
    .goal-card {
      width: 960px;
      min-height: 248px;
      margin: 14px auto 0;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,.08), 0 0 0 1px rgba(156,255,46,.16), var(--shadow);
      padding-top: 8px;
    }
    .events-card {
      width: 960px;
      height: 340px;
      margin: 14px auto 0;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,.08), 0 0 0 1px rgba(156,255,46,.16), var(--shadow);
    }
    .stats-card {
      width: 960px;
      height: 244px;
      margin: 14px auto 0;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,.08), 0 0 0 1px rgba(156,255,46,.16), var(--shadow);
    }
    .table-card {
      width: 960px;
      min-height: 188px;
      margin: 14px auto 0;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,.08), 0 0 0 1px rgba(156,255,46,.16), var(--shadow);
    }
    .card-head {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 14px 24px 6px;
    }
    .card-icon {
      color: var(--accent);
      font-size: 24px;
      line-height: 1;
    }
    .card-title {
      font-family: "Arial Narrow", "Roboto Condensed", "Trebuchet MS", sans-serif;
      font-size: 26px;
      line-height: 1;
      text-transform: uppercase;
      letter-spacing: 1.2px;
      font-weight: 700;
      text-shadow: none;
      -webkit-font-smoothing: antialiased;
      text-rendering: geometricPrecision;
    }
    .card-line {
      flex: 0 0 220px;
      height: 3px;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--accent), transparent);
      opacity: .9;
      margin-top: 4px;
    }
    .scorers-body {
      padding: 4px 24px 28px;
      display: grid;
      grid-template-columns: 1fr 1px 1fr;
      gap: 20px;
      align-items: start;
    }
    .scorers-divider {
      align-self: stretch;
      background: linear-gradient(180deg, transparent, rgba(255,255,255,.26), transparent);
      width: 1px;
    }
    .scorer-side {
      display: grid;
      gap: 10px;
      transform: translate(0, 6px);
      min-width: 0;
    }
    .scorer-team {
      display: flex;
      align-items: center;
      gap: 12px;
      font-family: "Arial Narrow", "Roboto Condensed", "Trebuchet MS", sans-serif;
      font-size: 22px;
      line-height: 1;
      text-transform: uppercase;
      font-weight: 700;
      letter-spacing: .6px;
      text-shadow: none;
      -webkit-font-smoothing: antialiased;
      text-rendering: geometricPrecision;
      padding-left: 12px;
    }
    .scorer-team img {
      width: 38px;
      height: 38px;
      object-fit: contain;
    }
    .scorer-list {
      display: grid;
      gap: 8px;
      padding-left: 8px;
      font-size: 22px;
      text-shadow: none;
      -webkit-font-smoothing: antialiased;
      text-rendering: geometricPrecision;
      min-width: 0;
    }
    .scorer-list.two-col {
      grid-template-columns: minmax(0, 1fr) minmax(0, .9fr);
      column-gap: 12px;
      align-items: start;
      max-width: 100%;
    }
    .scorer-col {
      display: grid;
      gap: 8px;
      align-content: start;
      min-width: 0;
    }
    .scorer-row {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
      white-space: nowrap;
      overflow: hidden;
    }
    .scorer-row span:nth-child(2) {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .ball { color: var(--accent); }
    .minute { color: var(--accent); font-weight: 800; }
    .empty-line { color: var(--muted); }
    .events-body {
      height: 280px;
      padding: 4px 24px 8px 42px;
      display: grid;
      gap: 0;
      align-content: start;
      overflow: hidden;
    }
    .event-row {
      display: grid;
      grid-template-columns: 52px 88px 1fr;
      gap: 12px;
      align-items: center;
      padding: 8px 0;
      border-top: 1px solid rgba(255,255,255,.18);
      font-size: 22px;
    }
    .event-row:first-child { border-top: 0; }
    .event-icon { font-size: 22px; text-align: center; }
    .event-row.compact {
      font-size: 22px;
    }
    .event-row.spacious {
      font-size: 24px;
    }
    .event-minute { color: var(--accent); font-weight: 700; font-family: "Arial Narrow", "Roboto Condensed", "Trebuchet MS", sans-serif; font-size: 23px; }
    .event-row.compact .event-minute { font-size: 23px; }
    .event-row.spacious .event-minute { font-size: 25px; }
    .event-text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .stats-body {
      height: 176px;
      padding: 6px 26px 10px;
      display: grid;
      gap: 8px;
      align-content: start;
      overflow: hidden;
    }
    .stat-row {
      display: grid;
      grid-template-columns: 72px 1fr 190px 1fr 72px;
      align-items: center;
      gap: 12px;
      font-size: 20px;
    }
    .stat-value {
      font-family: "Arial Narrow", "Roboto Condensed", "Trebuchet MS", sans-serif;
      font-size: 26px;
      line-height: 1;
      color: var(--accent);
      text-align: center;
      font-weight: 600;
      text-shadow: none;
      -webkit-font-smoothing: antialiased;
      text-rendering: geometricPrecision;
    }
    .stat-value.away { color: #ffffff; }
    .stat-label {
      text-align: center;
      color: #ffffff;
      font-size: 22px;
      font-family: "Arial Narrow", "Roboto Condensed", "Trebuchet MS", sans-serif;
      font-weight: 600;
      text-shadow: none;
      -webkit-font-smoothing: antialiased;
      text-rendering: geometricPrecision;
    }
    .bar {
      height: 14px;
      background: rgba(255,255,255,.18);
      border-radius: 999px;
      overflow: hidden;
    }
    .bar-fill {
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--accent), var(--accent-strong));
    }
    .bar-fill.away {
      margin-left: auto;
      background: rgba(255,255,255,.88);
    }
    .standings-body {
      padding: 0 24px 8px;
    }
    .standings-header, .standing-row {
      display: grid;
      grid-template-columns: 64px 1fr 68px 68px;
      gap: 12px;
      align-items: center;
    }
    .standings-header {
      color: var(--accent);
      font-family: "Arial Narrow", "Roboto Condensed", "Trebuchet MS", sans-serif;
      font-size: 24px;
      text-transform: uppercase;
      padding: 0 0 4px;
      font-weight: 700;
      letter-spacing: .8px;
      text-shadow: none;
      -webkit-font-smoothing: antialiased;
      text-rendering: geometricPrecision;
    }
    .standings-header > div:first-child {
      transform: translateX(28px);
    }
    .standing-row {
      padding: 6px 0;
      border-top: 1px solid rgba(255,255,255,.16);
      font-size: 22px;
    }
    .standing-row:first-of-type { border-top: 0; }
    .rank-box {
      width: 44px;
      height: 44px;
      border: 2px solid rgba(156,255,46,.82);
      border-radius: 8px;
      display: grid;
      place-items: center;
      color: var(--accent);
      font-family: Impact, Haettenschweiler, "Arial Narrow Bold", sans-serif;
      font-size: 24px;
      transform: translateX(18px);
    }
    .standing-team {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }
    .standing-team img {
      width: 38px;
      height: 38px;
      object-fit: contain;
      flex: 0 0 auto;
    }
    .standing-name {
      min-width: 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      font-family: "Arial Narrow", "Roboto Condensed", "Trebuchet MS", sans-serif;
      font-size: 22px;
      text-transform: uppercase;
      font-weight: 600;
      text-shadow: none;
      -webkit-font-smoothing: antialiased;
      text-rendering: geometricPrecision;
    }
    .standing-gd, .standing-pts {
      text-align: center;
      font-family: "Arial Narrow", "Roboto Condensed", "Trebuchet MS", sans-serif;
      font-size: 25px;
      justify-self: center;
      width: 100%;
      transform: translateX(-12px);
      font-weight: 600;
      text-shadow: none;
      -webkit-font-smoothing: antialiased;
      text-rendering: geometricPrecision;
    }
    .standing-pts { color: var(--accent); }
    .knockout-box {
      padding: 18px 26px 26px;
      text-align: center;
      font-family: Impact, Haettenschweiler, "Arial Narrow Bold", sans-serif;
      font-size: 34px;
      line-height: 1.1;
      color: var(--accent);
      text-transform: uppercase;
    }
    .ticker {
      width: calc(100% + 72px);
      margin: 14px 0 0 -36px;
      height: 86px;
      display: flex;
      align-items: center;
      overflow: hidden;
      border: 2px solid rgba(156,255,46,.82);
      border-radius: 16px;
      background: rgba(4, 10, 4, .88);
      box-shadow: 0 0 28px rgba(156,255,46,.18), inset 0 0 0 2px rgba(156,255,46,.12);
    }
    .ticker-track {
      white-space: nowrap;
      font-family: "Arial Narrow", "Roboto Condensed", "Trebuchet MS", sans-serif;
      font-size: 24px;
      line-height: 1;
      padding-left: 100%;
      animation: ticker 34s linear infinite;
      font-weight: 600;
      letter-spacing: .4px;
    }
    .ticker-accent { color: var(--accent); }
    .subline {
      margin-top: 8px;
      text-align: center;
      color: var(--accent);
      font-family: Impact, Haettenschweiler, "Arial Narrow Bold", sans-serif;
      font-size: 22px;
      text-transform: none;
      pointer-events: none;
    }
    .hidden { display: none !important; }
    @keyframes ticker { to { transform: translateX(-100%); } }
  </style>
</head>
<body>
  <div id="viewport" class="viewport">
    <main class="stage">
      <header class="topbar">
        <div class="brand">
          <img src="/assets/logo.png" alt="Channel logo" onerror="this.style.display='none'">
        </div>
        <div class="title-wrap">
          <h1 class="title">FIFA WORLD CUP 2026</h1>
          <div class="subtitle-row">
            <div class="subtitle-line"></div>
            <div class="subtitle">LIVE SCOREBOARD</div>
            <div class="subtitle-line"></div>
          </div>
        </div>
        <div class="status-box">
          <div class="live-pill"><span class="dot"></span><span id="liveLabel">LIVE</span></div>
          <div id="streamClock" class="clock-now">08:45 PM</div>
        </div>
      </header>

      <section class="scoreboard">
        <div class="team-block home">
          <div class="team-logo-slot">
            <img id="homeLogo" class="team-logo" alt="">
          </div>
          <div id="homeName" class="team-name">HOME</div>
        </div>
        <div class="center-score">
          <div class="scoreline">
            <span id="homeGoals">-</span><span class="score-sep">-</span><span id="awayGoals">-</span>
          </div>
          <div class="meta-line">
            <span id="minuteLive" class="minute-live">67' LIVE</span>
            <span class="pipe">|</span>
            <span id="roundLine">Group D</span>
            <span class="pipe">|</span>
            <span id="venueLine">MetLife Stadium, New York</span>
          </div>
          <div id="phaseChip" class="status-chip">2nd Half</div>
        </div>
        <div class="team-block away">
          <div class="team-logo-slot">
            <img id="awayLogo" class="team-logo" alt="">
          </div>
          <div id="awayName" class="team-name">AWAY</div>
        </div>
      </section>

      <section class="card goal-card">
        <div class="card-head">
          <div class="card-icon">⚽</div>
          <div class="card-title">Goal Scorers</div>
          <div class="card-line"></div>
        </div>
        <div class="scorers-body">
          <div class="scorer-side">
            <div class="scorer-team"><img id="homeScorerLogo" alt=""><span id="homeScorerTeam">Home</span></div>
            <div id="homeScorers" class="scorer-list"></div>
          </div>
          <div class="scorers-divider"></div>
          <div class="scorer-side">
            <div class="scorer-team"><img id="awayScorerLogo" alt=""><span id="awayScorerTeam">Away</span></div>
            <div id="awayScorers" class="scorer-list"></div>
          </div>
        </div>
      </section>

      <div style="display:none">
      <section class="card">
        <div class="card-head">
          <div class="card-icon">🕒</div>
          <div class="card-title">Live Events</div>
          <div class="card-line"></div>
        </div>
        <div id="events" class="events-body"></div>
      </section>

      <section class="card">
        <div class="card-head">
          <div class="card-icon">📊</div>
          <div class="card-title">Match Stats</div>
          <div class="card-line"></div>
        </div>
        <div id="stats" class="stats-body"></div>
      </section>

      <section class="card">
        <div class="card-head">
          <div class="card-icon">🏆</div>
          <div id="tableTitle" class="card-title">Group Table</div>
          <div class="card-line"></div>
        </div>
        <div id="standingsWrap" class="standings-body"></div>
        <div id="knockoutWrap" class="knockout-box hidden"></div>
      </section>

      <div class="ticker">
        <div id="ticker" class="ticker-track">FIFA WORLD CUP 2026 LIVE UPDATES</div>
      </div>
      <div class="subline">Subscribe for World Cup live scores and analysis</div>
      </div>
    </main>
  </div>
  <script>
    const fixtureId = __FIXTURE_ID__;
    const pollMs = __POLL_MS__;
    let lastGood = null;

    function fitViewport() {
      const viewport = document.getElementById('viewport');
      const scale = Math.min(window.innerWidth / 1080, window.innerHeight / 1920, 1);
      viewport.style.transform = `scale(${scale})`;
      viewport.style.width = `${1080 * scale}px`;
      viewport.style.height = `${1920 * scale}px`;
    }

    function setupVisiblePanels() {
      const wrapper = document.querySelector('.stage > div[style="display:none"]');
      if (!wrapper || wrapper.dataset.ready === '1') return;
      wrapper.style.display = 'block';
      const sections = wrapper.querySelectorAll(':scope > section.card');
      sections.forEach((section, index) => {
        if (index === 0) {
          section.classList.add('events-card');
          section.style.display = '';
        } else if (index === 1) {
          section.classList.add('stats-card');
          section.style.display = '';
        } else if (index === 2) {
          section.classList.add('table-card');
          section.style.display = '';
        } else {
          section.style.display = 'none';
        }
      });
      const ticker = wrapper.querySelector('.ticker');
      if (ticker) ticker.style.display = '';
      const subline = wrapper.querySelector('.subline');
      if (subline) subline.style.display = 'none';
      wrapper.dataset.ready = '1';
    }

    function setText(id, value) {
      const el = document.getElementById(id);
      if (el) el.textContent = value ?? '';
    }

    function fitTeamNames() {
      const ids = ['homeName', 'awayName'];
      const minSize = ids.reduce((lowest, id) => {
        const el = document.getElementById(id);
        if (!el) return lowest;
        let size = 72;
        el.style.fontSize = `${size}px`;
        while (el.scrollWidth > el.clientWidth && size > 28) {
          size -= 2;
          el.style.fontSize = `${size}px`;
        }
        return Math.min(lowest, size);
      }, 72);

      ids.forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.style.fontSize = `${minSize}px`;
      });
    }

    function fitHeaderTitle() {
      const topbar = document.querySelector('.topbar');
      const brand = document.querySelector('.brand');
      const statusBox = document.querySelector('.status-box');
      const titleWrap = document.querySelector('.title-wrap');
      const title = document.querySelector('.title');
      if (!topbar || !brand || !statusBox || !titleWrap || !title) return;

      const available = Math.max(420, topbar.clientWidth - brand.offsetWidth - statusBox.offsetWidth - 40);
      titleWrap.style.maxWidth = `${available}px`;

      let size = 72;
      title.style.fontSize = `${size}px`;
      while (title.scrollWidth > titleWrap.clientWidth && size > 42) {
        size -= 2;
        title.style.fontSize = `${size}px`;
      }
    }

    function fitMetaLine() {
      const el = document.querySelector('.meta-line');
      if (!el) return;
      let size = 24;
      el.style.fontSize = `${size}px`;
      while (el.scrollWidth > el.clientWidth && size > 12) {
        size -= 1;
        el.style.fontSize = `${size}px`;
      }
    }

    function setLogo(id, value) {
      const el = document.getElementById(id);
      if (!el) return;
      el.src = value || '';
      el.style.display = value ? '' : 'none';
    }

    function escapeHtml(value) {
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function minuteText(event) {
      if (!event || event.elapsed == null) return '';
      return event.extra ? `${event.elapsed}+${event.extra}'` : `${event.elapsed}'`;
    }

    function currentClock() {
      const now = new Date();
      const hh = now.getHours() % 12 || 12;
      const mm = String(now.getMinutes()).padStart(2, '0');
      const ampm = now.getHours() >= 12 ? 'PM' : 'AM';
      return `${hh}:${mm} ${ampm}`;
    }

    function phaseText(status) {
      const short = (status?.short || '').toUpperCase();
      if (short === 'NS') return 'Upcoming';
      if (short === '1H') return '1st Half';
      if (short === 'HT') return 'Half-Time';
      if (short === '2H') return '2nd Half';
      if (short === 'ET') return 'Extra Time';
      if (short === 'BT') return 'Break';
      if (short === 'P') return 'Penalties';
      if (short === 'AET' || short === 'PEN' || short === 'FT') return 'Full-Time';
      if (status?.long) return status.long;
      return 'Live';
    }

    function topBadgeText(status) {
      const short = (status?.short || '').toUpperCase();
      if (short === 'NS') return 'UPCOMING';
      if (short === 'HT') return 'HALF TIME';
      return 'LIVE';
    }

    function isFinishedStatus(status) {
      const short = (status?.short || '').toUpperCase();
      return short === 'FT' || short === 'AET' || short === 'PEN';
    }

    function minuteStatusLine(status, stale) {
      if (stale) return 'UPDATING...';
      const short = (status?.short || '').toUpperCase();
      if (short === 'NS') return 'KICKOFF SOON';
      if (short === 'HT') return 'HALF-TIME';
      if (short === 'FT' || short === 'AET' || short === 'PEN') return 'FULL-TIME';
      if (status?.elapsed != null) return `${status.elapsed}' LIVE`;
      return 'LIVE';
    }

    function roundLabel(value) {
      if (!value) return 'World Cup';
      return value.replace(/^Regular Season$/i, 'Group Stage');
    }

    function statValue(raw) {
      if (raw === null || raw === undefined || raw === '') return null;
      return String(raw).trim();
    }

    function statNumber(raw) {
      if (raw === null || raw === undefined || raw === '') return null;
      const numeric = parseFloat(String(raw).replace('%', '').trim());
      return Number.isFinite(numeric) ? numeric : null;
    }

    function renderScorerList(items) {
      if (!items || !items.length) return '<div class="empty-line">No scorers yet</div>';
      return items.map(item => `
        <div class="scorer-row">
          <span class="ball">⚽</span>
          <span>${escapeHtml(item.player)}</span>
          <span class="minute">${escapeHtml(item.minute)}</span>
        </div>
      `).join('');
    }

    function renderScorerListGrid(items) {
      if (!items || !items.length) return '<div class="empty-line">No scorers yet</div>';
      const rows = items.map(item => `
        <div class="scorer-row">
          <span class="ball">⚽</span>
          <span>${escapeHtml(item.player)}</span>
          <span class="minute">${escapeHtml(item.minute)}</span>
        </div>
      `);
      if (items.length <= 2) return rows.join('');
      return `
        <div class="scorer-list two-col">
          <div class="scorer-col">${rows.slice(0, 2).join('')}</div>
          <div class="scorer-col">${rows.slice(2, 4).join('')}</div>
        </div>
      `;
    }

    function eventMeta(event) {
      const detail = (event.detail || '').toLowerCase();
      const type = (event.type || '').toLowerCase();
      if (detail.includes('yellow')) return { icon: '🟨', label: 'Yellow Card' };
      if (detail.includes('red')) return { icon: '🟥', label: 'Red Card' };
      if (detail.includes('substitution') || type.includes('subst')) return { icon: '🔁', label: 'Substitution' };
      if (detail.includes('var')) return { icon: '📺', label: 'VAR' };
      if (detail.includes('penalty') && !type.includes('goal')) return { icon: '🎯', label: 'Penalty' };
      if (type === 'goal') return { icon: '⚽', label: event.detail || 'Goal' };
      return { icon: '•', label: event.detail || event.type || 'Event' };
    }

    function renderEvents(events) {
      const rows = (events || []).slice(-6).reverse();
      const rowClass = rows.length <= 2 ? 'event-row spacious' : rows.length >= 5 ? 'event-row compact' : 'event-row';
      if (!rows.length) return '<div class="event-row spacious"><div class="event-icon">•</div><div class="event-minute">--</div><div class="event-text">No major events yet</div></div>';
      return rows.map(event => {
        const meta = eventMeta(event);
        const who = [event.player, event.team].filter(Boolean).join(' - ');
        const text = [meta.label, who].filter(Boolean).join(' - ');
        return `
          <div class="${rowClass}">
            <div class="event-icon">${meta.icon}</div>
            <div class="event-minute">${escapeHtml(minuteText(event) || '--')}</div>
            <div class="event-text">${escapeHtml(text)}</div>
          </div>
        `;
      }).join('');
    }

    function renderStats(homeStats, awayStats) {
      const statRows = [
        ['Possession', homeStats.possession, awayStats.possession, true],
        ['Shots', homeStats.shots, awayStats.shots, false],
        ['Shots on Target', homeStats.shots_on_goal, awayStats.shots_on_goal, false],
        ['Corners', homeStats.corners, awayStats.corners, false],
        ['Fouls', homeStats.fouls, awayStats.fouls, false],
        ['Yellow Cards', homeStats.yellow_cards, awayStats.yellow_cards, false],
        ['Red Cards', homeStats.red_cards, awayStats.red_cards, false],
      ];
      const available = statRows
        .filter(row => statValue(row[1]) !== null || statValue(row[2]) !== null)
        .slice(0, 5);
      if (!available.length) return '<div class="event-row"><div class="event-icon">•</div><div class="event-minute">--</div><div class="event-text">Stats unavailable</div></div>';
      return available.map(row => {
        const homeValue = statValue(row[1]) ?? '-';
        const awayValue = statValue(row[2]) ?? '-';
        const homeNum = statNumber(row[1]);
        const awayNum = statNumber(row[2]);
        const total = (homeNum ?? 0) + (awayNum ?? 0);
        const homeWidth = total > 0 ? `${Math.max(8, Math.round((homeNum ?? 0) / total * 100))}%` : '0%';
        const awayWidth = total > 0 ? `${Math.max(8, Math.round((awayNum ?? 0) / total * 100))}%` : '0%';
        return `
          <div class="stat-row">
            <div class="stat-value">${escapeHtml(homeValue)}</div>
            <div class="bar"><div class="bar-fill" style="width:${homeNum === null ? '0%' : homeWidth}"></div></div>
            <div class="stat-label">${escapeHtml(row[0])}</div>
            <div class="bar"><div class="bar-fill away" style="width:${awayNum === null ? '0%' : awayWidth}"></div></div>
            <div class="stat-value away">${escapeHtml(awayValue)}</div>
          </div>
        `;
      }).join('');
    }

    function renderStandings(standings, knockoutMessage, standingsError) {
      const standingsWrap = document.getElementById('standingsWrap');
      const knockoutWrap = document.getElementById('knockoutWrap');
      if (standings && standings.rows && standings.rows.length) {
        knockoutWrap.classList.add('hidden');
        standingsWrap.classList.remove('hidden');
        const groupText = String(standings.group || '').trim();
        const groupMatch = String(groupText || standings.title || '').match(/group\s+([a-z0-9]+)/i);
        const tableTitle = groupMatch
          ? `Group ${groupMatch[1].toUpperCase()} Table`
          : (groupText || standings.title || 'Group Table');
        setText('tableTitle', tableTitle);
        standingsWrap.innerHTML = `
          <div class="standings-header">
            <div>#</div>
            <div>Team</div>
            <div>GD</div>
            <div>PTS</div>
          </div>
          ${standings.rows.slice(0, 4).map(row => `
            <div class="standing-row">
              <div class="rank-box">${escapeHtml(row.rank ?? '')}</div>
              <div class="standing-team">
                <img src="${escapeHtml(row.team_logo || '')}" alt="">
                <div class="standing-name">${escapeHtml(row.team_name || '')}</div>
              </div>
              <div class="standing-gd">${escapeHtml(row.goals_diff ?? '-')}</div>
              <div class="standing-pts">${escapeHtml(row.points ?? '-')}</div>
            </div>
          `).join('')}
        `;
        return;
      }
      standingsWrap.classList.add('hidden');
      knockoutWrap.classList.remove('hidden');
      setText('tableTitle', knockoutMessage ? 'Knockout Stage' : 'World Cup Status');
      knockoutWrap.textContent = knockoutMessage || standingsError || 'Standings unavailable for this match.';
    }

    function tickerText(data) {
      const fixture = data.fixture;
      const score = `${fixture.teams.home.name} ${fixture.goals.home ?? '-'}-${fixture.goals.away ?? '-'} ${fixture.teams.away.name}`;
      const homeScorers = (data.goal_scorers?.home || []).map(item => `${item.player} ${item.minute}`).join(', ');
      const awayScorers = (data.goal_scorers?.away || []).map(item => `${item.player} ${item.minute}`).join(', ');
      const scorerBits = [];
      if (homeScorers) scorerBits.push(`${fixture.teams.home.name}: ${homeScorers}`);
      if (awayScorers) scorerBits.push(`${fixture.teams.away.name}: ${awayScorers}`);
      const scorerLine = scorerBits.length ? ` • Goal: ${scorerBits.join(' | ')}` : '';
      return `• FIFA WORLD CUP 2026 LIVE UPDATES • ${score} • ${minuteStatusLine(fixture.status, false)} • ${roundLabel(fixture.league.round)}${scorerLine} • Subscribe for World Cup live scores and analysis`;
    }

    function render(data, stale = false) {
      const fixture = data.fixture;
      const home = fixture.teams.home;
      const away = fixture.teams.away;
      const round = roundLabel(fixture.league.round);
      const topGroup = String(data.standings?.group || '').trim() || round;
      const venue = [fixture.venue.name, fixture.venue.city].filter(Boolean).join(', ');

      setLogo('homeLogo', home.logo);
      setLogo('awayLogo', away.logo);
      setLogo('homeScorerLogo', home.logo);
      setLogo('awayScorerLogo', away.logo);
      setText('homeName', home.name || 'HOME');
      setText('awayName', away.name || 'AWAY');
      fitTeamNames();
      setText('homeScorerTeam', home.name || 'HOME');
      setText('awayScorerTeam', away.name || 'AWAY');
      setText('homeGoals', fixture.goals.home ?? '-');
      setText('awayGoals', fixture.goals.away ?? '-');
      setText('minuteLive', minuteStatusLine(fixture.status, stale));
      setText('roundLine', topGroup);
      setText('venueLine', venue || 'Venue TBC');
      fitMetaLine();
      fitHeaderTitle();
      setText('phaseChip', phaseText(fixture.status));
      setText('liveLabel', topBadgeText(fixture.status));
      document.getElementById('phaseChip').classList.toggle('is-finished', isFinishedStatus(fixture.status));
      document.getElementById('minuteLive').classList.toggle('is-finished', isFinishedStatus(fixture.status));

      document.getElementById('homeScorers').innerHTML = renderScorerListGrid(data.goal_scorers?.home || []);
      document.getElementById('awayScorers').innerHTML = renderScorerListGrid(data.goal_scorers?.away || []);
      document.getElementById('events').innerHTML = renderEvents(data.events || []);

      const homeStats = data.statistics?.[home.name] || {};
      const awayStats = data.statistics?.[away.name] || {};
      document.getElementById('stats').innerHTML = renderStats(homeStats, awayStats);
      renderStandings(data.standings, data.knockout_message || '', data.standings_error || '');
      setText('ticker', tickerText(data));
    }

    function tickClock() {
      setText('streamClock', currentClock());
    }

    async function refresh() {
      try {
        setupVisiblePanels();
        const res = await fetch(`/api/match/${fixtureId}/live`, { cache: 'no-store' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'API error');
        lastGood = data;
        render(data, false);
      } catch (err) {
        if (lastGood) render(lastGood, true);
        else {
          setText('minuteLive', 'API ERROR');
          setText('phaseChip', 'Waiting');
        }
      }
    }

    tickClock();
    setupVisiblePanels();
    refresh();
    fitViewport();
    fitHeaderTitle();
    setInterval(refresh, pollMs);
    setInterval(tickClock, 1000);
    window.addEventListener('resize', fitViewport);
    window.addEventListener('resize', fitHeaderTitle);
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OBS live score dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--fixture-id", type=int, help="Print the OBS URL for this fixture")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/live-score/select"
    if args.fixture_id:
        url = f"http://{args.host}:{args.port}/live-score/fixture/{args.fixture_id}"
    print(f"Live score dashboard: {url}")
    print("OBS Browser Source size: 1080 x 1920")

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
