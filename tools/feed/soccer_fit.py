"""
Fair prices for every soccer goal market from a bookmaker's main markets.

Fit each team's expected goals so the model reproduces a book's margin-free full-time
result (1X2) and main over/under, then price any other line (alternate totals, Asian
handicaps, team totals, both teams to score, draw no bet, double chance, clean sheets,
odd/even) from the same scoreline distribution (Poisson with the Dixon-Coles low-score
correction used by the main engine). Standard library only.
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "model"))
import pricing as P  # noqa: E402


def devig(prices):
    """{outcome: decimal} -> {outcome: margin-free probability} (power method)."""
    keys = sorted(prices)
    return dict(zip(keys, P.remove_vig([prices[k] for k in keys], "power")))


def _dist(lh, la, cfg):
    return P.soccer_dist({"home_goals": lh, "away_goals": la}, cfg)


def _be(d, kind, sel, line=None, team=None):
    o = P.evaluate(d, kind, sel, line, team)
    return P.breakeven_prob(o) if o else None


def fit(p_home, p_away, p_over, total_line, cfg, start=(1.4, 1.1)):
    """Expected goals (home, away) matching P(home win), P(away win) and P(over total_line).
    Returns (lh, la, dist, rms_error)."""
    x = [math.log(start[0]), math.log(start[1])]
    targets = [p_home, p_away, p_over]

    def resid(v):
        d = _dist(math.exp(v[0]), math.exp(v[1]), cfg)
        got = [_be(d, "moneyline", "home"), _be(d, "moneyline", "away"), _be(d, "total", "over", total_line)]
        return [g - t for g, t in zip(got, targets)], d

    r, d = resid(x)
    for _ in range(15):
        eps = 1e-3
        cols = []
        for j in range(2):
            v = list(x)
            v[j] += eps
            rj, _ = resid(v)
            cols.append([(a - b) / eps for a, b in zip(rj, r)])
        # normal equations for a 3x2 Jacobian (columns cols[0], cols[1])
        a11 = sum(c * c for c in cols[0])
        a12 = sum(c0 * c1 for c0, c1 in zip(cols[0], cols[1]))
        a22 = sum(c * c for c in cols[1])
        b1 = -sum(c * e for c, e in zip(cols[0], r))
        b2 = -sum(c * e for c, e in zip(cols[1], r))
        det = a11 * a22 - a12 * a12
        if abs(det) < 1e-12:
            break
        dx = [(b1 * a22 - b2 * a12) / det, (a11 * b2 - a12 * b1) / det]
        step = max(abs(dx[0]), abs(dx[1]))
        if step > 0.5:
            dx = [v * 0.5 / step for v in dx]
        x = [min(max(x[0] + dx[0], math.log(0.05)), math.log(6)), min(max(x[1] + dx[1], math.log(0.05)), math.log(6))]
        r, d = resid(x)
        if step < 1e-6:
            break
    rms = math.sqrt(sum(e * e for e in r) / 3)
    return math.exp(x[0]), math.exp(x[1]), d, rms


def anchor_targets(markets, meta):
    """From one book's soccer markets ({market_id: {outcome_id: price}}), the margin-free targets for
    the fit: P(home), P(away) from the full-time result and P(over) at the most balanced main total."""
    res = tot = None
    for mid, outs in markets.items():
        m = meta.get(mid)
        if not m or m.get("period") != "fulltime":
            continue
        if m["type"] == "1x2" and len(outs) == 3:
            names = {m["outcomes"].get(o): o for o in outs}
            if {"1", "X", "2"} <= set(names):
                f = devig(outs)
                res = (f[names["1"]], f[names["2"]], outs)
        elif m["type"] == "totals" and len(outs) == 2 and m.get("line") is not None:
            names = {m["outcomes"].get(o): o for o in outs}
            if {"Over", "Under"} <= set(names):
                f = devig(outs)
                p_over = f[names["Over"]]
                if tot is None or abs(p_over - 0.5) < abs(tot[0] - 0.5):
                    tot = (p_over, float(m["line"]), mid)
    if not res or not tot:
        return None
    return {"p_home": res[0], "p_away": res[1], "p_over": tot[0], "line": tot[1], "total_market": tot[2]}


def _prob_outcome(p):
    return {"win": p, "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "loss": 1 - p}


def price_market(dist, m, outcome_name):
    """Outcome probabilities {win, half_win, push, half_loss, loss} for one soccer goal market outcome,
    or None if the market isn't modelled."""
    t, line, n = m["type"], m.get("line"), str(outcome_name)
    if m.get("period") != "fulltime":
        return None
    if t == "1x2":
        sel = {"1": "home", "X": "draw", "2": "away"}.get(n)
        return P.evaluate(dist, "moneyline", sel, None) if sel else None
    if t == "drawnobet":
        sel = {"1": "home", "2": "away"}.get(n)
        return P.evaluate(dist, "draw_no_bet", sel, None) if sel else None
    if t == "spreads" and line is not None:  # Asian handicap; line is the home team's
        if n == "1":
            return P.evaluate(dist, "spread", "home", float(line))
        if n == "2":
            return P.evaluate(dist, "spread", "away", -float(line))
        return None
    if t == "totals" and line is not None:
        sel = {"Over": "over", "Under": "under"}.get(n)
        return P.evaluate(dist, "total", sel, float(line)) if sel else None
    if t in ("teamtotals-team1", "teamtotals-team2") and line is not None:
        sel = {"Over": "over", "Under": "under"}.get(n)
        team = "home" if t.endswith("team1") else "away"
        return P.evaluate(dist, "team_total", sel, float(line), team) if sel else None
    if t == "bothteamsscore":
        sel = {"Yes": "yes", "No": "no"}.get(n)
        return P.evaluate(dist, "btts", sel, None) if sel else None
    mat = dist.matrix or {}
    if t == "doublechance":
        ph = sum(p for (h, a), p in mat.items() if h > a)
        pd = sum(p for (h, a), p in mat.items() if h == a)
        pa = 1 - ph - pd
        p = {"1X": ph + pd, "X1": ph + pd, "12": ph + pa, "21": ph + pa, "2X": pa + pd, "X2": pa + pd}.get(n.replace(" ", ""))
        return _prob_outcome(p) if p is not None else None
    if t in ("toscore-team1", "toscore-team2", "cleansheet-team1", "cleansheet-team2", "wintonil-team1", "wintonil-team2"):
        if n not in ("Yes", "No"):
            return None
        if t == "toscore-team1":
            p = sum(p for (h, a), p in mat.items() if h > 0)
        elif t == "toscore-team2":
            p = sum(p for (h, a), p in mat.items() if a > 0)
        elif t == "cleansheet-team1":
            p = sum(p for (h, a), p in mat.items() if a == 0)
        elif t == "cleansheet-team2":
            p = sum(p for (h, a), p in mat.items() if h == 0)
        elif t == "wintonil-team1":
            p = sum(p for (h, a), p in mat.items() if h > 0 and a == 0)
        else:
            p = sum(p for (h, a), p in mat.items() if a > 0 and h == 0)
        return _prob_outcome(p if n == "Yes" else 1 - p)
    if t == "oddeven":
        p = sum(p for (h, a), p in mat.items() if (h + a) % 2 == 1)
        return _prob_outcome(p if n == "Odd" else 1 - p) if n in ("Odd", "Even") else None
    return None
