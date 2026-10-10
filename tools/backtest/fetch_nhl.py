#!/usr/bin/env python3
"""
Download NHL history for backtesting (runs on GitHub Actions; standard library only).

    python3 tools/backtest/fetch_nhl.py --out <feed dir> [--seasons 2021-2025]

Writes <feed dir>/backtest/nhl.json with, for every regular-season game:
  - each team's 5v5 and all-situation expected goals and goals (MoneyPuck game by game)
  - the final score including the shootout winner, and how it ended (NHL API)
  - both starting goalies (NHL API box scores)
plus every goalie's season totals (MoneyPuck) so prior-season GSAx can be used without
peeking at the game being predicted. MoneyPuck labels seasons by start year (2025 = 2025-26).
"""

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 MorningLineBacktest/1.0"
MP_TEAMS = ["ANA", "ARI", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL", "DAL", "DET", "EDM", "FLA", "LAK", "MIN", "MTL",
            "NJD", "NSH", "NYI", "NYR", "OTT", "PHI", "PIT", "SEA", "SJS", "STL", "TBL", "TOR", "UTA", "VAN", "VGK", "WPG", "WSH"]
NHL_ABBR = {"LAK": "LAK", "NJD": "NJD", "SJS": "SJS", "TBL": "TBL"}  # MoneyPuck and NHL mostly agree


def get(url, as_json=True, tries=3, timeout=60):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
            return json.loads(body) if as_json else body
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def team_games(code, seasons, log):
    """MoneyPuck team game-by-game rows for the given seasons, 5on5 and all situations merged per game."""
    try:
        body = get(f"https://moneypuck.com/moneypuck/playerData/careers/gameByGame/regular/teams/{code}.csv", as_json=False)
    except Exception as e:
        log["errors"].append(f"moneypuck {code}: {e}")
        return []
    games = {}
    for r in csv.DictReader(io.StringIO(body)):
        try:
            season = int(f(r.get("season")))
        except ValueError:
            continue
        if season not in seasons or r.get("situation") not in ("5on5", "all"):
            continue
        gid = str(r.get("gameId"))
        g = games.setdefault(gid, {"s": season, "g": gid, "d": r.get("gameDate"), "t": r.get("playerTeam") or code,
                                   "o": r.get("opposingTeam"), "h": 1 if str(r.get("home_or_away", "")).upper() == "HOME" else 0})
        sfx = "5" if r["situation"] == "5on5" else "A"
        ice = f(r.get("iceTime"))
        g[f"ice{sfx}"] = round(ice / 60, 2)
        g[f"xgf{sfx}"] = round(f(r.get("scoreVenueAdjustedxGoalsFor") or r.get("xGoalsFor")), 3)
        g[f"xga{sfx}"] = round(f(r.get("scoreVenueAdjustedxGoalsAgainst") or r.get("xGoalsAgainst")), 3)
        g[f"gf{sfx}"] = int(f(r.get("goalsFor")))
        g[f"ga{sfx}"] = int(f(r.get("goalsAgainst")))
    return list(games.values())


def schedules(seasons, log):
    """Final scores (shootout winner included) for every regular-season game, from the NHL API."""
    out = {}
    for s in seasons:
        for code in MP_TEAMS:
            abbr = NHL_ABBR.get(code, code)
            try:
                data = get(f"https://api-web.nhle.com/v1/club-schedule-season/{abbr}/{s}{s + 1}")
            except Exception:
                continue  # team didn't exist that season (ARI after 2023, UTA before 2024, SEA before 2021)
            for g in data.get("games", []):
                if g.get("gameType") != 2 or g.get("gameState") not in ("OFF", "FINAL"):
                    continue
                out[str(g["id"])] = {"s": s, "date": g.get("gameDate"), "start": g.get("startTimeUTC"),
                                     "home": g["homeTeam"]["abbrev"], "away": g["awayTeam"]["abbrev"],
                                     "hs": g["homeTeam"].get("score"), "as": g["awayTeam"].get("score"),
                                     "end": (g.get("gameOutcome") or {}).get("lastPeriodType")}
    log["schedule_games"] = len(out)
    return out


def starter_of(goalies):
    if not goalies:
        return None
    st = [x for x in goalies if x.get("starter")]
    pick = st[0] if st else max(goalies, key=lambda x: sum(int(p) * m for p, m in zip(str(x.get("toi", "0:0")).split(":"), (60, 1))))
    return {"id": pick.get("playerId"), "name": (pick.get("name") or {}).get("default")}


def starters(game_ids, log):
    def one(gid):
        try:
            b = get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore", tries=2, timeout=30)
            pg = b.get("playerByGameStats") or {}
            return gid, {"home": starter_of((pg.get("homeTeam") or {}).get("goalies")),
                         "away": starter_of((pg.get("awayTeam") or {}).get("goalies"))}
        except Exception as e:
            return gid, {"error": str(e)[:120]}
    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for gid, res in ex.map(one, game_ids):
            out[gid] = res
    log["starters"] = sum(1 for v in out.values() if "error" not in v)
    log["starter_errors"] = sum(1 for v in out.values() if "error" in v)
    return out


def goalie_seasons(seasons, log):
    out = {}
    for s in seasons:
        try:
            body = get(f"https://moneypuck.com/moneypuck/playerData/seasonSummary/{s}/regular/goalies.csv", as_json=False)
        except Exception as e:
            log["errors"].append(f"moneypuck goalies {s}: {e}")
            continue
        g = {}
        for r in csv.DictReader(io.StringIO(body)):
            if r.get("situation") != "all":
                continue
            g[str(r.get("playerId"))] = {"name": r.get("name"), "team": r.get("team"), "gp": int(f(r.get("games_played"))),
                                         "hours": round(f(r.get("icetime")) / 3600, 2), "gsax": round(f(r.get("xGoals")) - f(r.get("goals")), 2)}
        out[str(s)] = g
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seasons", default="2021-2025", help="first-last MoneyPuck season (start year)")
    a = ap.parse_args(argv)
    lo, hi = (int(x) for x in a.seasons.split("-"))
    seasons = list(range(lo, hi + 1))
    eval_seasons = seasons[1:]  # the first season only feeds the next one's priors
    log = {"seasons": seasons, "errors": []}
    t0 = time.time()

    rows = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for part in ex.map(lambda c: team_games(c, set(seasons), log), MP_TEAMS):
            rows += part
    log["team_game_rows"] = len(rows)
    sched = schedules(eval_seasons, log)
    st = starters(sorted(sched), log)
    gs = goalie_seasons(seasons, log)
    log["seconds"] = round(time.time() - t0)

    os.makedirs(os.path.join(a.out, "backtest"), exist_ok=True)
    with open(os.path.join(a.out, "backtest", "nhl.json"), "w") as fh:
        json.dump({"seasons": seasons, "team_games": rows, "results": sched, "starters": st, "goalie_seasons": gs, "log": log},
                  fh, separators=(",", ":"))
    print(json.dumps(log, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
