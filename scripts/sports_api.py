"""
sports_api.py — NBA game state from ESPN's public scoreboard API.

No API key, no auth, no third-party SDK. The squares oracle uses this to
push per-quarter scores onto the Squares contract once each quarter is
final on-chain.

Why ESPN and not balldontlie.io:
- balldontlie's v1 endpoints require an API key (free tier with rate
  limits, but adds a setup step the rest of the codebase doesn't need).
- ESPN's `site.api.espn.com` scoreboard endpoints are open and ship
  per-period linescores out of the box. That's the exact shape the
  squares contract wants for reportQuarter(quarter, homeScore, awayScore).

Convention for tying an on-chain Squares grid to an ESPN game:
  createGame(name="ESPN:401871337") — the oracle parses the prefix and
  treats the suffix as the ESPN event id.

Public surface:
    find_game(date_yyyymmdd, abbr_a, abbr_b) -> event_id | None
    fetch_game(event_id) -> Game | None       # snapshot of state + linescores
    parse_espn_id(name) -> event_id | None    # decode the createGame.name tag

Game.linescores comes back as a list of *finished* quarter dicts:
    [{'home': 29, 'away': 27, 'final': True}, ...]
…so callers can just enumerate and submit any quarter whose `final` flag
is True and whose corresponding `quarterReported[q]` is False on chain.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
USER_AGENT = "TezLiteApps-sports-oracle/1.0"


@dataclass
class TeamLine:
    abbr: str           # 'CLE', 'DET', etc.
    name: str           # 'Cleveland Cavaliers'
    score: int          # current/final total
    quarters: list[int] # ESPN linescores[].value, in order (Q1, Q2, Q3, Q4, [OT…])


@dataclass
class Game:
    event_id: str
    short_name: str         # 'CLE @ DET'
    state: str              # 'pre' | 'in' | 'post'
    completed: bool         # game over (any state, includes ties broken)
    period: int             # current period (1..4 regulation, 5+ OT)
    home: TeamLine
    away: TeamLine

    def quarter_finals(self) -> list[dict]:
        """Return one dict per quarter whose result is final on the scoreboard.

        A quarter is final when the current period has advanced past it
        OR the whole game is post. Overtime periods are included after Q4
        — they don't map onto Squares' 4-quarter contract directly, but
        we expose them so callers can decide what to do (the existing
        contract gate is `quarter < 4`)."""
        out = []
        max_q = max(len(self.home.quarters), len(self.away.quarters))
        for q in range(max_q):
            is_final = self.completed or (self.period > q + 1)
            if not is_final:
                continue
            home_q = self.home.quarters[q] if q < len(self.home.quarters) else 0
            away_q = self.away.quarters[q] if q < len(self.away.quarters) else 0
            out.append({"q": q, "home": home_q, "away": away_q, "final": True})
        return out


def _http_get(url: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _build_team_line(competitor: dict) -> TeamLine:
    team = competitor.get("team", {}) or {}
    # ESPN's scoreboard endpoint serves linescores as {value: 29}, while
    # the summary endpoint serves them as {displayValue: "29"}. Accept
    # either shape so the same parser works for both.
    quarters: list[int] = []
    for ls in (competitor.get("linescores") or []):
        raw = ls.get("value")
        if raw is None:
            raw = ls.get("displayValue", 0)
        try:
            quarters.append(int(raw))
        except (TypeError, ValueError):
            quarters.append(0)
    return TeamLine(
        abbr=team.get("abbreviation", "?"),
        name=team.get("displayName", team.get("name", "?")),
        score=int(competitor.get("score", 0) or 0),
        quarters=quarters,
    )


def _parse_event(event: dict) -> Game | None:
    """Convert one ESPN scoreboard event into a Game. Returns None if the
    event is malformed (no competitions or fewer than 2 competitors)."""
    comps = event.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    competitors = comp.get("competitors") or []
    if len(competitors) < 2:
        return None

    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

    status = event.get("status") or {}
    stype = status.get("type") or {}
    return Game(
        event_id=str(event.get("id", "")),
        short_name=event.get("shortName", event.get("name", "?")),
        state=stype.get("state", "pre"),
        completed=bool(stype.get("completed", False)),
        period=int(status.get("period", 0) or 0),
        home=_build_team_line(home),
        away=_build_team_line(away),
    )


def fetch_scoreboard(date_yyyymmdd: str) -> list[Game]:
    """Pull every NBA event on `date_yyyymmdd` (e.g. '20260513')."""
    url = f"{ESPN_BASE}/scoreboard?{urllib.parse.urlencode({'dates': date_yyyymmdd})}"
    payload = _http_get(url)
    out: list[Game] = []
    for ev in payload.get("events") or []:
        g = _parse_event(ev)
        if g:
            out.append(g)
    return out


def find_game(date_yyyymmdd: str, abbr_a: str, abbr_b: str) -> str | None:
    """Return the ESPN event id for the game between abbr_a and abbr_b on
    `date_yyyymmdd`, or None if there's no such matchup on the slate."""
    target = {abbr_a.upper(), abbr_b.upper()}
    for g in fetch_scoreboard(date_yyyymmdd):
        if {g.home.abbr.upper(), g.away.abbr.upper()} == target:
            return g.event_id
    return None


def fetch_game(event_id: str) -> Game | None:
    """Pull a single game by ESPN event id. Uses the summary endpoint —
    which carries the same competitors + linescores shape as scoreboard
    but lets us look up a known game without scanning a date's slate."""
    url = f"{ESPN_BASE}/summary?{urllib.parse.urlencode({'event': event_id})}"
    try:
        payload = _http_get(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    # The summary endpoint nests the event one level deeper than
    # scoreboard. Stitch it back into the same shape so _parse_event
    # can handle both.
    header = payload.get("header") or {}
    competitions = header.get("competitions") or []
    if not competitions:
        return None
    status = competitions[0].get("status") or header.get("status") or {}
    # Summary doesn't always surface `status.period`; infer it from
    # finished linescores if the explicit field is missing.
    if not status.get("period"):
        max_q = max(
            len(c.get("linescores") or []) for c in competitions[0].get("competitors", [{}])
        )
        if max_q:
            status = {**status, "period": max_q}
    return _parse_event({
        "id": header.get("id") or event_id,
        "shortName": header.get("shortName") or header.get("name") or "?",
        "status": status,
        "competitions": competitions,
    })


# ─── Contract-name parsing ────────────────────────────────────────────
# The squares oracle reads grid `name` strings looking for an "ESPN:<id>"
# tag. Anything else (including legacy names like "Test Bowl") returns
# None and the handler skips that grid.
_ESPN_TAG_RE = re.compile(r"\bESPN:(\d{6,})\b")


def parse_espn_id(name: str) -> str | None:
    """Extract the ESPN event id from a Squares createGame.name string.

    Convention: createGame(name="ESPN:401871337  ·  Cavs vs Pistons G6")
    Anything else returns None; the rest of the display name is free-form
    so the UI can still show 'Cavs vs Pistons G6'."""
    if not name:
        return None
    m = _ESPN_TAG_RE.search(name)
    return m.group(1) if m else None
