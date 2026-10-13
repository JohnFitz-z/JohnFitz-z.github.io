#!/usr/bin/env python3
"""
Grade finished bets from free official score feeds, with no AI involved.

    python3 tools/grade.py            # grade everything that's due, record closing lines, update notes
    python3 tools/grade.py --dry-run  # show what would change, write nothing

Sources (no keys needed): the NHL's api-web.nhle.com, MLB's statsapi.mlb.com, and ESPN's public
scoreboards for football, basketball and soccer. Box scores are used for player props.

For every pending bet (top pick, card and old backups) whose game should be over, it finds the game,
settles the bet exactly as written (NHL/MLB/NFL/NBA include overtime; soccer is 90 minutes; first-five
bets count five innings; quarter lines split), writes status, final_score, result_units and graded_at
into db/picks/<id>.json, records the closing line from the data feed when it can, and appends a line to
notes/journal.md for the analyst to review. Anything it can't settle with certainty (a cup game that
went to extra time, a player it can't find in the box score) is left pending and listed, so the next
analyst run settles it by hand.
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import db  # noqa: E402

ET = ZoneInfo("America/New_York")
HFX = ZoneInfo("America/Halifax")
UA = {"User-Agent": "Mozilla/5.0 (Morning Line grader)"}

# Minutes after the start before a game can be over.
MIN_MINUTES = {"SOCCER": 110, "NBA": 135, "WNBA": 135, "NCAAB": 135, "NHL": 140, "MLB": 150, "NFL": 180, "NCAAF": 180,
               "CFL": 180, "TENNIS": 90, "MMA": 90}
ESPN = {"NFL": ("football", "nfl"), "NCAAF": ("football", "college-football"), "CFL": ("football", "cfl"),
        "NBA": ("basketball", "nba"), "WNBA": ("basketball", "wnba"), "NCAAB": ("basketball", "mens-college-basketball")}
SOCCER = [("premier league", "eng.1"), ("epl", "eng.1"), ("championship", "eng.2"), ("la liga", "esp.1"),
          ("serie a", "ita.1"), ("bundesliga", "ger.1"), ("ligue 1", "fra.1"), ("mls", "usa.1"),
          ("champions league", "uefa.champions"), ("europa league", "uefa.europa"), ("conference league", "uefa.europa.conf"),
          ("eredivisie", "ned.1"), ("primeira", "por.1"), ("liga mx", "mex.1"), ("scottish", "sco.1"),
          ("brasileiro", "bra.1"), ("serie b", "ita.2"), ("league one", "eng.3"), ("league two", "eng.4")]
SOCCER_FALLBACK = ["eng.1", "esp.1", "ita.1", "ger.1", "fra.1", "uefa.champions", "uefa.europa", "eng.2", "usa.1",
                   "ned.1", "por.1", "uefa.europa.conf", "sco.1", "mex.1"]

_cache = {}


def fetch(url):
    if url in _cache:
        return _cache[url]
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                data = json.loads(r.read().decode())
            _cache[url] = data
            return data
        except Exception as e:  # network hiccup: retry, then give up on this source
            last = e
            time.sleep(2 * (attempt + 1))
    print(f"  could not fetch {url}: {last}")
    _cache[url] = None
    return None


# ---------------------------------------------------------------- names

STOP = {"fc", "cf", "sc", "afc", "ac", "the", "club", "de", "cd", "ud", "sk", "fk", "if", "bk"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(w for w in s.split() if w not in STOP)


def name_match(ours, *theirs):
    """True if our team name and any of the feed's names refer to the same team."""
    a = norm(ours)
    if not a:
        return False
    for t in theirs:
        b = norm(t)
        if not b:
            continue
        if a == b or (len(a) >= 4 and a in b) or (len(b) >= 4 and b in a):
            return True
        wa, wb = set(a.split()), set(b.split())
        if wa and wb and (wa <= wb or wb <= wa):
            return True
    return False


# ---------------------------------------------------------------- finding games

def et_date(start):
    t = dt.datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    return t.astimezone(ET).date()


def nhl_games(day):
    d = fetch(f"https://api-web.nhle.com/v1/score/{day.isoformat()}") or {}
    out = []
    for g in d.get("games", []):
        h, a = g.get("homeTeam", {}), g.get("awayTeam", {})
        hn = [(h.get("name") or {}).get("default"), h.get("abbrev"), (h.get("placeName") or {}).get("default") if isinstance(h.get("placeName"), dict) else None]
        an = [(a.get("name") or {}).get("default"), a.get("abbrev"), (a.get("placeName") or {}).get("default") if isinstance(a.get("placeName"), dict) else None]
        state = g.get("gameState")
        status = "final" if state in ("OFF", "FINAL") else ("void" if g.get("gameScheduleState") in ("PPD", "CNCL") else "open")
        last = ((g.get("gameOutcome") or {}).get("lastPeriodType") or "REG")
        out.append({"home_names": hn, "away_names": an, "home": h.get("score"), "away": a.get("score"), "status": status,
                    "label": f"{an[0]} {a.get('score')}, {hn[0]} {h.get('score')}" + (f" ({last})" if last != "REG" else ""),
                    "box": ("nhl", g.get("id")), "home_disp": hn[0], "away_disp": an[0]})
    return out


def mlb_games(day):
    d = fetch(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={day.isoformat()}&hydrate=linescore") or {}
    out = []
    for dd in d.get("dates", []):
        for g in dd.get("games", []):
            st = g.get("status", {})
            det = str(st.get("detailedState", ""))
            status = "final" if st.get("abstractGameState") == "Final" and not re.search(r"postpon|cancel|suspend", det, re.I) else \
                     ("void" if re.search(r"postpon|cancel", det, re.I) else "open")
            th, ta = g["teams"]["home"], g["teams"]["away"]
            inns = (g.get("linescore") or {}).get("innings") or []
            f5 = None
            if len(inns) >= 5:
                f5 = (sum((i.get("home") or {}).get("runs") or 0 for i in inns[:5]), sum((i.get("away") or {}).get("runs") or 0 for i in inns[:5]))
            out.append({"home_names": [th["team"].get("name")], "away_names": [ta["team"].get("name")], "home": th.get("score"),
                        "away": ta.get("score"), "status": status, "f5": f5, "box": ("mlb", g.get("gamePk")),
                        "label": f"{ta['team'].get('name')} {ta.get('score')}, {th['team'].get('name')} {th.get('score')}",
                        "home_disp": th["team"].get("name"), "away_disp": ta["team"].get("name")})
    return out


def espn_games(sport, league, day, soccer=False):
    extra = "&groups=80&limit=400" if league == "college-football" else ("&groups=50&limit=400" if league == "mens-college-basketball" else "")
    d = fetch(f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates={day.strftime('%Y%m%d')}{extra}") or {}
    out = []
    for ev in d.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        st = (ev.get("status") or comp.get("status") or {}).get("type", {})
        name = str(st.get("name", ""))
        detail = str(st.get("detail", "")) + " " + str(st.get("shortDetail", ""))
        if st.get("completed") and st.get("state") == "post":
            status = "final"
            if soccer and re.search(r"AET|Pen|ET", detail):
                status = "needs_review"  # 90-minute score isn't on the scoreboard
        elif re.search(r"POSTPONED|CANCELED|CANCELLED", name):
            status = "void"
        else:
            status = "open"
        teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        h, a = teams.get("home", {}), teams.get("away", {})
        names = lambda c: [c.get("team", {}).get(k) for k in ("displayName", "shortDisplayName", "name", "location", "abbreviation")]
        num = lambda c: int(float(c["score"])) if c.get("score") not in (None, "") else None
        out.append({"home_names": names(h), "away_names": names(a), "home": num(h), "away": num(a), "status": status,
                    "label": f"{a.get('team', {}).get('displayName')} {a.get('score')}, {h.get('team', {}).get('displayName')} {h.get('score')}"
                             + (" (OT)" if re.search(r"OT", detail) and not soccer else ""),
                    "box": ("espn", sport, league, ev.get("id")),
                    "home_disp": h.get("team", {}).get("displayName"), "away_disp": a.get("team", {}).get("displayName")})
    return out


def sport_key(b):
    s = str(b.get("sport") or "").upper()
    return "SOCCER" if s in ("SOCCER", "FOOTBALL (SOCCER)") else s


def candidates_for(b, day):
    s = sport_key(b)
    if s == "NHL":
        return nhl_games(day)
    if s == "MLB":
        return mlb_games(day)
    if s in ESPN:
        return espn_games(*ESPN[s], day)
    if s == "SOCCER":
        lg = norm(b.get("league"))
        slugs = [slug for key, slug in SOCCER if key in lg] + SOCCER_FALLBACK
        seen, out = set(), []
        for slug in slugs:
            if slug in seen:
                continue
            seen.add(slug)
            games = espn_games("soccer", slug, day, soccer=True)
            out += games
            if any(match(b, g) for g in games):
                break
        return out
    return []


def match(b, g):
    home, away = b.get("home"), b.get("away")
    if not home and not away and b.get("event"):
        parts = re.split(r"\s+(?:@|vs\.?|v)\s+", str(b["event"]))
        if len(parts) == 2:
            away, home = (parts[0], parts[1]) if "@" in str(b["event"]) else (parts[1], parts[0])
            if "@" not in str(b["event"]):  # "Home vs Away"
                home, away = parts[0], parts[1]
    return name_match(home, *g["home_names"]) and name_match(away, *g["away_names"])


def find_game(b):
    day = et_date(b["start_time"])
    for d in (day, day - dt.timedelta(days=1), day + dt.timedelta(days=1)):
        for g in candidates_for(b, d):
            if match(b, g):
                return g
    return None


# ---------------------------------------------------------------- settling

def kind_of(b):
    inp = b.get("input") or {}
    k = str(inp.get("market") or b.get("market_key") or b.get("market") or "").lower().strip()
    k = k.replace(" ", "_")
    for word, kind in (("player", None), ("team_total", "team_total"), ("btts", "btts"), ("both_teams", "btts"),
                       ("draw_no_bet", "draw_no_bet"), ("puck_line", "spread"), ("run_line", "spread"), ("handicap", "spread"),
                       ("spread", "spread"), ("total", "total"), ("moneyline", "moneyline"), ("1x2", "moneyline")):
        if word in k:
            if kind is None:
                return k if k.startswith("player_") else "player_" + k.split("player")[-1].strip("_")
            return kind + ("_f5" if "f5" in k or "first_5" in k else "")
    return k


def sel_of(b):
    inp = b.get("input") or {}
    return str(inp.get("selection") or b.get("selection") or "").lower()


def line_of(b):
    inp = b.get("input") or {}
    v = inp.get("line") if inp.get("line") is not None else b.get("line")
    return float(v) if v is not None else None


def split_line(line):
    """A quarter line is two half-stakes on the neighbouring half/whole lines."""
    if line is None:
        return [None]
    frac = round(abs(line) % 1, 2)
    if frac in (0.25, 0.75):
        return [line - 0.25, line + 0.25]
    return [line]


def one(diff):
    return "won" if diff > 1e-9 else ("lost" if diff < -1e-9 else "push")


def combine(results):
    if len(results) == 1:
        return results[0]
    r = sorted(results)
    if r == ["won", "won"]:
        return "won"
    if r == ["lost", "lost"]:
        return "lost"
    if r == ["push", "won"]:
        return "half_won"
    if r == ["lost", "push"]:
        return "half_lost"
    return "push"


def settle_scores(kind, sel, line, h, a, team=None):
    """Status for a team-level bet given the home and away score that counts for it."""
    if kind.startswith("moneyline"):
        if sel == "draw":
            return "won" if h == a else "lost"
        if h == a:
            return "push" if kind.endswith("_f5") else "lost"  # a 2-way bet that ends level (soccer 1X2 side) loses
        return "won" if (h > a) == (sel == "home") else "lost"
    if kind == "draw_no_bet":
        if h == a:
            return "void"
        return "won" if (h > a) == (sel == "home") else "lost"
    if kind.startswith("spread"):
        mine, theirs = (h, a) if sel == "home" else (a, h)
        return combine([one(mine - theirs + ln) for ln in split_line(line)])
    if kind.startswith("total"):
        t = h + a
        return combine([one((t - ln) if sel == "over" else (ln - t)) for ln in split_line(line)])
    if kind.startswith("team_total"):
        t = h if (team or "home") == "home" else a
        return combine([one((t - ln) if sel == "over" else (ln - t)) for ln in split_line(line)])
    if kind == "btts":
        both = h > 0 and a > 0
        return "won" if both == (sel in ("yes", "over")) else "lost"
    return None


# player props ----------------------------------------------------------------

def last_first(n):
    n = norm(n).split()
    return (n[-1], n[0][0]) if n else ("", "")


def player_stat(game, player, stat, sport):
    """The player's value for a stat from the box score, or None if not found."""
    box = game["box"]
    want = last_first(player)
    stat = stat.replace("player_", "")
    if box[0] == "nhl":
        d = fetch(f"https://api-web.nhle.com/v1/gamecenter/{box[1]}/boxscore") or {}
        for side in ("homeTeam", "awayTeam"):
            for grp in ("forwards", "defense", "goalies"):
                for p in (d.get("playerByGameStats", {}).get(side, {}).get(grp) or []):
                    nm = (p.get("name") or {}).get("default", "")
                    parts = norm(nm).split()
                    if parts and parts[-1] == want[0] and parts[0][0] == want[1]:
                        m = {"points": "points", "goals": "goals", "assists": "assists", "shots_on_goal": "sog", "shots": "sog",
                             "sog": "sog", "saves": "saves", "blocked_shots": "blockedShots", "hits": "hits"}
                        k = m.get(stat)
                        if k == "saves" and "saves" not in p and "saveShotsAgainst" in p:
                            return float(str(p["saveShotsAgainst"]).split("/")[0])
                        return float(p[k]) if k and p.get(k) is not None else None
        return None
    if box[0] == "mlb":
        d = fetch(f"https://statsapi.mlb.com/api/v1/game/{box[1]}/boxscore") or {}
        for side in ("home", "away"):
            for p in (d.get("teams", {}).get(side, {}).get("players") or {}).values():
                if last_first(p.get("person", {}).get("fullName", "")) != want:
                    continue
                bat, pit = p.get("stats", {}).get("batting") or {}, p.get("stats", {}).get("pitching") or {}
                if stat in ("strikeouts", "pitcher_strikeouts") and pit:
                    return float(pit.get("strikeOuts", 0))
                if stat == "outs":
                    return float(pit.get("outs", 0)) if pit else None
                if not bat:
                    return None
                tb = bat.get("hits", 0) + bat.get("doubles", 0) + 2 * bat.get("triples", 0) + 3 * bat.get("homeRuns", 0)
                m = {"hits": bat.get("hits"), "total_bases": tb, "home_runs": bat.get("homeRuns"), "rbis": bat.get("rbi"),
                     "runs": bat.get("runs"), "walks": bat.get("baseOnBalls"), "batter_strikeouts": bat.get("strikeOuts"),
                     "hits_runs_rbis": (bat.get("hits", 0) + bat.get("runs", 0) + bat.get("rbi", 0))}
                v = m.get(stat)
                return float(v) if v is not None else None
        return None
    if box[0] == "espn":
        _, sp, lg, eid = box
        d = fetch(f"https://site.api.espn.com/apis/site/v2/sports/{sp}/{lg}/summary?event={eid}") or {}
        vals = {}
        for team in (d.get("boxscore") or {}).get("players") or []:
            for grp in team.get("statistics") or []:
                keys = grp.get("keys") or []
                for ath in grp.get("athletes") or []:
                    if last_first(ath.get("athlete", {}).get("displayName", "")) != want:
                        continue
                    for k, v in zip(keys, ath.get("stats") or []):
                        vals[f"{grp.get('name', '')}.{k}"] = v
        if not vals:
            return None

        def g(*names):
            for n in names:
                for k, v in vals.items():
                    if k.endswith("." + n) or k == n:
                        try:
                            return float(str(v).split("-")[0].split("/")[0])
                        except ValueError:
                            return None
            return None
        m = {"passing_yards": lambda: g("passingYards"), "rushing_yards": lambda: g("rushingYards"),
             "receiving_yards": lambda: g("receivingYards"), "receptions": lambda: g("receptions"),
             "passing_tds": lambda: g("passingTouchdowns"), "rushing_attempts": lambda: g("rushingAttempts"),
             "points": lambda: g("points"), "rebounds": lambda: g("rebounds"), "assists": lambda: g("assists"),
             "threes": lambda: g("threePointFieldGoalsMade-threePointFieldGoalsAttempted"),
             "steals": lambda: g("steals"), "blocks": lambda: g("blocks")}
        if stat in ("pra", "points_rebounds_assists"):
            parts = [g("points"), g("rebounds"), g("assists")]
            return sum(parts) if None not in parts else None
        if stat in ("rush_rec_yards", "rushing_receiving_yards"):
            r, c = g("rushingYards"), g("receivingYards")
            return (r or 0) + (c or 0) if (r is not None or c is not None) else None
        f = m.get(stat)
        return f() if f else None
    return None


def settle(b, game):
    """(status, final_score) or (None, reason) when it can't be settled with certainty."""
    if game["status"] == "void":
        return "void", game["label"] + " (postponed or cancelled)"
    if game["status"] == "needs_review":
        return None, "went to extra time: settle on the 90-minute score by hand"
    if game["status"] != "final":
        return None, "not final yet"
    kind, sel, line = kind_of(b), sel_of(b), line_of(b)
    team = (b.get("input") or {}).get("team") or b.get("team")
    if kind.startswith("player_"):
        player = b.get("player") or (b.get("input") or {}).get("player")
        if not player:
            return None, "player prop without a player name"
        v = player_stat(game, player, kind, sport_key(b))
        if v is None:
            return None, f"couldn't find {player}'s {kind[7:]} in the box score (did not play?)"
        res = combine([one((v - ln) if sel == "over" else (ln - v)) for ln in split_line(line)])
        return res, f"{game['label']} · {player} {v:g} {kind[7:].replace('_', ' ')}"
    h, a = game["home"], game["away"]
    if kind.endswith("_f5"):
        if not game.get("f5"):
            return None, "no inning-by-inning score"
        h, a = game["f5"]
    if h is None or a is None:
        return None, "no score"
    res = settle_scores(kind, sel, line, h, a, team)
    if res is None:
        return None, f"don't know how to settle market {kind!r}"
    return res, game["label"] + (" after 5" if kind.endswith("_f5") else "")


def result_units(status, units, odds):
    w = odds - 1
    return round({"won": units * w, "half_won": units * w / 2, "lost": -units, "half_lost": -units / 2}.get(status, 0.0), 2)


# ---------------------------------------------------------------- the run

def due(b, now):
    if str(b.get("status") or "pending").lower() != "pending" or not b.get("start_time"):
        return False
    try:
        st = dt.datetime.fromisoformat(str(b["start_time"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    mins = MIN_MINUTES.get(sport_key(b), 150)
    if kind_of(b).endswith("_f5"):
        mins = 90
    return now >= st + dt.timedelta(minutes=mins)


def closing_line(pid, key):
    feed = os.environ.get("FEED_DIR") or os.path.join(ROOT, "..", "feed")
    if not os.path.isdir(os.path.join(feed, "odds")):
        return None
    tmp = os.path.join("/tmp", f"ml_{pid}.json")
    with open(tmp, "w") as f:
        json.dump(db.load(pid), f)
    cmd = [sys.executable, os.path.join(ROOT, "tools", "close_from_feed.py"), feed, tmp] + ([] if key == "main" else ["--backup", key])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    for line in reversed(r.stdout.strip().splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


def journal_add(lines_by_date):
    path = os.path.join(ROOT, "notes", "journal.md")
    try:
        with open(path) as f:
            text = f.read()
    except FileNotFoundError:
        text = "# Journal\n"
    for day in sorted(lines_by_date, reverse=True):
        block = "\n".join(lines_by_date[day])
        head = f"## {day}"
        if head in text:
            i = text.index(head) + len(head)
            text = text[:i] + "\n" + block + text[i:]
        else:
            # newest day first, after the format example
            m = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2})$", text, re.M))
            later = [x for x in m if x.group(1) < day and not x.group(1).startswith("YYYY")]
            pos = later[0].start() if later else len(text)
            text = text[:pos].rstrip("\n") + f"\n\n{head}\n{block}\n\n" + text[pos:].lstrip("\n")
    with open(path, "w") as f:
        f.write(text.rstrip("\n") + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", help="pretend it's this ISO time (tests)")
    a = ap.parse_args(argv)
    now = dt.datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else dt.datetime.now(dt.timezone.utc)
    graded, skipped, journal = [], [], {}
    for pid, doc in db.all_docs():
        entries = [("main", doc)] + [(c.get("key"), c) for c in doc.get("card") or []] + [(c.get("key"), c) for c in doc.get("backups") or []]
        changed = False
        for key, b in entries:
            if not due(b, now):
                continue
            g = find_game(b)
            if not g:
                skipped.append(f"{pid} {b.get('bet')}: game not found in the score feed")
                continue
            status, score = settle(b, g)
            if not status:
                if score != "not final yet":
                    skipped.append(f"{pid} {b.get('bet')}: {score}")
                continue
            b.update(status=status, final_score=score,
                     result_units=result_units(status, float(b.get("units") or 1), float(b.get("odds_decimal") or 2)),
                     graded_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
            changed = True
            graded.append(f"{pid} {b.get('bet')}: {status.upper()} ({score})")
            tag = ", ".join(x for x in (b.get("sport"), b.get("angle"), b.get("confidence")) if x)
            journal.setdefault(str(doc.get("date") or pid[:10]), []).append(
                f"- {status.upper().replace('_', ' ')} | {b.get('bet')} ({tag}) | {score} | (review pending)")
        if changed and not a.dry_run:
            db.save(pid, doc)
            # closing lines for main markets, now that the result is in
            for key, b in entries:
                if b.get("status") in ("won", "lost", "push", "half_won", "half_lost") and not b.get("close"):
                    c = closing_line(pid, key)
                    if c and isinstance(c, dict) and c.get("odds_decimal"):
                        b["close"] = c
            db.save(pid, doc)
    if journal and not a.dry_run:
        journal_add(journal)
    for line in graded:
        print("GRADED", line)
    for line in skipped:
        print("PENDING", line)
    if not graded and not skipped:
        print("Nothing to grade.")
    if a.dry_run:
        print("(dry run: nothing written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
