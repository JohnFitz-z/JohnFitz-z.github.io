#!/usr/bin/env python3
"""
Morning Line pricing engine.

Turns a shortlist of candidate bets into probabilities, expected value, a
stake and a minimum acceptable price, then ranks them. METHOD.md explains
the inputs; config.json holds every tunable number.

Commands
    python3 model/pricing.py price candidates.json --out priced.json
    python3 model/pricing.py clv --taken 1.75 --selection home --close home=-150 away=+130
    python3 model/pricing.py odds -134

How one candidate is priced
    1. Market     Strip the bookmaker margin from each book's prices and take
                  the median fair probability across books.
    2. Model      Sport-specific score model gives the outcome probabilities
                  for the exact bet, including pushes, extra innings or
                  overtime rules, and NFL key numbers.
    3. Blend      Combine market and model in log-odds space.
    4. Adjust     Add researched factors the model can't see. Each is capped
                  and the total is capped.
    5. Bet        Expected value at the real price, fractional Kelly stake,
                  minimum price, and a growth score used for ranking.

Every probability compared with a price is a break-even probability: the
chance that makes the bet exactly fair once pushes and half results are
accounted for. For a bet that can't push it's simply the win probability,
and the price's own break-even is always 1 / decimal odds.
"""

import argparse
import json
import re
import math
import os
import sys
from statistics import median

HERE = os.path.dirname(os.path.abspath(__file__))
EPS = 1e-12

# ---------------------------------------------------------------- config


def load_config(path=None):
    with open(path or os.path.join(HERE, "config.json")) as f:
        return json.load(f)


# ---------------------------------------------------------------- odds


def american_to_decimal(a):
    a = float(a)
    if -100 < a < 100:
        raise ValueError(f"American odds must be <= -100 or >= +100, got {a}")
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def decimal_to_american(d):
    d = float(d)
    if d <= 1:
        raise ValueError(f"Decimal odds must be above 1, got {d}")
    return int(round((d - 1) * 100)) if d >= 2 else int(round(-100 / (d - 1)))


def to_decimal(price):
    """Read odds in any common form: -134, '+114', 'EVEN', 1.75, '1.75'."""
    if isinstance(price, bool) or price is None:
        raise ValueError(f"Can't read odds: {price!r}")
    if isinstance(price, str):
        s = price.strip().replace("−", "-").replace(" ", "")
        if s.lower() in ("even", "evs", "ev", "pk"):
            return 2.0
        if s[:1] in "+-":
            return american_to_decimal(float(s))
        price = float(s)
    x = float(price)
    if abs(x) >= 100:
        return american_to_decimal(x)
    if x > 1:
        return x
    raise ValueError(f"Can't read odds: {price!r}")


def logit(p):
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


# ---------------------------------------------------------------- margin removal


def remove_vig(decimals, method="power"):
    """Fair probabilities for a complete market (2 or 3 outcomes).

    proportional: scale implied probabilities so they sum to 1.
    power:        find k with sum(p_i ** k) = 1. Takes more margin off long
                  shots than favourites, which matches how books shade prices.
    """
    q = [1 / float(d) for d in decimals]
    s = sum(q)
    if len(q) < 2:
        raise ValueError("Need every outcome of the market to remove the margin")
    if method == "proportional" or abs(s - 1) < 1e-9:
        return [x / s for x in q]
    if method != "power":
        raise ValueError(f"Unknown margin method {method!r}")
    lo, hi = 0.05, 20.0  # sum(q ** k) falls as k rises
    for _ in range(200):
        k = (lo + hi) / 2
        if sum(x ** k for x in q) > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    fair = [x ** k for x in q]
    t = sum(fair)
    return [x / t for x in fair]


def _norm_book(name):
    return re.sub(r"[^a-z]", "", str(name).lower())


def sharp_weight(book, cfg):
    """Weight of a book in the sharp anchor (0 = not a sharp book)."""
    key = _norm_book(book)
    for name, w in (cfg.get("market", {}).get("sharp_books") or {}).items():
        if _norm_book(name) and _norm_book(name) in key:
            return float(w)
    return 0.0


def market_view(c, cfg):
    """Fair (break-even) probability of the selection. When a sharp book (Pinnacle, Betfair
    Exchange, Circa...) prices the market, its margin-free price is the anchor, since sharp
    closing prices are the best public forecast; otherwise the median across books."""
    sel = c["selection"].lower()
    kind = c["market"].lower()
    line = c.get("line")
    method = cfg.get("devig_method", "power")
    rows, fairs, margins, skipped, sharp = [], [], [], [], []
    for b in c.get("market_odds") or []:
        book = b.get("book", "?")
        if line is not None and b.get("line") is not None and abs(float(b["line"]) - float(line)) > 1e-9:
            skipped.append(f"{book} (different line {b['line']})")
            continue
        prices = {str(k).lower(): v for k, v in (b.get("prices") or {}).items()}
        try:
            if kind == "draw_no_bet":
                need = ["home", "draw", "away"]
                decs = [to_decimal(prices[k]) for k in need]
                f3 = remove_vig(decs, method)
                h, a = f3[0], f3[2]
                fair = (h if sel == "home" else a) / (h + a)
                margin = sum(1 / d for d in decs) - 1
            else:
                keys = list(prices.keys())
                if sel not in keys:
                    skipped.append(f"{book} (no {sel} price)")
                    continue
                decs = [to_decimal(prices[k]) for k in keys]
                fair = remove_vig(decs, method)[keys.index(sel)]
                margin = sum(1 / d for d in decs) - 1
        except (KeyError, ValueError) as e:
            skipped.append(f"{book} ({e})")
            continue
        fairs.append(fair)
        margins.append(margin)
        sel_price = prices.get(sel)
        w = sharp_weight(book, cfg)
        rows.append({
            "book": book,
            "price": sel_price,
            "decimal": round(to_decimal(sel_price), 3) if sel_price is not None else None,
            "fair": round(fair, 4),
            "margin": round(margin, 4),
            **({"sharp": True} if w > 0 else {}),
        })
        if w > 0:
            sharp.append((w, fair, book, margin))
    if not fairs:
        return None
    use_sharp = cfg.get("market", {}).get("anchor", "sharp") == "sharp" and sharp
    if use_sharp:
        fair_prob = sum(w * f for w, f, _, _ in sharp) / sum(w for w, _, _, _ in sharp)
        names = ", ".join(dict.fromkeys(b for _, _, b, _ in sharp))
        others = len(rows) - len(sharp)
        detail = (f"{names} (sharp), {method} method, margin {sum(m for *_, m in sharp) / len(sharp) * 100:.1f}%"
                  + (f"; {others} other book{'s' if others != 1 else ''} shown for comparison" if others else ""))
    else:
        fair_prob = median(fairs)
        detail = (f"Median of {len(rows)} book{'s' if len(rows) != 1 else ''}, {method} method, "
                  f"average margin {sum(margins) / len(margins) * 100:.1f}%")
    return {
        "fair_prob": fair_prob,
        "source": "sharp" if use_sharp else "consensus",
        "detail": detail,
        "books": rows,
        "avg_margin": sum(margins) / len(margins),
        "method": method,
        "skipped": skipped,
    }


# ---------------------------------------------------------------- score distributions


def poisson_pmf(lam, kmax):
    lam = max(float(lam), 1e-6)
    p = [math.exp(-lam)]
    for k in range(1, kmax + 1):
        p.append(p[-1] * lam / k)
    p[-1] += max(0.0, 1 - sum(p))
    return p


def negbin_pmf(mu, r, kmax):
    """Negative binomial with mean mu and dispersion r (variance mu + mu^2 / r)."""
    mu = max(float(mu), 1e-6)
    p = r / (r + mu)
    out = []
    for k in range(kmax + 1):
        lp = math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log(1 - p)
        out.append(math.exp(lp))
    out[-1] += max(0.0, 1 - sum(out))
    return out


def _add(d, k, v):
    d[k] = d.get(k, 0.0) + v


class Dist:
    """Final-score distribution for one game, from the home team's side.

    margin: {home points minus away points: probability}
    total:  {combined points: probability}
    home_pts / away_pts: {that team's points: probability}, for team totals
    matrix: {(home, away): probability} when exact scores are modelled
    three_way: True when a draw is a settled result (soccer 90 minutes)
    """

    def __init__(self, method, label, inputs, margin=None, total=None, matrix=None, three_way=False, notes=None,
                 home_pts=None, away_pts=None):
        self.method = method
        self.label = label
        self.inputs = inputs
        self.margin = margin
        self.total = total
        self.matrix = matrix
        self.three_way = three_way
        self.notes = notes or []
        self.home_pts = home_pts  # {points: probability} for team totals
        self.away_pts = away_pts


def _from_matrix(matrix, tie_home=None):
    """Margin and total distributions from an exact-score matrix.

    tie_home: for MLB and NHL a level score goes to extra innings or overtime.
    The home side wins that with probability tie_home; the winner ends one
    run or goal ahead and the total rises by one.
    """
    margin, total, hp, ap = {}, {}, {}, {}
    for (h, a), p in matrix.items():
        if h == a and tie_home is not None:
            _add(margin, 1, p * tie_home)
            _add(margin, -1, p * (1 - tie_home))
            _add(total, h + a + 1, p)
            _add(hp, h + 1, p * tie_home)
            _add(hp, h, p * (1 - tie_home))
            _add(ap, a, p * tie_home)
            _add(ap, a + 1, p * (1 - tie_home))
        else:
            _add(margin, h - a, p)
            _add(total, h + a, p)
            _add(hp, h, p)
            _add(ap, a, p)
    return margin, total, hp, ap


def _independent_matrix(ph, pa):
    return {(h, a): x * y for h, x in enumerate(ph) for a, y in enumerate(pa) if x * y > 1e-15}


def _num(d, k, default=None):
    v = d.get(k, default)
    if v is None:
        return None
    return float(v)


def _mlb_runs_builder(inp, c, innings):
    """Expected runs over `innings` from the building blocks. For the first five
    innings only the opposing starter is counted (bullpen only if he's expected
    to leave before the fifth ends)."""
    lg_r, lg_era = c["league_runs_per_game"], c["league_era"]
    park = _num(inp, "park", 100) / 100

    def runs(t):
        ip = min(max(_num(t, "opp_sp_ip", 5.0), 0.0), 9.0)
        sp_share = min(ip, innings) / innings
        pitch = sp_share * (_num(t, "opp_sp", lg_era) / lg_era) + (1 - sp_share) * (_num(t, "opp_pen", lg_era) / lg_era)
        return lg_r * (innings / 9) * (_num(t, "off", 100) / 100) * pitch * park

    return runs(inp["home"]) * c["home_mult"], runs(inp["away"]) * c["away_mult"]


def mlb_f5_dist(inp, cfg):
    """First five innings. A tie after five is a push on the moneyline."""
    c = cfg["mlb"]
    notes = []
    if inp.get("home_runs_f5") is not None and inp.get("away_runs_f5") is not None:
        h, a = float(inp["home_runs_f5"]), float(inp["away_runs_f5"])
        notes.append("First-five expected runs given directly.")
    elif inp.get("home") and inp.get("away"):
        h, a = _mlb_runs_builder(inp, c, 5)
        notes.append("First-five expected runs built from offense, the opposing starter and park.")
    elif inp.get("home_runs") is not None and inp.get("away_runs") is not None:
        h, a = float(inp["home_runs"]) * 5 / 9, float(inp["away_runs"]) * 5 / 9
        notes.append("First-five runs scaled from full-game expected runs (starters not separated).")
    else:
        return None
    h, a = max(h, 0.3), max(a, 0.3)
    r = c["negbin_r"] * 5 / 9
    km = c["max_runs"]
    matrix = _independent_matrix(negbin_pmf(h, r, km), negbin_pmf(a, r, km))
    margin, total, hp, ap = _from_matrix(matrix, tie_home=None)
    notes.append("First five innings only; a tie is a push on the moneyline.")
    return Dist("mlb_f5_negbin", "First-five runs model", {"home_runs": round(h, 2), "away_runs": round(a, 2)},
                margin, total, matrix, notes=notes, home_pts=hp, away_pts=ap)


def mlb_dist(inp, cfg):
    c = cfg["mlb"]
    notes = []
    if inp.get("home_runs") is not None and inp.get("away_runs") is not None:
        h, a = float(inp["home_runs"]), float(inp["away_runs"])
        notes.append("Expected runs given directly (home field already included).")
    elif inp.get("home") and inp.get("away"):
        h, a = _mlb_runs_builder(inp, c, 9)
        notes.append("Expected runs built from offense, opposing starter and bullpen, and park.")
    else:
        return None
    h, a = max(h, 0.5), max(a, 0.5)
    km, r = c["max_runs"], c["negbin_r"]
    matrix = _independent_matrix(negbin_pmf(h, r, km), negbin_pmf(a, r, km))
    margin, total, hp, ap = _from_matrix(matrix, tie_home=c["extras_home_win"])
    return Dist("mlb_negbin", "Runs model", {"home_runs": round(h, 2), "away_runs": round(a, 2)},
                margin, total, matrix, notes=notes, home_pts=hp, away_pts=ap)


def nhl_dist(inp, cfg):
    c = cfg["nhl"]
    notes = []
    if inp.get("home_goals") is not None and inp.get("away_goals") is not None:
        h, a = float(inp["home_goals"]), float(inp["away_goals"])
        notes.append("Expected regulation goals given directly (home ice already included).")
    elif inp.get("home") and inp.get("away"):
        lg, lgx, w = c["league_reg_goals"], c["league_xg60"], c["gsax_weight"]
        H, A = inp["home"], inp["away"]
        h = lg * (_num(H, "xgf60", lgx) / lgx) * (_num(A, "xga60", lgx) / lgx) * c["home_mult"] - w * _num(A, "goalie_gsax60", 0.0)
        a = lg * (_num(A, "xgf60", lgx) / lgx) * (_num(H, "xga60", lgx) / lgx) * c["away_mult"] - w * _num(H, "goalie_gsax60", 0.0)
        notes.append("Expected goals built from 5v5 expected goals for and against, and each starting goalie.")
    else:
        return None
    h, a = max(h, 0.6), max(a, 0.6)
    km = c["max_goals"]
    matrix = _independent_matrix(poisson_pmf(h, km), poisson_pmf(a, km))
    margin, total, hp, ap = _from_matrix(matrix, tie_home=c["ot_home_win"])
    notes.append("Totals and puck lines include overtime and shootout, with a shootout counting as one goal.")
    return Dist("nhl_poisson", "Goals model", {"home_goals": round(h, 2), "away_goals": round(a, 2)},
                margin, total, matrix, notes=notes, home_pts=hp, away_pts=ap)


def soccer_dist(inp, cfg):
    c = cfg["soccer"]
    notes = []
    if inp.get("home_goals") is not None and inp.get("away_goals") is not None:
        h, a = float(inp["home_goals"]), float(inp["away_goals"])
        notes.append("Expected goals given directly (home advantage already included).")
    elif inp.get("home") and inp.get("away"):
        lg = _num(inp, "league_avg", c["league_goals"])
        H, A = inp["home"], inp["away"]
        h = lg * (_num(H, "xgf", lg) / lg) * (_num(A, "xga", lg) / lg) * c["home_mult"]
        a = lg * (_num(A, "xgf", lg) / lg) * (_num(H, "xga", lg) / lg) * c["away_mult"]
        notes.append("Expected goals built from each side's xG for and against per match.")
    else:
        return None
    h, a = max(h, 0.15), max(a, 0.15)
    km, rho = c["max_goals"], c["dixon_coles_rho"]
    ph, pa = poisson_pmf(h, km), poisson_pmf(a, km)
    matrix = {}
    for i, x in enumerate(ph):
        for j, y in enumerate(pa):
            tau = 1.0
            if i == 0 and j == 0:
                tau = 1 - h * a * rho
            elif i == 0 and j == 1:
                tau = 1 + h * rho
            elif i == 1 and j == 0:
                tau = 1 + a * rho
            elif i == 1 and j == 1:
                tau = 1 - rho
            v = x * y * max(tau, 0.0)
            if v > 1e-15:
                matrix[(i, j)] = v
    s = sum(matrix.values())
    matrix = {k: v / s for k, v in matrix.items()}
    margin, total, hp, ap = _from_matrix(matrix, tie_home=None)
    notes.append("90 minutes only. Low scores corrected for the extra draws real matches produce (Dixon-Coles).")
    return Dist("soccer_dixon_coles", "Goals model", {"home_goals": round(h, 2), "away_goals": round(a, 2)},
                margin, total, matrix, three_way=True, notes=notes, home_pts=hp, away_pts=ap)


def _normal_cdf(x, mu, sd):
    return 0.5 * (1 + math.erf((x - mu) / (sd * math.sqrt(2))))


def _discrete_normal(mu, sd, lo, hi):
    out = {}
    for k in range(lo, hi + 1):
        p = _normal_cdf(k + 0.5, mu, sd) - _normal_cdf(k - 0.5, mu, sd)
        if p > 1e-12:
            out[k] = p
    s = sum(out.values())
    return {k: v / s for k, v in out.items()}


def points_dist(sport, inp, cfg):
    c = cfg["points"][sport]
    notes = []
    margin = total = None
    m = None
    if inp.get("margin") is not None:
        m = float(inp["margin"])
        notes.append("Projected margin given directly (home field already included).")
    elif inp.get("home_rating") is not None and inp.get("away_rating") is not None:
        hfa = float(inp["hfa"]) if inp.get("hfa") is not None else c["hfa"]
        if inp.get("neutral"):
            hfa = 0.0
        m = float(inp["home_rating"]) - float(inp["away_rating"]) + hfa
        notes.append(f"Projected margin from power ratings plus {hfa:g} points home field.")
    if m is not None:
        span = int(max(60, abs(m) + 6 * c["margin_sd"]))
        margin = _discrete_normal(m, c["margin_sd"], -span, span)
        if c.get("key_numbers"):
            w = {int(k): v for k, v in cfg["nfl_key_number_weights"].items()}
            margin = {k: v * w.get(abs(k), 1.0) for k, v in margin.items()}
            s = sum(margin.values())
            margin = {k: v / s for k, v in margin.items()}
            notes.append("Margins reweighted for football key numbers (3, 7, 10, 14).")
        if c.get("tie") == "overtime":
            z = margin.pop(0, 0.0)
            if sport == "NCAAF":
                for k in (3, -3, 7, -7):
                    _add(margin, k, z / 4)
            else:
                _add(margin, 1, z / 2)
                _add(margin, -1, z / 2)
    t = None
    if inp.get("total") is not None:
        t = float(inp["total"])
        span = int(6 * c["total_sd"]) + 1
        total = _discrete_normal(t, c["total_sd"], max(0, int(t) - span), int(t) + span)
    hp = ap = None
    if m is not None and t is not None:
        sd_team = math.sqrt((c["total_sd"] ** 2 + c["margin_sd"] ** 2) / 4)
        span = int(6 * sd_team) + 1
        mh, ma = (t + m) / 2, (t - m) / 2
        hp = _discrete_normal(mh, sd_team, max(0, int(mh) - span), int(mh) + span)
        ap = _discrete_normal(ma, sd_team, max(0, int(ma) - span), int(ma) + span)
    if margin is None and total is None:
        return None
    label = "Points model"
    shown = {}
    if m is not None:
        shown["margin"] = round(m, 1)
    if t is not None:
        shown["total"] = round(t, 1)
    return Dist("points_normal" + ("_keynum" if c.get("key_numbers") else ""), label, shown, margin, total, notes=notes,
                home_pts=hp, away_pts=ap)


def model_distribution(sport, inp, cfg, period="game"):
    inp = inp or {}
    if period == "f5":
        return mlb_f5_dist(inp, cfg) if sport == "MLB" else None
    if sport == "MLB":
        return mlb_dist(inp, cfg)
    if sport == "NHL":
        return nhl_dist(inp, cfg)
    if sport == "SOCCER":
        return soccer_dist(inp, cfg)
    if sport in cfg["points"]:
        return points_dist(sport, inp, cfg)
    return None


# ---------------------------------------------------------------- settlement


OUTCOMES = ("win", "half_win", "push", "half_loss", "loss")


def _grade(x):
    return "win" if x > 1e-9 else ("loss" if x < -1e-9 else "push")


def _combine(a, b):
    pair = {a, b}
    if pair == {"win"}:
        return "win"
    if pair == {"loss"}:
        return "loss"
    if pair == {"win", "push"}:
        return "half_win"
    if pair == {"loss", "push"}:
        return "half_loss"
    return "push"


def grade_line(beat_by, line):
    """Settle a handicap or total. beat_by(L) is how far the selection clears line L.
    Quarter lines (e.g. -0.75, 2.25) split the stake across the two nearest lines."""
    quarters = round(float(line) * 4)
    if quarters % 2:
        return _combine(_grade(beat_by(line - 0.25)), _grade(beat_by(line + 0.25)))
    return _grade(beat_by(line))


def evaluate(dist, kind, sel, line, team=None):
    """Outcome probabilities {win, half_win, push, half_loss, loss} for one bet.
    team ("home"/"away") is only used by team totals."""
    out = {k: 0.0 for k in OUTCOMES}
    if kind == "moneyline":
        if dist.margin is None:
            return None
        for m, p in dist.margin.items():
            if sel == "draw":
                out["win" if m == 0 else "loss"] += p
            elif m == 0:
                out["loss" if dist.three_way else "push"] += p
            else:
                home_won = m > 0
                out["win" if home_won == (sel == "home") else "loss"] += p
    elif kind == "draw_no_bet":
        if dist.margin is None:
            return None
        for m, p in dist.margin.items():
            if m == 0:
                out["push"] += p
            else:
                out["win" if (m > 0) == (sel == "home") else "loss"] += p
    elif kind == "spread":
        if dist.margin is None or line is None:
            return None
        sign = 1 if sel == "home" else -1
        for m, p in dist.margin.items():
            out[grade_line(lambda L, m=m: sign * m + L, line)] += p
    elif kind == "total":
        if dist.total is None or line is None:
            return None
        for t, p in dist.total.items():
            if sel == "over":
                o = grade_line(lambda L, t=t: t - L, line)
            else:
                o = grade_line(lambda L, t=t: L - t, line)
            out[o] += p
    elif kind == "team_total":
        pts = dist.home_pts if team == "home" else dist.away_pts if team == "away" else None
        if pts is None or line is None:
            return None
        for t, p in pts.items():
            o = grade_line((lambda L, t=t: t - L) if sel == "over" else (lambda L, t=t: L - t), line)
            out[o] += p
    elif kind == "btts":
        if dist.matrix is None:
            return None
        for (h, a), p in dist.matrix.items():
            both = h > 0 and a > 0
            out["win" if both == (sel == "yes") else "loss"] += p
    else:
        return None
    s = sum(out.values())
    return {k: v / s for k, v in out.items()}


def win_loss_mass(o):
    return o["win"] + o["half_win"] / 2, o["loss"] + o["half_loss"] / 2


def breakeven_prob(o):
    w, l = win_loss_mass(o)
    return w / (w + l)


def reshape(shape, q):
    """Keep the model's push and half-result pattern, move the win/loss balance
    so the break-even probability equals q."""
    w, l = win_loss_mass(shape)
    a_mass = shape["win"] + shape["half_win"]
    b_mass = shape["loss"] + shape["half_loss"]
    rest = 1 - a_mass - b_mass
    if w <= EPS or l <= EPS:
        return {"win": q * (1 - shape["push"]), "half_win": 0.0, "push": shape["push"],
                "half_loss": 0.0, "loss": (1 - q) * (1 - shape["push"])}
    ratio = w * (1 - q) / (q * l)  # beta / alpha
    alpha = (1 - rest) / (a_mass + ratio * b_mass)
    beta = alpha * ratio
    return {"win": shape["win"] * alpha, "half_win": shape["half_win"] * alpha, "push": shape["push"],
            "half_loss": shape["half_loss"] * beta, "loss": shape["loss"] * beta}


def returns(d):
    b = d - 1
    return {"win": b, "half_win": b / 2, "push": 0.0, "half_loss": -0.5, "loss": -1.0}


def expected_value(o, d):
    r = returns(d)
    return sum(o[k] * r[k] for k in OUTCOMES)


def log_growth(o, d, f):
    r = returns(d)
    return sum(o[k] * math.log(1 + f * r[k]) for k in OUTCOMES if o[k] > 0)


def kelly_fraction(o, d):
    """Stake fraction that maximises expected log growth (full Kelly)."""
    if expected_value(o, d) <= 0:
        return 0.0
    lo, hi = 0.0, 0.999
    for _ in range(120):
        m1 = lo + (hi - lo) / 3
        m2 = hi - (hi - lo) / 3
        if log_growth(o, d, m1) < log_growth(o, d, m2):
            lo = m1
        else:
            hi = m2
    return (lo + hi) / 2


def min_price(o, min_ev):
    """Lowest decimal price where EV is at least min_ev, rounded up to 0.01."""
    w, l = win_loss_mass(o)
    d = 1 + (l + min_ev) / w
    return math.ceil(d * 100 - 1e-9) / 100


def fair_price(o):
    w, l = win_loss_mass(o)
    return 1 + l / w


# ---------------------------------------------------------------- labels


SPORT_NAMES = {"MLB": "MLB", "NHL": "NHL", "SOCCER": "Soccer", "NFL": "NFL", "CFL": "CFL", "NCAAF": "NCAAF",
               "NBA": "NBA", "WNBA": "WNBA", "NCAAB": "NCAAB", "TENNIS": "Tennis", "MMA": "MMA"}
SCORE_UNIT = {"MLB": "runs", "NHL": "goals", "SOCCER": "goals"}
SPREAD_NAME = {"MLB": "Run line", "NHL": "Puck line", "SOCCER": "Handicap"}


def norm_sport(s):
    s = str(s or "").strip().upper()
    aliases = {"FOOTBALL": "SOCCER", "EPL": "SOCCER", "MLS": "SOCCER", "UFC": "MMA", "COLLEGE FOOTBALL": "NCAAF",
               "COLLEGE BASKETBALL": "NCAAB", "BASEBALL": "MLB", "HOCKEY": "NHL"}
    return aliases.get(s, s)


def fmt_line(x):
    x = float(x)
    s = f"{x:+.2f}".rstrip("0").rstrip(".")
    return s


def split_market(market):
    """'total_f5' -> ('total', 'f5'); normalises common aliases."""
    kind = str(market).lower().strip().replace(" ", "_").replace("-", "_")
    period = "game"
    for suf in ("_f5", "_first5", "_first_5"):
        if kind.endswith(suf):
            kind, period = kind[: -len(suf)], "f5"
    kind = {"ml": "moneyline", "h2h": "moneyline", "winner": "moneyline", "handicap": "spread", "run_line": "spread",
            "puck_line": "spread", "ah": "spread", "totals": "total", "over_under": "total", "ou": "total",
            "team_totals": "team_total", "dnb": "draw_no_bet"}.get(kind, kind)
    return kind, period


def bet_label(c, sport):
    if c.get("bet"):
        return c["bet"]
    kind, period = split_market(c["market"])
    sel, line = c["selection"].lower(), c.get("line")
    team = c.get(sel) if sel in ("home", "away") else None
    team = team or sel.title()
    unit = SCORE_UNIT.get(sport, "points")
    f5 = ", first 5" if period == "f5" else ""
    if kind == "moneyline":
        return "Draw" if sel == "draw" else f"{team} moneyline{f5}"
    if kind == "draw_no_bet":
        return f"{team} draw no bet"
    if kind == "spread":
        return f"{team} {fmt_line(line)}{f5}"
    if kind == "total":
        return f"{'Over' if sel == 'over' else 'Under'} {float(line):g} {unit}{f5}"
    if kind == "team_total":
        who = c.get(c.get("team", "")) or str(c.get("team", "")).title()
        return f"{who} {'over' if sel == 'over' else 'under'} {float(line):g} {unit}{f5}"
    if kind == "btts":
        return f"Both teams to score: {'Yes' if sel == 'yes' else 'No'}"
    return f"{team} {kind}"


def market_label(kind, sport, period="game"):
    base = {"moneyline": "Moneyline", "draw_no_bet": "Draw no bet", "total": "Total", "team_total": "Team total",
            "btts": "Both teams to score"}.get(kind) or (SPREAD_NAME.get(sport, "Spread") if kind == "spread" else kind.title())
    return f"First 5 {base.lower()}" if period == "f5" else base


# ---------------------------------------------------------------- pricing


def adjustments_logit(adjs, cfg):
    a = cfg["adjustments"]
    sizes = a["logit_size"]
    items, raw = [], 0.0
    for x in (adjs or [])[: a["max_count"]]:
        size = str(x.get("size", "small")).lower()
        if size not in sizes:
            raise ValueError(f"Adjustment size must be one of {sorted(sizes)}, got {size!r}")
        direction = str(x.get("direction", "+")).strip()
        sign = -1 if direction in ("-", "against", "down") else 1
        v = sign * sizes[size]
        raw += v
        items.append({"factor": x.get("factor", ""), "size": size, "sign": sign, "logit": v, "note": x.get("note", "")})
    cap = a["max_total_logit"]
    total = max(-cap, min(cap, raw))
    scale = (total / raw) if abs(raw) > 1e-12 else 0.0
    for it in items:
        it["logit_applied"] = it["logit"] * scale
    return items, total, abs(raw) > cap + 1e-12


def price_candidate(c, cfg):
    original = json.loads(json.dumps(c))
    sport = norm_sport(c["sport"])
    kind, period = split_market(c["market"])
    sel = c["selection"].lower()
    line = float(c["line"]) if c.get("line") is not None else None
    team = str(c.get("team") or "").lower() or None
    if kind == "team_total" and team not in ("home", "away"):
        raise ValueError(f"{c.get('id', '?')}: team totals need \"team\": \"home\" or \"away\"")
    c = dict(c, market=kind, selection=sel)

    d = round(to_decimal(c["price"]), 4)
    warnings = []

    mv = market_view(c, cfg)
    if mv is None:
        warnings.append("No usable market prices, so the market step is skipped.")
    for s in (mv or {}).get("skipped", []):
        warnings.append(f"Skipped {s}.")

    dist = model_distribution(sport, c.get("model_inputs"), cfg, period)
    model_out = evaluate(dist, kind, sel, line, team) if dist else None
    if dist and model_out is None:
        warnings.append(f"{dist.label} can't price this market with the inputs given, so it's market only.")
    q_model = breakeven_prob(model_out) if model_out else None

    bw = cfg["blend"]
    steps = []
    if mv:
        steps.append({"key": "market", "label": "Sharp market, margin removed" if mv["source"] == "sharp" else "Market, margin removed",
                      "prob": mv["fair_prob"], "detail": mv["detail"]})
    if q_model is not None:
        steps.append({"key": "model", "label": dist.label, "prob": q_model, "detail": _inputs_text(dist, c, sport)})

    suspect = False
    if mv and q_model is not None:
        gap = abs(logit(q_model) - logit(mv["fair_prob"]))
        if gap > cfg.get("ranking", {}).get("max_model_logit_gap", 9e9):
            suspect = True
            warnings.append(f"Model ({q_model * 100:.0f}%) is far from the market ({mv['fair_prob'] * 100:.0f}%). A gap this big "
                            "is usually a wrong input (starter, goalie, home/away, stale stats), so it ranks below normal bets.")
        wm, ws = bw["market_weight"], bw["model_weight"]
        q = sigmoid((wm * logit(mv["fair_prob"]) + ws * logit(q_model)) / (wm + ws))
        steps.append({"key": "blend", "label": f"Blend: {round(wm * 100)}% market, {round(ws * 100)}% model", "prob": q})
        method = dist.method
    elif mv:
        q = mv["fair_prob"]
        method = "market_only"
    elif q_model is not None:
        q = q_model
        method = dist.method
        warnings.append("Model only, with no market check. Treat with extra caution.")
    else:
        raise ValueError(f"{c.get('id', '?')}: no market prices and no model inputs, nothing to price")

    items, total_adj, capped = adjustments_logit(c.get("adjustments"), cfg)
    running = q
    for it in items:
        nxt = sigmoid(logit(running) + it["logit_applied"])
        steps.append({"key": "adj", "label": it["factor"], "prob": nxt, "delta": nxt - running,
                      "detail": it["note"], "size": it["size"]})
        running = nxt
    if capped:
        warnings.append("Adjustments hit the cap, so each was scaled down.")
    q_final = running
    steps.append({"key": "final", "label": "Final estimate", "prob": q_final})

    if model_out:
        shape = model_out
    else:
        shape = {"win": 0.5, "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "loss": 0.5}
        if kind in ("spread", "total") and line is not None and float(line).is_integer():
            warnings.append("Whole-number line priced without a model, so the push chance isn't included.")
    final_out = reshape(shape, q_final)

    st = cfg["staking"]
    ev = expected_value(final_out, d)
    k_full = kelly_fraction(final_out, d)
    growth = log_growth(final_out, d, k_full) if k_full > 0 else 0.0
    no_edge = ev <= 0
    if no_edge:
        units = st["min_units"]
    else:
        raw_units = k_full * st["kelly_fraction"] * st["bankroll_units"]
        units = round(raw_units / st["round_to"]) * st["round_to"]
        units = min(max(units, st["min_units"]), st["max_units"])
    cc = cfg["confidence"]
    conf = "High" if ev >= cc["high_ev"] else ("Medium" if ev >= cc["medium_ev"] else "Low")
    m_price = min_price(final_out, st["min_ev"])
    f_price = fair_price(final_out)

    label = bet_label(dict(c, market=original["market"]), sport)
    sport_name = SPORT_NAMES.get(sport, str(c["sport"]))
    model_block = {
        "engine": cfg.get("engine_version", "1.0"),
        "method": method,
        "method_label": dist.label if (dist and q_model is not None) else "Market only",
        "inputs": dist.inputs if (dist and q_model is not None) else {},
        "inputs_text": _inputs_text(dist, c, sport) if (dist and q_model is not None) else "",
        "notes": (dist.notes if (dist and q_model is not None) else []),
        "steps": [_round_step(s) for s in steps],
        "books": (mv or {}).get("books", []),
        "market_margin": round(mv["avg_margin"], 4) if mv else None,
        "market_source": mv["source"] if mv else None,
        "suspect": suspect,
        "outcomes": {k: round(v, 4) for k, v in final_out.items() if v > 1e-6},
        "ev": round(ev, 4),
        "kelly_full": round(k_full, 4),
        "kelly_fraction": st["kelly_fraction"],
        "growth_bp": round(growth * 1e4, 2),
        "fair_odds_decimal": round(f_price, 2),
        "min_odds_decimal": m_price,
        "min_ev": st["min_ev"],
        "no_edge": no_edge,
        "warnings": warnings,
    }
    doc = {
        "sport": sport_name,
        "event": c.get("event") or (f"{c.get('away')} @ {c.get('home')}" if c.get("home") else ""),
        "bet": label,
        "market": market_label(kind, sport, period),
        "odds_decimal": round(d, 2),
        "odds_american": decimal_to_american(d),
        "units": units,
        "confidence": conf,
        "model_prob": round(q_final, 4),
        "implied_prob": round(1 / d, 4),
        "fair_prob": round(mv["fair_prob"], 4) if mv else None,
        "ev": round(ev, 4),
        "min_odds_decimal": m_price,
        "min_odds_american": decimal_to_american(m_price),
        "no_edge": no_edge,
        "model": model_block,
        "status": "pending",
    }
    for k in ("league", "start_time", "home", "away"):
        if c.get(k):
            doc[k] = c[k]
    doc["input"] = original
    game = c.get("game_id") or f"{doc['event']}|{c.get('start_time', '')}"
    return {"id": c.get("id"), "game": game, "score": growth, "ev": ev, "modeled": method != "market_only",
            "suspect": suspect, "doc": doc}


def _inputs_text(dist, c, sport):
    if not dist:
        return ""
    h, a = c.get("home", "Home"), c.get("away", "Away")
    i = dist.inputs
    if "home_runs" in i:
        return f"Expected runs: {h} {i['home_runs']:.1f}, {a} {i['away_runs']:.1f}"
    if "home_goals" in i:
        return f"Expected goals: {h} {i['home_goals']:.2f}, {a} {i['away_goals']:.2f}"
    parts = []
    if "margin" in i:
        fav = h if i["margin"] >= 0 else a
        parts.append(f"Projected margin: {fav} by {abs(i['margin']):.1f}")
    if "total" in i:
        parts.append(f"projected total {i['total']:.1f}")
    return ", ".join(parts)


def _round_step(s):
    out = dict(s)
    out["prob"] = round(s["prob"], 4)
    if "delta" in s:
        out["delta"] = round(s["delta"], 4)
    return out


BACKUP_FIELDS = ("bet", "event", "sport", "league", "market", "start_time", "home", "away", "odds_decimal", "odds_american",
                 "min_odds_decimal", "min_odds_american", "units", "confidence", "ev", "model_prob", "implied_prob",
                 "fair_prob", "no_edge", "input")


def rank_and_pick(priced, cfg, date=None, n_backups=2):
    """Order priced candidates and choose the pick plus backups from other games.

    Market-only candidates can never show an edge (they just copy the market and
    pay its margin), so when any candidate has a model behind it, market-only
    ones are ranked after all modeled ones."""
    prefer = cfg.get("ranking", {}).get("modeled_first", True) and any(p["modeled"] for p in priced)
    priced.sort(key=lambda p: ((p["modeled"] if prefer else True), not p.get("suspect"), p["score"], p["ev"]), reverse=True)
    for i, p in enumerate(priced, 1):
        p["rank"] = i
    if not priced:
        return None
    top = priced[0]
    pick = dict(top["doc"])
    if date:
        pick["date"] = date
    used, backups = {top["game"]}, []
    for p in priced[1:]:
        if len(backups) >= n_backups:
            break
        if p["game"] in used:
            continue
        used.add(p["game"])
        b = {k: p["doc"][k] for k in BACKUP_FIELDS if k in p["doc"]}
        b.update({"key": f"b{len(backups) + 1}", "status": "pending"})
        backups.append(b)
    pick["backups"] = backups
    chosen = {top["id"]} | {b["input"].get("id") for b in backups}
    pick["candidates"] = [
        {"bet": p["doc"]["bet"], "event": p["doc"]["event"],
         "note": f"EV {p['ev'] * 100:+.1f}% at {p['doc']['odds_decimal']:.2f}, "
                 f"estimate {p['doc']['model_prob'] * 100:.1f}% vs {p['doc']['implied_prob'] * 100:.1f}% needed"
                 + ("" if p["modeled"] else ", market only") + (", model far from market (check inputs)" if p.get("suspect") else "") + "."}
        for p in priced if p["id"] not in chosen][:8]
    return pick


def price_all(cands, cfg):
    priced, errors = [], []
    for c in cands:
        try:
            priced.append(price_candidate(c, cfg))
        except Exception as e:  # report and keep going
            errors.append({"id": c.get("id"), "error": str(e)})
    return priced, errors


def price_file(path, cfg):
    with open(path) as f:
        data = json.load(f)
    cands = data["candidates"] if isinstance(data, dict) else data
    priced, errors = price_all(cands, cfg)
    pick = rank_and_pick(priced, cfg, data.get("date") if isinstance(data, dict) else None)
    return {"pick_id": priced[0]["id"] if priced else None, "pick": pick, "ranked": priced, "errors": errors}


# ---------------------------------------------------------------- slate screening


def _median_price(books, sel):
    decs = []
    for b in books:
        prices = {str(k).lower(): v for k, v in (b.get("prices") or {}).items()}
        if sel in prices:
            try:
                decs.append(to_decimal(prices[sel]))
            except ValueError:
                pass
    return median(decs) if decs else None


SHARP_NAMES = ("pinnacle", "betfair", "circa", "matchbook")


def _is_sharp_name(book):
    k = _norm_book(book)
    return any(n in k for n in SHARP_NAMES)


def expand_slate(data):
    """Turn a slate of games (each with its markets and book prices) into one
    candidate per side of every market."""
    cands = []
    for g in data.get("games", []):
        gid = g.get("id") or f"{g.get('away')}@{g.get('home')}"
        base = {k: g[k] for k in ("sport", "league", "home", "away", "start_time", "model_inputs") if k in g}
        base["event"] = g.get("event") or (f"{g.get('home')} vs {g.get('away')}" if norm_sport(g.get("sport")) == "SOCCER"
                                           else f"{g.get('away')} @ {g.get('home')}")
        base["game_id"] = gid
        for mk in g.get("markets", []):
            market = mk["market"]
            kind, _ = split_market(market)
            books = mk.get("books") or []
            line = mk.get("line")
            keys = set()
            for b in books:
                keys |= {str(k).lower() for k in (b.get("prices") or {})}
            if kind in ("moneyline", "draw_no_bet"):
                sides = [(s, None) for s in ("home", "away", "draw") if s in keys and not (kind == "draw_no_bet" and s == "draw")]
            elif kind == "spread":
                if line is None:
                    continue
                sides = [("home", float(line)), ("away", -float(line))]
            elif kind in ("total", "team_total"):
                if line is None:
                    continue
                sides = [("over", float(line)), ("under", float(line))]
            elif kind == "btts":
                sides = [("yes", None), ("no", None)]
            else:
                continue
            soft = [b for b in books if not _is_sharp_name(b.get("book", ""))]
            for sel, ln in sides:
                price = _median_price(soft if len(soft) >= 2 else books, sel)
                if price is None:
                    continue
                c = dict(base, market=market, selection=sel, line=ln, price=round(price, 3),
                         market_odds=[{"book": b.get("book", "?"), "prices": b.get("prices", {})} for b in books],
                         adjustments=[])
                if kind == "team_total":
                    c["team"] = mk.get("team")
                tag = f"{market}:{mk.get('team', '')}{sel}{'' if ln is None else ln:}"
                c["id"] = f"{gid}:{tag}"
                cands.append(c)
    return cands


def screen_file(path, cfg, top=8):
    with open(path) as f:
        data = json.load(f)
    cands = expand_slate(data)
    priced, errors = price_all(cands, cfg)
    pick = rank_and_pick(priced, cfg, data.get("date"))
    shortlist, seen_games = [], {}
    for p in priced:
        if seen_games.get(p["game"], 0) >= 2:  # at most two bets per game on the shortlist
            continue
        seen_games[p["game"]] = seen_games.get(p["game"], 0) + 1
        shortlist.append(p)
        if len(shortlist) >= top:
            break
    games = {c["game_id"] for c in cands}
    modeled_games = {p["game"] for p in priced if p["modeled"]}
    return {"date": data.get("date"), "games": len(games), "modeled_games": len(modeled_games), "candidates": len(cands),
            "pick": pick, "ranked": priced, "shortlist": shortlist, "errors": errors}


# ---------------------------------------------------------------- afternoon price check


def recheck(doc, fresh, cfg, now_iso=None):
    """Reprice the pick and its backups at fresh prices. Returns the fields to merge
    into the pick document: a price_check block and a recommendation."""
    import datetime
    st = cfg["staking"]
    bets = [("main", doc.get("input"), doc)] + [(b.get("key"), b.get("input"), b) for b in doc.get("backups", [])]
    out = {"at": now_iso or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    recommend = None
    for key, inp, orig in bets:
        if not inp or key not in fresh:
            continue
        f = fresh[key]
        sel = str(inp.get("selection", "")).lower()
        book_med = _median_price(f.get("market_odds") or [], sel)
        price = f.get("price")
        if price is None:
            price = book_med if book_med is not None else inp.get("price")
        warn = None
        if book_med is not None and abs(to_decimal(price) / book_med - 1) > 0.12:
            warn = (f"price {to_decimal(price):.2f} doesn't match the books' median {book_med:.2f} for "
                    f"'{sel}': check the side")
        c = dict(inp, price=price)
        if f.get("market_odds"):
            c["market_odds"] = f["market_odds"]
        if f.get("adjustments") is not None:
            c["adjustments"] = f["adjustments"]
        r = price_candidate(c, cfg)["doc"]
        value = r["ev"] >= st["min_ev"] - 1e-9 and warn is None
        out[key] = {"bet": orig.get("bet"), "odds_decimal": r["odds_decimal"], "ev": r["ev"], "min_odds_decimal": r["min_odds_decimal"],
                    "model_prob": r["model_prob"], "fair_prob": r["fair_prob"], "value": value,
                    "was_odds_decimal": orig.get("odds_decimal")}
        if warn:
            out[key]["warning"] = warn
        if value and recommend is None:
            recommend = key
    out["recommend"] = recommend or "none"
    names = {"main": "the main pick", "b1": "backup 1", "b2": "backup 2"}
    out["note"] = ("No bet still has value at current prices. Skip today." if recommend is None
                   else f"Bet {names.get(recommend, recommend)}.")
    return {"price_check": out}


def print_table(result):
    print(f"{'#':>2}  {'bet':<34} {'odds':>5} {'need':>6} {'est':>6} {'EV':>7} {'units':>5} {'take at':>7}  method")
    for p in result["ranked"]:
        d = p["doc"]
        print(f"{p['rank']:>2}  {d['bet'][:34]:<34} {d['odds_decimal']:>5.2f} {d['implied_prob'] * 100:>5.1f}% "
              f"{d['model_prob'] * 100:>5.1f}% {d['ev'] * 100:>+6.1f}% {d['units']:>5.2f} {d['min_odds_decimal']:>7.2f}  "
              f"{d['model']['method']}")
        for w in d["model"]["warnings"]:
            print(f"      note: {w}")
    for e in result["errors"]:
        print(f"ERROR {e['id']}: {e['error']}")
    if result["pick"]:
        p = result["pick"]
        flag = "  (no candidate has an edge: minimum stake)" if p["no_edge"] else ""
        print(f"\nPick: {p['bet']} @ {p['odds_decimal']:.2f}, {p['units']}u, {p['confidence']}, "
              f"take at {p['min_odds_decimal']:.2f} or better{flag}")
        for b in p.get("backups", []):
            print(f"  {b['key']}: {b['bet']} ({b['event']}) @ {b['odds_decimal']:.2f}, {b['units']}u, "
                  f"take at {b['min_odds_decimal']:.2f}{'  no edge' if b.get('no_edge') else ''}")


# ---------------------------------------------------------------- closing line value


def closing_line_value(taken_decimal, close_prices, selection, method="power"):
    """CLV = price taken x closing fair probability - 1. Positive means the bet
    was better than the closing market."""
    prices = {str(k).lower(): v for k, v in close_prices.items()}
    sel = selection.lower()
    keys = list(prices)
    decs = [to_decimal(prices[k]) for k in keys]
    fair = remove_vig(decs, method)[keys.index(sel)]
    return {
        "odds_decimal": round(decs[keys.index(sel)], 3),
        "fair_prob": round(fair, 4),
        "clv": round(float(taken_decimal) * fair - 1, 4),
    }


# ---------------------------------------------------------------- CLI


def main(argv=None):
    ap = argparse.ArgumentParser(description="Morning Line pricing engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("price", help="price and rank a candidates file")
    p1.add_argument("file")
    p1.add_argument("--out", help="write the full result as JSON")
    p1.add_argument("--pick-out", help="write just the chosen pick document as JSON")
    p1.add_argument("--config")
    p2 = sub.add_parser("clv", help="closing line value for a graded pick")
    p2.add_argument("--taken", required=True, help="price taken (decimal or American)")
    p2.add_argument("--selection", required=True)
    p2.add_argument("--close", nargs="+", required=True, help="closing prices, e.g. home=-150 away=+130")
    p2.add_argument("--config")
    p3 = sub.add_parser("odds", help="convert odds")
    p3.add_argument("price")
    p4 = sub.add_parser("screen", help="price every market of every game in a slate file")
    p4.add_argument("file")
    p4.add_argument("--top", type=int, default=8, help="shortlist size")
    p4.add_argument("--out", help="write the full result as JSON")
    p4.add_argument("--candidates-out", help="write the shortlist as a candidates file to research and re-price")
    p4.add_argument("--config")
    p5 = sub.add_parser("recheck", help="reprice a saved pick and its backups at fresh prices")
    p5.add_argument("pick", help="the saved pick document (JSON)")
    p5.add_argument("--fresh", required=True, help='JSON: {"main": {"price": ..., "market_odds": [...]}, "b1": {...}, "b2": {...}}')
    p5.add_argument("--out", help="write the fields to merge into the pick document")
    p5.add_argument("--config")
    a = ap.parse_args(argv)

    if a.cmd == "odds":
        d = to_decimal(a.price)
        print(json.dumps({"decimal": round(d, 4), "american": decimal_to_american(d), "implied": round(1 / d, 4)}))
        return 0
    cfg = load_config(a.config)
    if a.cmd == "price":
        res = price_file(a.file, cfg)
        print_table(res)
        if a.out:
            with open(a.out, "w") as f:
                json.dump(res, f, indent=2, ensure_ascii=False)
        if a.pick_out and res["pick"]:
            with open(a.pick_out, "w") as f:
                json.dump(res["pick"], f, indent=2, ensure_ascii=False)
        return 1 if not res["ranked"] else 0
    if a.cmd == "screen":
        res = screen_file(a.file, cfg, a.top)
        print(f"Screened {res['games']} games ({res['modeled_games']} with a model) and {res['candidates']} bets.\n")
        print_table({"ranked": res["shortlist"], "errors": res["errors"], "pick": None})
        if a.out:
            with open(a.out, "w") as f:
                json.dump(res, f, indent=2, ensure_ascii=False)
        if a.candidates_out:
            with open(a.candidates_out, "w") as f:
                json.dump({"date": res["date"], "candidates": [p["doc"]["input"] for p in res["shortlist"]]}, f, indent=2, ensure_ascii=False)
        return 0 if res["ranked"] else 1
    if a.cmd == "recheck":
        with open(a.pick) as f:
            doc = json.load(f)
        doc = doc.get("data", doc)
        with open(a.fresh) as f:
            fresh = json.load(f)
        upd = recheck(doc, fresh, cfg)
        pc = upd["price_check"]
        for k in ("main", "b1", "b2"):
            if k in pc:
                x = pc[k]
                print(f"{k:>4}  {str(x['bet'])[:34]:<34} now {x['odds_decimal']:.2f} (was {x['was_odds_decimal']}), "
                      f"EV {x['ev'] * 100:+.1f}%, take at {x['min_odds_decimal']:.2f}  {'VALUE' if x['value'] else 'no value'}")
                if x.get("warning"):
                    print(f"      WARNING: {x['warning']}")
        print(pc["note"])
        if a.out:
            with open(a.out, "w") as f:
                json.dump(upd, f, indent=2, ensure_ascii=False)
        return 0
    if a.cmd == "clv":
        close = dict(x.split("=", 1) for x in a.close)
        print(json.dumps(closing_line_value(to_decimal(a.taken), close, a.selection, cfg.get("devig_method", "power"))))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
