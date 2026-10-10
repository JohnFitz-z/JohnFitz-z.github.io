#!/usr/bin/env python3
"""
Morning Line data feed. Runs on GitHub Actions (open internet, standard library only)
and writes into a checkout of the `feed` branch.

    python3 tools/feed/run.py --out <feed dir> --mode morning|afternoon|close|all

  morning    full odds snapshot for every active sport + NHL and MLB stats
  afternoon  full odds snapshot (for the 3:53 PM price check)
  close      odds for sports with a game starting in the next 45 minutes, saved as
             that game's closing line (the last snapshot before it starts)
  stats      NHL and MLB stats only, no odds (used when the feed code changes)
  all        morning

Odds come from The Odds API (env ODDS_API_KEY), regions us + eu (eu has Pinnacle and
Betfair Exchange), markets moneyline/spread/total, decimal odds. Without a key the odds
part is skipped and logged; stats still run.
"""

import argparse
import csv
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Halifax")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 MorningLineFeed/1.0"
ODDS = "https://api.the-odds-api.com/v4"

# Odds API sport key -> (engine sport, league label)
SPORTS = {
    "baseball_mlb": ("MLB", "MLB"),
    "icehockey_nhl": ("NHL", "NHL"),
    "americanfootball_nfl": ("NFL", "NFL"),
    "americanfootball_ncaaf": ("NCAAF", "NCAAF"),
    "americanfootball_cfl": ("CFL", "CFL"),
    "basketball_nba": ("NBA", "NBA"),
    "basketball_wnba": ("WNBA", "WNBA"),
    "basketball_ncaab": ("NCAAB", "NCAAB"),
    "soccer_epl": ("Soccer", "Premier League"),
    "soccer_spain_la_liga": ("Soccer", "La Liga"),
    "soccer_italy_serie_a": ("Soccer", "Serie A"),
    "soccer_germany_bundesliga": ("Soccer", "Bundesliga"),
    "soccer_france_ligue_one": ("Soccer", "Ligue 1"),
    "soccer_uefa_champs_league": ("Soccer", "Champions League"),
    "soccer_uefa_europa_league": ("Soccer", "Europa League"),
    "soccer_usa_mls": ("Soccer", "MLS"),
}
MARKETS = "h2h,spreads,totals"
REGIONS = "us,eu"          # paid plan: US books + Europe (Pinnacle, Betfair)
REGIONS_FREE = "eu"        # free plan: Pinnacle, Betfair and other European books only
CLOSE_WINDOW_MIN = 45
MIN_REMAINING_FOR_CLOSE = 600
FREE_QUOTA_MAX = 1000      # a monthly quota at or below this is treated as the free plan
# Order sports are fetched in when credits are short (free plan)
PRIORITY = ["icehockey_nhl", "americanfootball_nfl", "basketball_nba", "baseball_mlb", "americanfootball_ncaaf",
            "soccer_epl", "soccer_uefa_champs_league", "basketball_ncaab", "basketball_wnba", "soccer_spain_la_liga",
            "soccer_italy_serie_a", "soccer_germany_bundesliga", "soccer_france_ligue_one", "soccer_usa_mls",
            "soccer_uefa_europa_league", "americanfootball_cfl"]
ENGINE_TO_KEYS = {"MLB": ["baseball_mlb"], "NHL": ["icehockey_nhl"], "NFL": ["americanfootball_nfl"],
                  "NCAAF": ["americanfootball_ncaaf"], "CFL": ["americanfootball_cfl"], "NBA": ["basketball_nba"],
                  "WNBA": ["basketball_wnba"], "NCAAB": ["basketball_ncaab"]}
CODE_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def local_date(t):
    return t.astimezone(TZ).date().isoformat()


def get(url, params=None, as_json=True, tries=3, timeout=40):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
                headers = {k.lower(): v for k, v in r.headers.items()}
                return (json.loads(body) if as_json else body), headers
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.reason}"
            if e.code in (401, 403, 404, 422):
                break
        except Exception as e:  # network hiccup, retry
            last = str(e)
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url.split('?')[0]}: {last}")


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)


# ------------------------------------------------------------------ odds


def compact_event(ev):
    """Odds API event -> compact form: prices per book for moneyline, spread (home line) and total."""
    home, away = ev["home_team"], ev["away_team"]
    books = {}
    for bk in ev.get("bookmakers", []):
        b = {}
        for m in bk.get("markets", []):
            outs = m.get("outcomes", [])
            if m["key"] == "h2h":
                p = {}
                for o in outs:
                    side = "home" if o["name"] == home else "away" if o["name"] == away else "draw" if o["name"].lower() == "draw" else None
                    if side:
                        p[side] = o["price"]
                if "home" in p and "away" in p:
                    # Outside soccer a quoted draw means a 60-minute (regulation) 3-way market, which is a
                    # different bet from the moneyline including overtime; keep it apart.
                    is_soccer = ev["sport_key"].startswith("soccer")
                    b["h2h" if (is_soccer or "draw" not in p) else "h2h_3way"] = p
            elif m["key"] == "spreads":
                h = next((o for o in outs if o["name"] == home), None)
                a = next((o for o in outs if o["name"] == away), None)
                if h and a and h.get("point") is not None:
                    b["spreads"] = {"line": h["point"], "home": h["price"], "away": a["price"]}
            elif m["key"] == "totals":
                ov = next((o for o in outs if o["name"].lower() == "over"), None)
                un = next((o for o in outs if o["name"].lower() == "under"), None)
                if ov and un and ov.get("point") is not None and ov.get("point") == un.get("point"):
                    b["totals"] = {"line": ov["point"], "over": ov["price"], "under": un["price"]}
        if b:
            books.setdefault(bk["key"], dict(b, title=bk.get("title", bk["key"]), updated=bk.get("last_update")))
    sport, league = SPORTS.get(ev["sport_key"], (ev.get("sport_title"), ev.get("sport_title")))
    return {"id": ev["id"], "sport_key": ev["sport_key"], "sport": sport, "league": league,
            "commence_time": ev["commence_time"], "home": home, "away": away, "books": books}


class Odds:
    def __init__(self, key, log):
        self.key, self.log = key, log
        self.remaining = self.used = None
        self.plan = os.environ.get("FEED_PLAN", "").strip().lower() or None
        self._active = None

    @property
    def regions(self):
        return REGIONS_FREE if self.plan == "free" else REGIONS

    @property
    def cost(self):  # credits per odds call: markets x regions
        return len(MARKETS.split(",")) * len(self.regions.split(","))

    def _track(self, headers):
        if "x-requests-remaining" in headers:
            try:
                self.remaining = float(headers["x-requests-remaining"])
                self.used = float(headers.get("x-requests-used", 0))
            except ValueError:
                pass
        if self.plan is None and self.remaining is not None and self.used is not None:
            self.plan = "free" if self.remaining + self.used <= FREE_QUOTA_MAX else "paid"

    def daily_allowance(self):
        """Credits we can spend today without running out before the month resets."""
        if self.remaining is None:
            return 0
        today = now_utc().date()
        nxt = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        return self.remaining / max(1, (nxt - today).days)

    def active_sports(self):
        if self._active is None:
            data, h = get(f"{ODDS}/sports", {"apiKey": self.key})
            self._track(h)
            self._active = [s["key"] for s in data if s.get("active") and s["key"] in SPORTS]
        return self._active

    def events(self, sport):  # free endpoint
        data, h = get(f"{ODDS}/sports/{sport}/events", {"apiKey": self.key, "dateFormat": "iso"})
        self._track(h)
        return data

    def odds(self, sport, frm=None, to=None):
        params = {"apiKey": self.key, "regions": self.regions, "markets": MARKETS, "oddsFormat": "decimal", "dateFormat": "iso"}
        if frm:
            params["commenceTimeFrom"] = iso(frm)
        if to:
            params["commenceTimeTo"] = iso(to)
        data, h = get(f"{ODDS}/sports/{sport}/odds", params)
        self._track(h)
        return [compact_event(e) for e in data]


def todays_pick_sports(t0):
    """Odds API sport keys and start times of today's pick(s) and backups, from the site's picks.json."""
    try:
        with open(os.path.join(CODE_ROOT, "data", "picks.json")) as f:
            picks = json.load(f).get("picks", [])
    except (OSError, ValueError):
        return {}
    day = local_date(t0)
    out = {}
    for p in picks:
        if str(p.get("date")) != day or p.get("excluded"):
            continue
        for bet in [p] + list(p.get("backups") or []):
            keys = ENGINE_TO_KEYS.get(str(bet.get("sport", "")).upper())
            if not keys and str(bet.get("sport", "")).lower() == "soccer":
                lg = str(bet.get("league", "")).lower()
                keys = [k for k, (_, label) in SPORTS.items() if k.startswith("soccer") and
                        (label.lower() in lg or lg in label.lower() or any(w in lg for w in label.lower().split() if len(w) > 3))]
            for k in keys or []:
                if bet.get("start_time"):
                    out.setdefault(k, []).append(parse_iso(bet["start_time"]))
    return out


def sports_with_games(odds, t0, hours):
    """Active sports that have a game starting in the next `hours` (uses the free events endpoint)."""
    out = []
    for sport in odds.active_sports():
        try:
            evs = odds.events(sport)
        except Exception as e:
            odds.log["errors"].append(f"events {sport}: {e}")
            continue
        if any(t0 < parse_iso(e["commence_time"]) <= t0 + dt.timedelta(hours=hours) for e in evs):
            out.append(sport)
    return sorted(out, key=lambda k: PRIORITY.index(k) if k in PRIORITY else 99)


def snapshot(odds, out, name, log):
    t0 = now_utc()
    events, per_sport = [], {}
    sports = odds.active_sports()
    budget = None
    if odds.plan == "free":
        if name == "afternoon":
            sports = [k for k in sports_with_games(odds, t0, 12) if k in todays_pick_sports(t0)]
            budget = odds.daily_allowance() * 0.3
        else:
            sports = sports_with_games(odds, t0, 24)
            budget = odds.daily_allowance() * 0.7
        log["budget"] = {"plan": "free", "credits_for_this_run": round(budget, 1), "cost_per_sport": odds.cost}
    spent = 0
    for sport in sports:
        if budget is not None and spent + odds.cost > budget:
            log.setdefault("skipped_for_budget", []).append(sport)
            continue
        spent += odds.cost
        try:
            evs = odds.odds(sport, frm=t0, to=t0 + dt.timedelta(hours=40))
            events += evs
            per_sport[sport] = len(evs)
        except Exception as e:
            log["errors"].append(f"odds {sport}: {e}")
    snap = {"fetched_at": iso(t0), "kind": name, "events": events}
    day = local_date(t0)
    write_json(os.path.join(out, "odds", day, f"{name}.json"), snap)
    write_json(os.path.join(out, "odds", f"latest_{name}.json"), snap)
    write_json(os.path.join(out, "odds", "latest.json"), snap)
    log["odds"] = {"kind": name, "events": len(events), "per_sport": per_sport}
    return snap


def closing(odds, out, log):
    if odds.remaining is not None and odds.remaining < MIN_REMAINING_FOR_CLOSE:
        log["odds"] = {"kind": "close", "skipped": f"only {odds.remaining:.0f} credits left"}
        return
    t0 = now_utc()
    soon = t0 + dt.timedelta(minutes=CLOSE_WINDOW_MIN)
    saved, checked = 0, []
    sports = odds.active_sports()
    if odds.plan == "free":
        # Free plan: only the closing lines of today's pick and backups.
        mine = todays_pick_sports(t0)
        sports = [k for k in sports if any(t0 < st <= soon + dt.timedelta(minutes=5) for st in mine.get(k, []))]
        if not sports:
            log["odds"] = {"kind": "close", "plan": "free", "note": "no pick or backup starting soon"}
            return
    for sport in sports:
        try:
            evs = odds.events(sport)
        except Exception as e:
            log["errors"].append(f"events {sport}: {e}")
            continue
        upcoming = [e for e in evs if t0 < parse_iso(e["commence_time"]) <= soon]
        if not upcoming:
            continue
        checked.append(sport)
        try:
            snap = odds.odds(sport, frm=t0, to=soon)
        except Exception as e:
            log["errors"].append(f"odds {sport}: {e}")
            continue
        by_day = {}
        for e in snap:
            by_day.setdefault(local_date(parse_iso(e["commence_time"])), []).append(e)
        for day, evs_day in by_day.items():
            path = os.path.join(out, "odds", "closing", f"{day}.json")
            cur = read_json(path, {"events": {}})
            for e in evs_day:
                cur["events"][e["id"]] = dict(e, snapshot_at=iso(t0))
                saved += 1
            write_json(path, cur)
    log["odds"] = {"kind": "close", "sports_checked": checked, "events_saved": saved}


# ------------------------------------------------------------------ NHL (MoneyPuck)

NHL_TEAMS = {  # Odds API / full name -> (MoneyPuck code, nickname)
    "Anaheim Ducks": ("ANA", "Ducks"), "Boston Bruins": ("BOS", "Bruins"), "Buffalo Sabres": ("BUF", "Sabres"),
    "Calgary Flames": ("CGY", "Flames"), "Carolina Hurricanes": ("CAR", "Hurricanes"), "Chicago Blackhawks": ("CHI", "Blackhawks"),
    "Colorado Avalanche": ("COL", "Avalanche"), "Columbus Blue Jackets": ("CBJ", "Blue Jackets"), "Dallas Stars": ("DAL", "Stars"),
    "Detroit Red Wings": ("DET", "Red Wings"), "Edmonton Oilers": ("EDM", "Oilers"), "Florida Panthers": ("FLA", "Panthers"),
    "Los Angeles Kings": ("LAK", "Kings"), "Minnesota Wild": ("MIN", "Wild"), "Montreal Canadiens": ("MTL", "Canadiens"),
    "Montréal Canadiens": ("MTL", "Canadiens"), "Nashville Predators": ("NSH", "Predators"), "New Jersey Devils": ("NJD", "Devils"),
    "New York Islanders": ("NYI", "Islanders"), "New York Rangers": ("NYR", "Rangers"), "Ottawa Senators": ("OTT", "Senators"),
    "Philadelphia Flyers": ("PHI", "Flyers"), "Pittsburgh Penguins": ("PIT", "Penguins"), "San Jose Sharks": ("SJS", "Sharks"),
    "Seattle Kraken": ("SEA", "Kraken"), "St Louis Blues": ("STL", "Blues"), "St. Louis Blues": ("STL", "Blues"),
    "Tampa Bay Lightning": ("TBL", "Lightning"), "Toronto Maple Leafs": ("TOR", "Maple Leafs"), "Utah Mammoth": ("UTA", "Mammoth"),
    "Utah Hockey Club": ("UTA", "Mammoth"), "Vancouver Canucks": ("VAN", "Canucks"), "Vegas Golden Knights": ("VGK", "Golden Knights"),
    "Washington Capitals": ("WSH", "Capitals"), "Winnipeg Jets": ("WPG", "Jets"),
}


def nhl_season(t):
    d = t.astimezone(TZ)
    return d.year if d.month >= 9 else d.year - 1  # MoneyPuck labels 2025-26 as 2025


def moneypuck(season, kind):
    body, _ = get(f"https://moneypuck.com/moneypuck/playerData/seasonSummary/{season}/regular/{kind}.csv", as_json=False)
    return list(csv.DictReader(io.StringIO(body)))


def f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def nhl_stats(out, log):
    cur = nhl_season(now_utc())
    teams, goalies = {}, {}
    for season in (cur, cur - 1):
        try:
            rows = moneypuck(season, "teams")
            t = {}
            for r in rows:  # all situations first, so the 5on5 entry below can carry both
                if r.get("situation") == "all" and f(r.get("iceTime")) > 0:
                    ice = f(r.get("iceTime"))
                    t.setdefault(r["team"], {}).update({
                        "xgf60_all": round(f(r.get("scoreVenueAdjustedxGoalsFor") or r.get("xGoalsFor")) / ice * 3600, 3),
                        "xga60_all": round(f(r.get("scoreVenueAdjustedxGoalsAgainst") or r.get("xGoalsAgainst")) / ice * 3600, 3)})
            for r in rows:
                if r.get("situation") != "5on5":
                    continue
                ice = f(r.get("iceTime"))
                if ice <= 0:
                    continue
                t.setdefault(r["team"], {}).update({
                    "gp": int(f(r.get("games_played"))),
                    "toi_min": round(ice / 60, 1),
                    "xgf60": round(f(r.get("scoreVenueAdjustedxGoalsFor") or r.get("xGoalsFor")) / ice * 3600, 3),
                    "xga60": round(f(r.get("scoreVenueAdjustedxGoalsAgainst") or r.get("xGoalsAgainst")) / ice * 3600, 3),
                    "gf60": round(f(r.get("goalsFor")) / ice * 3600, 3),
                    "ga60": round(f(r.get("goalsAgainst")) / ice * 3600, 3),
                })
            t = {k: v for k, v in t.items() if "xgf60" in v}
            teams[str(season)] = t
        except Exception as e:
            log["errors"].append(f"moneypuck teams {season}: {e}")
        try:
            rows = moneypuck(season, "goalies")
            g = {}
            for r in rows:
                if r.get("situation") != "all":
                    continue
                ice = f(r.get("icetime"))
                if ice <= 0:
                    continue
                g[r["name"]] = {"team": r.get("team"), "gp": int(f(r.get("games_played"))), "hours": round(ice / 3600, 2),
                                "gsax": round(f(r.get("xGoals")) - f(r.get("goals")), 2)}
            goalies[str(season)] = g
        except Exception as e:
            log["errors"].append(f"moneypuck goalies {season}: {e}")
    write_json(os.path.join(out, "stats", "nhl.json"),
               {"fetched_at": iso(now_utc()), "current_season": cur, "teams": teams, "goalies": goalies, "team_map": NHL_TEAMS})
    log["nhl"] = {s: len(v) for s, v in teams.items()} | {f"goalies_{s}": len(v) for s, v in goalies.items()}


# ------------------------------------------------------------------ MLB (MLB Stats API)

MLB = "https://statsapi.mlb.com/api/v1"


def ip_to_float(ip):
    s = str(ip or "0")
    if "." in s:
        whole, frac = s.split(".", 1)
        return int(whole or 0) + {"0": 0, "1": 1 / 3, "2": 2 / 3}.get(frac[:1], 0)
    return f(s)


def pitching_line(st):
    ip = ip_to_float(st.get("inningsPitched"))
    return {"ip": round(ip, 2), "gs": int(f(st.get("gamesStarted"))), "era": f(st.get("era"), None),
            "hr": int(f(st.get("homeRuns"))), "bb": int(f(st.get("baseOnBalls"))), "hbp": int(f(st.get("hitByPitch"))),
            "k": int(f(st.get("strikeOuts")))}


def team_stats(season, group):
    data, _ = get(f"{MLB}/teams/stats", {"season": season, "group": group, "stats": "season", "sportIds": 1})
    out = {}
    for sp in (data.get("stats") or [{}])[0].get("splits", []):
        out[sp["team"]["name"]] = sp["stat"]
    return out


def mlb_stats(out, log):
    t0 = now_utc()
    season = t0.astimezone(TZ).year
    start = local_date(t0)
    end = (t0.astimezone(TZ).date() + dt.timedelta(days=1)).isoformat()
    try:
        sched, _ = get(f"{MLB}/schedule", {"sportId": 1, "startDate": start, "endDate": end, "hydrate": "probablePitcher,team"})
    except Exception as e:
        log["errors"].append(f"mlb schedule: {e}")
        return
    games, pids = [], set()
    for d in sched.get("dates", []):
        for g in d.get("games", []):
            row = {"game_pk": g["gamePk"], "date": d["date"], "start": g.get("gameDate"), "type": g.get("gameType"),
                   "venue": (g.get("venue") or {}).get("name")}
            for side in ("home", "away"):
                tm = g["teams"][side]
                pp = tm.get("probablePitcher") or {}
                row[side] = {"team": tm["team"]["name"], "team_id": tm["team"]["id"], "pitcher": pp.get("fullName"), "pitcher_id": pp.get("id")}
                if pp.get("id"):
                    pids.add(pp["id"])
            games.append(row)
    pitchers = {}
    if pids:
        for yr in (season, season - 1):
            try:
                data, _ = get(f"{MLB}/people", {"personIds": ",".join(map(str, sorted(pids))),
                                                "hydrate": f"stats(group=[pitching],type=[season],season={yr})"})
                for p in data.get("people", []):
                    splits = ((p.get("stats") or [{}])[0].get("splits") or [])
                    if splits:
                        pitchers.setdefault(str(p["id"]), {"name": p.get("fullName"), "hand": (p.get("pitchHand") or {}).get("code")})[str(yr)] = pitching_line(splits[0]["stat"])
            except Exception as e:
                log["errors"].append(f"mlb pitchers {yr}: {e}")
    teams = {}
    for yr in (season, season - 1):
        try:
            hit, pit = team_stats(yr, "hitting"), team_stats(yr, "pitching")
            teams[str(yr)] = {name: {"g": int(f(s.get("gamesPlayed"))), "obp": f(s.get("obp")), "slg": f(s.get("slg")),
                                     "ops": f(s.get("ops")), "pitching": pitching_line(pit.get(name, {}))} for name, s in hit.items()}
        except Exception as e:
            log["errors"].append(f"mlb teams {yr}: {e}")
    write_json(os.path.join(out, "stats", "mlb", f"{start}.json"),
               {"fetched_at": iso(t0), "season": season, "games": games, "pitchers": pitchers, "teams": teams})
    write_json(os.path.join(out, "stats", "mlb", "latest.json"),
               {"fetched_at": iso(t0), "season": season, "games": games, "pitchers": pitchers, "teams": teams})
    log["mlb"] = {"games": len(games), "pitchers": len(pitchers), "team_seasons": list(teams)}


# ------------------------------------------------------------------ main


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", default="morning", choices=["morning", "afternoon", "close", "stats", "all"])
    a = ap.parse_args(argv)
    mode = "morning" if a.mode == "all" else a.mode
    log = {"started_at": iso(now_utc()), "mode": mode, "errors": []}
    key = os.environ.get("ODDS_API_KEY", "").strip()
    odds = Odds(key, log) if key else None
    try:
        if mode == "stats":
            pass  # code changes re-run the stats only, so pushes don't spend odds credits
        elif not odds:
            log["errors"].append("ODDS_API_KEY is not set, odds skipped")
        elif mode in ("morning", "afternoon"):
            snapshot(odds, a.out, mode, log)
        else:
            closing(odds, a.out, log)
    except Exception as e:
        log["errors"].append(f"odds: {e}")
    if mode in ("morning", "stats"):
        for fn in (nhl_stats, mlb_stats):
            try:
                fn(a.out, log)
            except Exception as e:
                log["errors"].append(f"{fn.__name__}: {e}")
    if odds and odds.remaining is not None:
        log["credits"] = {"remaining": odds.remaining, "used": odds.used, "plan": odds.plan}
        write_json(os.path.join(a.out, "odds", "usage.json"), {"at": iso(now_utc()), "remaining": odds.remaining, "used": odds.used})
    log["finished_at"] = iso(now_utc())
    write_json(os.path.join(a.out, "log", f"{mode}.json"), log)
    print(json.dumps(log, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
