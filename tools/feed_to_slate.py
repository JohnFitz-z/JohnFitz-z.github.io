#!/usr/bin/env python3
"""
Build today's slate.json from the data feed (the `feed` branch) instead of scraping.

    python3 tools/feed_to_slate.py <feed dir> --date 2026-10-09 --out /tmp/ml/slate.json
        [--after 2026-10-09T10:00:00-03:00] [--goalies goalies.json] [--snapshot morning]

- Every game in the odds snapshot that starts on --date (Atlantic) after --after, with
  moneyline, spread and total from every book (Pinnacle and Betfair included).
- NHL model inputs from MoneyPuck: 5v5 xGF/60 and xGA/60, this season blended with last
  season by games played and scaled to the engine's league average. Starting goalies come
  from --goalies ({"Bruins": "Jeremy Swayman", ...}); their GSAx/60 is shrunk toward zero.
- MLB model inputs from the MLB Stats API: probable starters' FIP, team OPS+ as the
  offence, team FIP as the bullpen, and an approximate park factor.
- Other sports get no model_inputs here; add ratings per METHOD.md during research.
Prints a summary of what's covered and what still needs inputs.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import pricing as P  # noqa: E402

TZ = ZoneInfo("America/Halifax")

BOOK_NAMES = {"pinnacle": "Pinnacle", "betfair_ex_eu": "Betfair Exchange", "betfair_ex_uk": "Betfair Exchange",
              "matchbook": "Matchbook", "draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM",
              "williamhill_us": "Caesars", "betrivers": "BetRivers", "fanatics": "Fanatics", "betonlineag": "BetOnline",
              "bovada": "Bovada", "lowvig": "LowVig", "mybookieag": "MyBookie", "betus": "BetUS", "williamhill": "William Hill",
              "onexbet": "1xBet", "sport888": "888sport", "betsson": "Betsson", "marathonbet": "Marathonbet",
              "unibet_se": "Unibet", "unibet_nl": "Unibet NL", "unibet_fr": "Unibet FR", "unibet_it": "Unibet IT",
              "betvictor": "BetVictor", "coolbet": "Coolbet", "everygame": "Everygame", "nordicbet": "NordicBet",
              "tipico_de": "Tipico", "gtbets": "GTbets", "betanysports": "BetAnySports", "suprabets": "Suprabets"}

MULTI_WORD = ("Red Sox", "White Sox", "Blue Jays", "Maple Leafs", "Golden Knights", "Blue Jackets", "Red Wings",
              "Trail Blazers", "Football Team")

# Approximate multi-year run park factors (100 = neutral), keyed by MLB nickname.
PARK = {"Rockies": 112, "Reds": 105, "Red Sox": 104, "Royals": 103, "Diamondbacks": 102, "Athletics": 103, "Phillies": 101,
        "Angels": 101, "Rangers": 100, "Braves": 100, "Twins": 100, "Cubs": 100, "Brewers": 100, "Blue Jays": 100,
        "Yankees": 100, "Nationals": 100, "White Sox": 100, "Orioles": 99, "Astros": 99, "Dodgers": 99, "Tigers": 99,
        "Pirates": 98, "Cardinals": 98, "Guardians": 98, "Rays": 98, "Marlins": 97, "Mets": 96, "Padres": 96, "Giants": 96,
        "Mariners": 93}


def nickname(full, sport):
    if sport in ("NCAAF", "NCAAB", "Soccer"):
        return full
    for m in MULTI_WORD:
        if full.endswith(m):
            return m
    if full in ("Athletics", "Oakland Athletics", "Sacramento Athletics"):
        return "Athletics"
    return full.split()[-1]


def load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def markets_for(ev):
    """Group book prices into slate markets (moneyline, spread by home line, total by line)."""
    ml, spreads, totals = [], {}, {}
    seen = set()
    for key, b in ev["books"].items():
        name = BOOK_NAMES.get(key, b.get("title") or key)
        if name in seen:
            continue
        seen.add(name)
        if "h2h" in b:
            ml.append({"book": name, "prices": b["h2h"]})
        if "spreads" in b:
            spreads.setdefault(float(b["spreads"]["line"]), []).append(
                {"book": name, "prices": {"home": b["spreads"]["home"], "away": b["spreads"]["away"]}})
        if "totals" in b:
            totals.setdefault(float(b["totals"]["line"]), []).append(
                {"book": name, "prices": {"over": b["totals"]["over"], "under": b["totals"]["under"]}})
    out = []
    if len(ml) >= 2:
        out.append({"market": "moneyline", "books": ml})
    for line, books in sorted(spreads.items(), key=lambda kv: -len(kv[1])):
        if len(books) >= 2:
            out.append({"market": "spread", "line": line, "books": books})
    for line, books in sorted(totals.items(), key=lambda kv: -len(kv[1])):
        if len(books) >= 2:
            out.append({"market": "total", "line": line, "books": books})
    return out


# ------------------------------------------------------------------ NHL


def nhl_inputs_factory(stats, cfg, goalies):
    if not stats:
        return None
    cur = str(stats.get("current_season"))
    prev = str(int(cur) - 1)
    tc, tp = stats["teams"].get(cur, {}), stats["teams"].get(prev, {})
    # Backtest 2022-26 (tools/backtest/nhl.py): all-situation expected goals predict better than 5v5,
    # last season should be regressed 40% toward the league average, and this season takes over at 25 games.
    def rate(team, k):
        return team.get(f"{k}_all", team[k])

    def lg_mean(teams):
        vals = [rate(t, k) for t in teams.values() for k in ("xgf60", "xga60")]
        return sum(vals) / len(vals) if vals else None

    mp = lg_mean(tp)
    blended = {}
    for code in set(tc) | set(tp):
        c, p = tc.get(code), tp.get(code)
        prior = {k: mp + 0.6 * (rate(p, k) - mp) for k in ("xgf60", "xga60")} if p and mp else None
        if c and prior:
            w = c["gp"] / (c["gp"] + 25.0)
            blended[code] = {k: w * rate(c, k) + (1 - w) * prior[k] for k in ("xgf60", "xga60")}
        elif prior:
            blended[code] = prior
        elif c:
            blended[code] = {k: rate(c, k) for k in ("xgf60", "xga60")}
    if not blended:
        return None
    mean = sum(v["xgf60"] + v["xga60"] for v in blended.values()) / (2 * len(blended))
    scale = cfg["nhl"]["league_xg60"] / mean
    gc, gp = stats["goalies"].get(cur, {}), stats["goalies"].get(prev, {})

    def goalie_gsax60(name):
        if not name:
            return 0.0, "no starter given"
        key = next((n for n in set(gc) | set(gp) if n.lower() == name.lower()), None)
        if not key:
            key = next((n for n in set(gc) | set(gp) if n.lower().split()[-1] == name.lower().split()[-1]), None)
        if not key:
            return 0.0, f"{name}: no data"
        c, p = gc.get(key, {}), gp.get(key, {})
        gsax = c.get("gsax", 0) + 0.7 * p.get("gsax", 0)
        hours = c.get("hours", 0) + 0.7 * p.get("hours", 0)
        return round(gsax / (hours + 25.0), 3), f"{key}: GSAx {gsax:+.1f} over {hours:.0f}h (shrunk)"

    tmap = stats.get("team_map", {})

    def build(ev):
        h, a = tmap.get(ev["home"]), tmap.get(ev["away"])
        if not h or not a or h[0] not in blended or a[0] not in blended:
            return None, "team not in MoneyPuck data"
        hn, an = h[1], a[1]
        hg, hnote = goalie_gsax60(goalies.get(hn) or goalies.get(ev["home"]))
        ag, anote = goalie_gsax60(goalies.get(an) or goalies.get(ev["away"]))
        mi = {"home": {"xgf60": round(blended[h[0]]["xgf60"] * scale, 3), "xga60": round(blended[h[0]]["xga60"] * scale, 3), "goalie_gsax60": hg},
              "away": {"xgf60": round(blended[a[0]]["xgf60"] * scale, 3), "xga60": round(blended[a[0]]["xga60"] * scale, 3), "goalie_gsax60": ag}}
        return mi, f"goalies: {hnote}; {anote}"

    return build


# ------------------------------------------------------------------ MLB


def fip(line, cfip):
    if not line or line.get("ip", 0) <= 0:
        return None
    return (13 * line["hr"] + 3 * (line["bb"] + line["hbp"]) - 2 * line["k"]) / line["ip"] + cfip


def mlb_inputs_factory(stats, cfg):
    if not stats:
        return None
    season = str(stats["season"])
    teams_cur, teams_prev = stats["teams"].get(season, {}), stats["teams"].get(str(int(season) - 1), {})
    lg_era = cfg["mlb"]["league_era"]

    def league(teams):
        if not teams:
            return None
        n = len(teams)
        tot = {k: sum(t["pitching"][k] for t in teams.values()) for k in ("ip", "hr", "bb", "hbp", "k")}
        cf = lg_era - (13 * tot["hr"] + 3 * (tot["bb"] + tot["hbp"]) - 2 * tot["k"]) / max(tot["ip"], 1)
        return {"obp": sum(t["obp"] for t in teams.values()) / n, "slg": sum(t["slg"] for t in teams.values()) / n, "cfip": cf}

    lc, lp = league(teams_cur), league(teams_prev)

    def team_line(name):
        c, p = teams_cur.get(name), teams_prev.get(name)
        out = {}
        parts = []
        if c and lc:
            parts.append((c["g"] / (c["g"] + 30.0), c, lc))
        if p and lp:
            parts.append((1 - (parts[0][0] if parts else 0), p, lp))
        if not parts:
            return None
        wsum = sum(w for w, _, _ in parts) or 1
        out["off"] = sum(w * 100 * (t["obp"] / l["obp"] + t["slg"] / l["slg"] - 1) for w, t, l in parts) / wsum
        pens = [(w, fip(t["pitching"], l["cfip"])) for w, t, l in parts]
        pens = [(w, v) for w, v in pens if v is not None]
        out["pen"] = sum(w * v for w, v in pens) / sum(w for w, _ in pens) if pens else lg_era
        return out

    def starter(pid):
        p = stats["pitchers"].get(str(pid)) if pid else None
        if not p:
            return None, None
        c, q = p.get(season), p.get(str(int(season) - 1))
        vals = []
        if c and lc:
            w = c["ip"] / (c["ip"] + 50.0)
            vals.append((w, fip(c, lc["cfip"]), c))
        if q and lp:
            vals.append((1 - (vals[0][0] if vals else 0), fip(q, lp["cfip"]), q))
        vals = [(w, v, l) for w, v, l in vals if v is not None and w > 0]
        if not vals:
            return None, None
        wsum = sum(w for w, _, _ in vals)
        est = sum(w * v for w, v, _ in vals) / wsum
        main = vals[0][2]
        ip_per_start = (main["ip"] / main["gs"]) if main.get("gs") else 5.0
        # Regress toward league average for small samples
        total_ip = sum(l["ip"] for _, _, l in vals)
        est = (est * total_ip + lg_era * 40) / (total_ip + 40)
        return round(est, 2), round(min(max(ip_per_start, 4.0), 6.5), 1)

    def build(ev):
        g = next((x for x in stats["games"] if x["home"]["team"] == ev["home"] and x["away"]["team"] == ev["away"]
                  and abs((P_iso(x["start"]) - P_iso(ev["commence_time"])).total_seconds()) < 6 * 3600), None)
        if not g:
            return None, "game not in MLB schedule data"
        ht, at = team_line(ev["home"]), team_line(ev["away"])
        hs, hip = starter(g["home"]["pitcher_id"])
        as_, aip = starter(g["away"]["pitcher_id"])
        if not ht or not at:
            return None, "team stats missing"
        if hs is None or as_ is None:
            return None, f"probable starter missing ({g['away']['pitcher']} vs {g['home']['pitcher']})"
        mi = {"home": {"off": round(ht["off"], 1), "opp_sp": as_, "opp_sp_ip": aip, "opp_pen": round(at["pen"], 2)},
              "away": {"off": round(at["off"], 1), "opp_sp": hs, "opp_sp_ip": hip, "opp_pen": round(ht["pen"], 2)},
              "park": PARK.get(nickname(ev["home"], "MLB"), 100)}
        return mi, f"starters: {g['away']['pitcher']} vs {g['home']['pitcher']}"

    return build


def P_iso(s):
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))


# ------------------------------------------------------------------ main


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("feed")
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--after", help="only games starting after this ISO time (default: now)")
    ap.add_argument("--goalies", help='JSON {"Bruins": "Jeremy Swayman", ...}')
    ap.add_argument("--snapshot", default="latest", help="latest, morning or afternoon")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    cfg = P.load_config(a.config)
    snap_path = os.path.join(a.feed, "odds", a.date, f"{a.snapshot}.json") if a.snapshot != "latest" else os.path.join(a.feed, "odds", "latest.json")
    snap = load(snap_path)
    if not snap:
        print(f"ERROR: no odds snapshot at {snap_path}")
        return 1
    after = P_iso(a.after) if a.after else dt.datetime.now(dt.timezone.utc)
    goalies = load(a.goalies, {}) if a.goalies else {}
    nhl = nhl_inputs_factory(load(os.path.join(a.feed, "stats", "nhl.json")), cfg, goalies)
    mlb = mlb_inputs_factory(load(os.path.join(a.feed, "stats", "mlb", "latest.json")), cfg)

    games, needs, sharp = [], [], 0
    for ev in snap["events"]:
        t = P_iso(ev["commence_time"])
        if t.astimezone(TZ).date().isoformat() != a.date or t <= after:
            continue
        sport = ev["sport"]
        mk = markets_for(ev)
        if not mk:
            continue
        hn, an = nickname(ev["home"], sport), nickname(ev["away"], sport)
        g = {"id": f"{sport.lower()}-{re.sub(r'[^a-z0-9]+', '', an.lower())[:12]}-{re.sub(r'[^a-z0-9]+', '', hn.lower())[:12]}",
             "sport": sport, "league": ev.get("league") or sport, "home": hn, "away": an,
             "start_time": t.astimezone(TZ).isoformat(), "feed_event_id": ev["id"], "markets": mk}
        if any(k in ev["books"] for k in ("pinnacle", "betfair_ex_eu", "betfair_ex_uk")):
            sharp += 1
        note = None
        if sport == "NHL" and nhl:
            mi, note = nhl(ev)
            if mi:
                g["model_inputs"] = mi
        elif sport == "MLB" and mlb:
            mi, note = mlb(ev)
            if mi:
                g["model_inputs"] = mi
        if note:
            g["inputs_note"] = note
        if "model_inputs" not in g:
            needs.append(f"{sport}: {an} @ {hn}" + (f" ({note})" if note else ""))
        games.append(g)
    games.sort(key=lambda g: g["start_time"])
    slate = {"date": a.date, "source": {"odds": snap.get("fetched_at"), "snapshot": os.path.relpath(snap_path, a.feed)}, "games": games}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(slate, f, indent=1, ensure_ascii=False)
    by_sport = {}
    for g in games:
        by_sport.setdefault(g["sport"], [0, 0])
        by_sport[g["sport"]][0] += 1
        by_sport[g["sport"]][1] += "model_inputs" in g
    print(f"Wrote {len(games)} games to {a.out} (odds fetched {snap.get('fetched_at')}); {sharp} have Pinnacle or Betfair prices.")
    for s, (n, m) in sorted(by_sport.items()):
        print(f"  {s}: {n} games, {m} with model inputs")
    if needs:
        print("Need model inputs (add per METHOD.md):")
        for x in needs:
            print("  -", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
