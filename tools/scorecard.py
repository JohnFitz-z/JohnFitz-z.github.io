#!/usr/bin/env python3
"""
The analyst's scorecard: how every bet on the daily list has done, broken down the ways that matter for
deciding what to bet next (sport, bet type, angle, confidence, method, odds range), plus closing line value.

    python3 tools/scorecard.py data/picks.json --out notes/scorecard.md
    python3 tools/scorecard.py <export dir>      # a database export (one JSON per pick under picks/)

Each bet counts once even if it appears as both a backup and a card bet. Profit is in units at the stake
the system recommended (1 unit = 1% of the bankroll) and also flat (1 unit on every bet).
"""

import argparse
import datetime
import glob
import json
import os
import sys
from collections import defaultdict

GRADED = {"won", "lost", "push", "void", "half_won", "half_lost"}


def load(path):
    if os.path.isdir(path):
        out = []
        for f in sorted(glob.glob(os.path.join(path, "picks", "*.json"))):
            with open(f) as fh:
                d = json.load(fh)
            d = d.get("data", d)
            d.setdefault("id", os.path.splitext(os.path.basename(f))[0])
            out.append(d)
        return out
    with open(path) as f:
        d = json.load(f)
    return d.get("picks", d) if isinstance(d, dict) else d


def market_type(b):
    k = str(b.get("market_key") or b.get("market") or "").lower()
    if k.startswith("player") or "player" in k:
        return "player prop"
    for word, label in (("moneyline", "moneyline"), ("spread", "spread"), ("puck line", "spread"), ("run line", "spread"),
                        ("handicap", "spread"), ("team total", "team total"), ("team_total", "team total"), ("total", "total"),
                        ("btts", "both teams score"), ("draw", "moneyline")):
        if word in k:
            return label
    return k or "other"


def bets_of(picks):
    seen, out = set(), []
    for p in picks:
        if p.get("excluded"):
            continue
        method = p.get("method") or ("analyst" if (p.get("model") or {}).get("method") == "analyst" else "engine")
        entries = [("main", p)] + [("backup", b) for b in p.get("backups") or []] + [("card", c) for c in p.get("card") or []]
        for role, b in entries:
            key = (p.get("date"), b.get("event"), b.get("bet"))
            if key in seen:
                continue
            seen.add(key)
            st = str(b.get("status") or "pending").lower().replace("-", "_")
            odds = b.get("odds_decimal")
            if not isinstance(odds, (int, float)):
                continue
            close = (p.get("close") or {}) if role == "main" else (b.get("close") or {})
            out.append({"date": str(p.get("date")), "role": role, "method": method, "sport": b.get("sport") or p.get("sport"),
                        "type": market_type(b), "angle": b.get("angle") or ("model" if method == "engine" else "unknown"),
                        "confidence": b.get("confidence") or "—", "odds": float(odds), "units": float(b.get("units") or 1),
                        "status": st, "bet": b.get("bet"), "event": b.get("event"), "clv": close.get("clv")})
    return out


def result_units(b, stake):
    w = b["odds"] - 1
    return {"won": stake * w, "half_won": stake * w / 2, "lost": -stake, "half_lost": -stake / 2}.get(b["status"], 0.0)


def summarize(rows):
    g = [r for r in rows if r["status"] in GRADED]
    w = sum(r["status"] in ("won", "half_won") for r in g)
    l = sum(r["status"] in ("lost", "half_lost") for r in g)
    p = len(g) - w - l
    units = sum(result_units(r, r["units"]) for r in g)
    risked = sum(r["units"] for r in g if r["status"] not in ("push", "void"))
    flat = sum(result_units(r, 1.0) for r in g)
    exp_w = sum(1 / r["odds"] for r in g if r["status"] not in ("push", "void"))
    clvs = [r["clv"] for r in g if isinstance(r.get("clv"), (int, float))]
    return {"n": len(g), "w": w, "l": l, "p": p, "units": units, "roi": units / risked if risked else None, "flat": flat,
            "exp_w": exp_w, "clv": sum(clvs) / len(clvs) if clvs else None, "n_clv": len(clvs),
            "pending": sum(r["status"] == "pending" for r in rows)}


def fmt_row(name, s):
    rec = f"{s['w']}-{s['l']}" + (f"-{s['p']}" if s["p"] else "")
    roi = f"{s['roi'] * 100:+.1f}%" if s["roi"] is not None else "—"
    clv = f"{s['clv'] * 100:+.1f}% ({s['n_clv']})" if s["clv"] is not None else "—"
    vs = f"{s['w'] - s['exp_w']:+.1f}" if s["n"] else "—"
    return f"| {name} | {s['n']} | {rec} | {s['units']:+.2f} | {roi} | {s['flat']:+.2f} | {vs} | {clv} |"


HEAD = ("| Group | Bets | Record | Units | ROI | Flat units | Wins vs odds | Avg CLV |\n"
        "|---|---|---|---|---|---|---|---|")


def table(title, rows, keyf, min_n=1):
    groups = defaultdict(list)
    for r in rows:
        groups[keyf(r)].append(r)
    lines = [f"### {title}", "", HEAD]
    for k, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        s = summarize(rs)
        if s["n"] >= min_n:
            lines.append(fmt_row(str(k), s))
    return "\n".join(lines) + "\n"


def odds_band(r):
    o = r["odds"]
    return "under 1.60" if o < 1.6 else "1.60-1.99" if o < 2.0 else "2.00-2.99" if o < 3.0 else "3.00+"


def render(rows, today=None):
    today = today or datetime.date.today().isoformat()
    since = (datetime.date.fromisoformat(today) - datetime.timedelta(days=14)).isoformat()
    s_all, s_recent = summarize(rows), summarize([r for r in rows if r["date"] >= since])
    out = [f"# Scorecard (updated {today})", "",
           "Every bet the system posted, whether or not John placed it. \"Wins vs odds\" is actual wins minus the wins the "
           "odds implied: positive means the picks beat the price. CLV is how the closing price compared with ours "
           "(positive = the market moved our way), the best early sign of a real edge.", "",
           HEAD, fmt_row("All bets", s_all), fmt_row("Last 14 days", s_recent), "",
           table("By method", rows, lambda r: r["method"]),
           table("By sport", rows, lambda r: r["sport"]),
           table("By bet type", rows, lambda r: r["type"]),
           table("By angle", rows, lambda r: r["angle"]),
           table("By confidence", rows, lambda r: r["confidence"]),
           table("By odds", rows, odds_band)]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--out")
    ap.add_argument("--today")
    a = ap.parse_args(argv)
    md = render(bets_of(load(a.source)), a.today)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w") as f:
            f.write(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
