#!/usr/bin/env python3
"""
Replay past NHL seasons through the goals model and tune its settings.

    python3 tools/backtest/nhl.py <feed dir> [--tune] [--out report.json]

For every regular-season game it builds the inputs exactly as the daily run would have
the morning of that game (this season's 5v5 expected goals so far, blended with last
season; last season's GSAx for the starting goalie) and prices the moneyline (overtime
and shootout included) and the 5.5 and 6.5 totals. It reports log loss (lower is better)
against a no-skill baseline and a calibration table. --tune searches the settings one at a
time (two passes) and prints the best set. Nothing here sees the game being predicted.
"""

import argparse
import copy
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "model"))
import pricing as P  # noqa: E402

PREV_CODE = {"UTA": "ARI"}  # Utah took over Arizona's roster in 2024-25

DEFAULTS = {"k_games": 25.0, "prev_regress": 1.0, "gsax_weight": 1.0, "gsax_prior_h": 25.0,
            "home_mult": 1.04, "away_mult": 0.975, "league_reg_goals": 3.03, "situation": "5", "ot_home_win": 0.52}
GRID = {"k_games": [8, 15, 25, 40, 70], "prev_regress": [0.4, 0.6, 0.8, 1.0], "gsax_weight": [0.0, 0.25, 0.5, 0.75, 1.0],
        "home_mult": [1.0, 1.02, 1.04, 1.06, 1.08], "away_mult": [0.96, 0.975, 0.99, 1.0], "league_reg_goals": [2.9, 2.97, 3.03, 3.1],
        "situation": ["5", "A"]}


def ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def load(feed):
    with open(os.path.join(feed, "backtest", "nhl.json")) as f:
        return json.load(f)


def prepare(data):
    """Per team-season chronological game rows, league averages by season, and the list of games to predict."""
    by_ts = defaultdict(list)
    league = defaultdict(lambda: defaultdict(float))
    for r in data["team_games"]:
        if not r.get("ice5"):
            continue
        by_ts[(r["t"], r["s"])].append(r)
        L = league[r["s"]]
        for k in ("ice5", "xgf5", "iceA", "xgfA", "gfA"):
            L[k] += r.get(k, 0) or 0
        L["n"] += 1
    for v in by_ts.values():
        v.sort(key=lambda r: (str(r["d"]), r["g"]))
    lg = {s: {"xg60_5": L["xgf5"] / L["ice5"] * 60, "xg60_A": L["xgfA"] / max(L["iceA"], 1) * 60, "gpg": L["gfA"] / L["n"]}
          for s, L in league.items()}
    games = []
    for gid, res in data["results"].items():
        if res.get("hs") is None or res.get("as") is None:
            continue
        games.append(dict(res, gid=gid))
    games.sort(key=lambda g: (g["date"], g["gid"]))
    return by_ts, lg, games


def rates_before(rows, date, sfx):
    gp = ice = xf = xa = 0.0
    for r in rows:
        if str(r["d"]) >= date.replace("-", ""):
            break
        gp += 1
        ice += r.get(f"ice{sfx}", 0) or 0
        xf += r.get(f"xgf{sfx}", 0) or 0
        xa += r.get(f"xga{sfx}", 0) or 0
    return gp, ice, xf, xa


def season_rates(rows, sfx):
    ice = sum(r.get(f"ice{sfx}", 0) or 0 for r in rows)
    if ice <= 0:
        return None
    return (sum(r.get(f"xgf{sfx}", 0) or 0 for r in rows) / ice * 60, sum(r.get(f"xga{sfx}", 0) or 0 for r in rows) / ice * 60)


class Replay:
    def __init__(self, data):
        self.data = data
        self.by_ts, self.lg, self.games = prepare(data)
        self.cache = {}

    def team_inputs(self, team, season, date, prm):
        sfx = prm["situation"]
        key = (team, season, date, sfx, prm["k_games"], prm["prev_regress"])
        if key in self.cache:
            return self.cache[key]
        mean = self.lg.get(season - 1, self.lg.get(season))[f"xg60_{sfx}"]
        prev_rows = self.by_ts.get((team, season - 1)) or self.by_ts.get((PREV_CODE.get(team, team), season - 1)) or []
        prev = season_rates(prev_rows, sfx) or (mean, mean)
        prev = tuple(mean + prm["prev_regress"] * (x - mean) for x in prev)
        gp, ice, xf, xa = rates_before(self.by_ts.get((team, season), []), date, sfx)
        if gp and ice > 0:
            w = gp / (gp + prm["k_games"])
            cur = (xf / ice * 60, xa / ice * 60)
            out = tuple(w * c + (1 - w) * p for c, p in zip(cur, prev))
        else:
            out = prev
        out = tuple(x / mean for x in out)  # relative to league average
        self.cache[key] = out
        return out

    def goalie(self, season, starter, prm):
        if not starter or not starter.get("id"):
            return 0.0
        g = self.data["goalie_seasons"].get(str(season - 1), {}).get(str(starter["id"]))
        if not g:
            return 0.0
        return g["gsax"] / (g["hours"] + prm["gsax_prior_h"])

    def run(self, prm, seasons=None):
        cfg = P.load_config()
        cfg = copy.deepcopy(cfg)
        lgx = 2.5
        cfg["nhl"].update({"league_xg60": lgx, "league_reg_goals": prm["league_reg_goals"], "gsax_weight": prm["gsax_weight"],
                           "home_mult": prm["home_mult"], "away_mult": prm["away_mult"], "ot_home_win": prm["ot_home_win"]})
        tot = defaultdict(float)
        n = 0
        calib = defaultdict(lambda: [0, 0.0, 0])
        for g in self.games:
            s = g["s"]
            if seasons and s not in seasons:
                continue
            st = self.data["starters"].get(g["gid"], {})
            h = self.team_inputs(g["home"], s, g["date"], prm)
            a = self.team_inputs(g["away"], s, g["date"], prm)
            inp = {"home": {"xgf60": h[0] * lgx, "xga60": h[1] * lgx, "goalie_gsax60": self.goalie(s, st.get("home"), prm)},
                   "away": {"xgf60": a[0] * lgx, "xga60": a[1] * lgx, "goalie_gsax60": self.goalie(s, st.get("away"), prm)}}
            d = P.nhl_dist(inp, cfg)
            p_home = P.breakeven_prob(P.evaluate(d, "moneyline", "home", None))
            p_o55 = P.breakeven_prob(P.evaluate(d, "total", "over", 5.5))
            p_o65 = P.breakeven_prob(P.evaluate(d, "total", "over", 6.5))
            y_home = 1 if g["hs"] > g["as"] else 0
            total = g["hs"] + g["as"]
            tot["ml"] += ll(p_home, y_home)
            tot["o55"] += ll(p_o55, 1 if total > 5.5 else 0)
            tot["o65"] += ll(p_o65, 1 if total > 6.5 else 0)
            tot["y_home"] += y_home
            tot["y_o55"] += total > 5.5
            tot["y_o65"] += total > 6.5
            tot["p_home"] += p_home
            tot["p_o55"] += p_o55
            b = min(int(p_home * 10), 9)
            calib[b][0] += 1
            calib[b][1] += p_home
            calib[b][2] += y_home
            n += 1
        if not n:
            return None
        res = {k: tot[k] / n for k in ("ml", "o55", "o65")}
        res["n"] = n
        # no-skill baselines: constant home-win and over rates
        for k, y in (("ml", "y_home"), ("o55", "y_o55"), ("o65", "y_o65")):
            r = tot[y] / n
            res[f"{k}_base"] = ll(r, 1) * r + ll(r, 0) * (1 - r)
        res["home_rate"] = tot["y_home"] / n
        res["avg_p_home"] = tot["p_home"] / n
        res["over55_rate"] = tot["y_o55"] / n
        res["avg_p_over55"] = tot["p_o55"] / n
        res["calibration"] = [{"bucket": f"{b * 10}-{b * 10 + 10}%", "games": c[0], "predicted": round(c[1] / c[0], 3),
                               "actual": round(c[2] / c[0], 3)} for b, c in sorted(calib.items()) if c[0]]
        return res


def score(r):
    return r["ml"] + 0.5 * (r["o55"] + r["o65"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("feed")
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rp = Replay(load(a.feed))
    seasons = sorted({g["s"] for g in rp.games})
    print(f"{len(rp.games)} games, seasons {seasons}")
    base = rp.run(DEFAULTS)
    print(f"Current settings: moneyline log loss {base['ml']:.4f} (no-skill {base['ml_base']:.4f}), "
          f"over 5.5 {base['o55']:.4f} ({base['o55_base']:.4f}), over 6.5 {base['o65']:.4f} ({base['o65_base']:.4f})")
    best, best_r = dict(DEFAULTS), base
    if a.tune:
        for pas in range(2):
            for k, vals in GRID.items():
                for v in vals:
                    trial = dict(best, **{k: v})
                    r = rp.run(trial)
                    if score(r) < score(best_r) - 1e-6:
                        best, best_r = trial, r
                print(f"  pass {pas + 1}, {k}: {best[k]}  (score {score(best_r):.4f})")
        print("Best settings:", json.dumps(best))
        print(f"Tuned: moneyline {best_r['ml']:.4f}, over 5.5 {best_r['o55']:.4f}, over 6.5 {best_r['o65']:.4f}")
        # out-of-sample check: tune on all but the last season, test on the last
        last = seasons[-1]
        train = [s for s in seasons if s != last]
        b2, r2 = dict(DEFAULTS), rp.run(DEFAULTS, train)
        for _ in range(2):
            for k, vals in GRID.items():
                for v in vals:
                    t = dict(b2, **{k: v})
                    r = rp.run(t, train)
                    if score(r) < score(r2) - 1e-6:
                        b2, r2 = t, r
        test_cur, test_tuned = rp.run(DEFAULTS, [last]), rp.run(b2, [last])
        print(f"Out of sample ({last}): current {score(test_cur):.4f} vs tuned-on-earlier-seasons {score(test_tuned):.4f} "
              f"(moneyline {test_cur['ml']:.4f} -> {test_tuned['ml']:.4f})")
        best_r["oos"] = {"season": last, "current": test_cur, "tuned": test_tuned, "params_train": b2}
    print("Calibration (home win):")
    for c in best_r["calibration"]:
        print(f"  {c['bucket']:>8}: {c['games']:5d} games, predicted {c['predicted']:.3f}, actual {c['actual']:.3f}")
    if a.out:
        with open(a.out, "w") as f:
            json.dump({"current": base, "best_params": best, "best": best_r}, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
