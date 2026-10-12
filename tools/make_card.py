#!/usr/bin/env python3
"""
Turn the analyst's list of bets into the day's pick document.

    python3 tools/make_card.py bets.json --out pick.json

bets.json is written by the morning run after it has handicapped the slate (model/ANALYST.md):

    {
      "date": "2026-10-13",
      "summary": "...", "reasoning": ["..."], "risks": ["..."], "sources": [{"title": "...", "url": "..."}],
      "bets": [
        {
          "sport": "NBA", "league": "NBA", "event": "Warriors @ Lakers", "home": "Lakers", "away": "Warriors",
          "start_time": "2026-10-13T22:30:00-03:00",
          "market": "player_points",          # moneyline | spread | total | team_total | btts | player_<stat> | other
          "bet": "Stephen Curry over 27.5 points",
          "selection": "over", "line": 27.5, "team": null, "player": "Stephen Curry",
          "odds": 1.87,                        # the price on Stake (or the soft-book median if Stake's isn't known)
          "price_source": "Stake",
          "my_prob": 0.58,                     # final probability, after reconciling with the market
          "sharp_prob": 0.53,                  # Pinnacle's no-vig probability for the same bet, when there is one
          "confidence": "High",                # High | Medium
          "angle": "role change",              # the kind of edge (see ANALYST.md)
          "reason": "Klay out: Curry's usage is up 4 points in 6 games without him; Lakers allow the 3rd-most 3s.",
          "edge_reason": "...",                # required when my_prob is more than 8 points from sharp_prob
          "market_odds": [{"book": "Pinnacle", "prices": {"over": 1.95, "under": 1.87}}],   # optional
          "input": {...}                       # optional engine candidate for main markets (price check, CLV)
        }
      ]
    }

Every bet is checked against the rules in config.json "analyst": a minimum edge at the stated odds, a
minimum price, a cap on how far the read can sit from Pinnacle without a stated reason, at most two bets
per game and ten in total. Bets that fail are listed with the reason and left out. The best bet (by
confidence, then edge) becomes the top-level pick and the rest go in "card" (keys c1, c2, ...).
Each bet gets its fair price, edge, take-at price (lowest odds that still clear the minimum edge) and a
stake in units (quarter Kelly times a confidence factor; 1 unit = 1% of the bankroll).
"""

import argparse
import datetime
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "model"))
import pricing as P  # noqa: E402

MARKET_LABEL = {"moneyline": "Moneyline", "spread": "Spread", "total": "Total", "team_total": "Team total",
                "btts": "Both teams to score", "draw_no_bet": "Draw no bet", "double_chance": "Double chance"}
ENGINE_MARKETS = {"moneyline", "spread", "total", "team_total", "moneyline_f5", "total_f5", "spread_f5"}
CONF_ORDER = {"High": 0, "Medium": 1}


def market_label(m):
    m = str(m or "")
    if m in MARKET_LABEL:
        return MARKET_LABEL[m]
    if m.startswith("player_"):
        return "Player " + m[len("player_"):].replace("_", " ")
    return m.replace("_", " ").capitalize() or "Other"


def ceil2(x):
    return math.ceil(x * 100 - 1e-9) / 100


def round_units(u, step=0.25):
    return round(round(u / step) * step, 2)


def check(b, cfg):
    """Returns (problems, warnings). A bet with problems is left out."""
    a = cfg["analyst"]
    probs, warns = [], []
    for k in ("sport", "event", "bet", "start_time", "odds", "my_prob", "confidence", "reason"):
        if b.get(k) in (None, ""):
            probs.append(f"missing {k}")
    if probs:
        return probs, warns
    try:
        odds = P.to_decimal(b["odds"])
    except ValueError as e:
        return [str(e)], warns
    p = float(b["my_prob"])
    if not 0.02 <= p <= 0.98:
        probs.append(f"my_prob {p} is outside 0.02-0.98")
        return probs, warns
    if b["confidence"] not in a["confidence_mult"]:
        probs.append(f"confidence must be one of {', '.join(a['confidence_mult'])}")
    if odds < a["min_odds"]:
        probs.append(f"odds {odds:.2f} are below the {a['min_odds']:.2f} minimum (too little payout for the risk)")
    ev = p * odds - 1
    if ev < a["min_ev"] - 1e-9:
        probs.append(f"edge {ev * 100:+.1f}% at {odds:.2f} is below the {a['min_ev'] * 100:.0f}% minimum")
    sp = b.get("sharp_prob")
    if sp not in (None, ""):
        gap = p - float(sp)
        if abs(gap) > a["max_gap"] + 1e-9:
            probs.append(f"read {p * 100:.0f}% is {abs(gap) * 100:.0f} points from Pinnacle ({float(sp) * 100:.0f}%): "
                         f"more than the {a['max_gap'] * 100:.0f}-point cap")
        elif abs(gap) > a["gap_needs_reason"] + 1e-9 and not b.get("edge_reason"):
            probs.append(f"read is {abs(gap) * 100:.0f} points from Pinnacle: add edge_reason (the fact the market hasn't priced)")
    else:
        if p - 1 / odds > a["max_edge_no_sharp"] + 1e-9:
            probs.append(f"read {p * 100:.0f}% is {(p - 1 / odds) * 100:.0f} points over the odds with no sharp price to check "
                         f"against (cap {a['max_edge_no_sharp'] * 100:.0f})")
        warns.append("no sharp price to check against")
    try:
        start = datetime.datetime.fromisoformat(str(b["start_time"]).replace("Z", "+00:00"))
        if start.tzinfo is None:
            warns.append("start_time has no UTC offset")
    except ValueError:
        probs.append(f"start_time {b['start_time']!r} isn't an ISO time")
    return probs, warns


def build_bet(b, cfg):
    a = cfg["analyst"]
    odds = round(P.to_decimal(b["odds"]), 3)
    p = float(b["my_prob"])
    ev = p * odds - 1
    take = ceil2((1 + a["min_ev"]) / p)
    full_kelly = max(0.0, ev / (odds - 1))
    units = full_kelly * a["kelly_fraction"] * 100 * a["confidence_mult"][b["confidence"]]
    units = max(0.25, min(a["max_units"], round_units(units)))
    sp = b.get("sharp_prob")
    sp = float(sp) if sp not in (None, "") else None
    market = str(b.get("market") or "other")
    inp = dict(b.get("input") or {})
    for k in ("sport", "league", "home", "away", "start_time", "selection", "line", "team", "player"):
        if b.get(k) is not None and k not in inp:
            inp[k] = b[k]
    inp.setdefault("market", market)
    if b.get("market_odds") and "market_odds" not in inp:
        inp["market_odds"] = b["market_odds"]
    inp["my_prob"] = round(p, 4)
    inp["price"] = odds
    steps = []
    if sp is not None:
        steps.append({"key": "market", "label": "Pinnacle, margin removed", "prob": round(sp, 4)})
    steps.append({"key": "final", "label": "Our read", "prob": round(p, 4), "detail": b.get("edge_reason") or b["reason"]})
    doc = {
        "sport": b["sport"], "league": b.get("league") or b["sport"], "event": b["event"],
        "home": b.get("home"), "away": b.get("away"), "start_time": b["start_time"],
        "market": market_label(market), "market_key": market, "bet": b["bet"],
        "selection": b.get("selection"), "line": b.get("line"), "player": b.get("player"),
        "odds_decimal": odds, "odds_american": P.decimal_to_american(odds),
        "min_odds_decimal": take, "min_odds_american": P.decimal_to_american(take),
        "price_source": b.get("price_source") or "books",
        "model_prob": round(p, 4), "implied_prob": round(1 / odds, 4), "fair_prob": round(sp, 4) if sp is not None else None,
        "ev": round(ev, 4), "units": units, "confidence": b["confidence"], "angle": b.get("angle"),
        "note": b["reason"], "edge_reason": b.get("edge_reason"),
        "model": {"method": "analyst", "fair_odds_decimal": round(1 / p, 3), "min_odds_decimal": take, "steps": steps},
        "input": inp, "status": "pending",
    }
    return {k: v for k, v in doc.items() if v is not None}


def make(data, cfg, now=None):
    a = cfg["analyst"]
    kept, dropped = [], []
    for b in data.get("bets", []):
        probs, warns = check(b, cfg)
        if probs:
            dropped.append({"bet": b.get("bet"), "event": b.get("event"), "why": "; ".join(probs)})
            continue
        doc = build_bet(b, cfg)
        if warns:
            doc["warnings"] = warns
        kept.append(doc)
    kept.sort(key=lambda d: (CONF_ORDER.get(d["confidence"], 9), -d["ev"]))
    per_game, final = {}, []
    for d in kept:
        g = d["event"]
        if per_game.get(g, 0) >= a["max_per_game"]:
            dropped.append({"bet": d["bet"], "event": g, "why": f"already {a['max_per_game']} bets on this game"})
            continue
        if len(final) >= a["max_bets"]:
            dropped.append({"bet": d["bet"], "event": g, "why": f"list is full ({a['max_bets']} bets)"})
            continue
        per_game[g] = per_game.get(g, 0) + 1
        final.append(d)
    if not final:
        return None, dropped
    top = dict(final[0])
    card = []
    for i, d in enumerate(final[1:], 1):
        c = dict(d)
        c.pop("warnings", None)
        c["key"] = f"c{i}"
        card.append(c)
    top.update({
        "date": data["date"], "card": card, "method": "analyst",
        "summary": data.get("summary") or top.get("note"),
        "reasoning": data.get("reasoning") or [], "risks": data.get("risks") or [], "sources": data.get("sources") or [],
        "created_at": now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "no_edge": False,
    })
    if dropped:
        top["passed"] = dropped
    return top, dropped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bets")
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", default=os.path.join(ROOT, "model", "config.json"))
    a = ap.parse_args(argv)
    with open(a.config) as f:
        cfg = json.load(f)
    with open(a.bets) as f:
        data = json.load(f)
    if not data.get("date"):
        print("ERROR: bets.json needs a date")
        return 1
    pick, dropped = make(data, cfg)
    for d in dropped:
        print(f"LEFT OUT  {d['bet']} ({d['event']}): {d['why']}")
    if not pick:
        print("ERROR: no bet passed the rules. Re-check the reads and prices, or post no card today.")
        return 1
    allb = [pick] + pick["card"]
    print(f"\n{len(allb)} bet{'s' if len(allb) != 1 else ''} on the list:")
    for i, d in enumerate(allb, 1):
        print(f"{i:>2}. {d['bet']:<40} {d['odds_decimal']:>5.2f} (take {d['min_odds_decimal']:.2f}+)  "
              f"read {d['model_prob'] * 100:4.1f}%  edge {d['ev'] * 100:+5.1f}%  {d['units']}u  {d['confidence']}"
              + (f"  [{', '.join(d['warnings'])}]" if d.get("warnings") else ""))
    with open(a.out, "w") as f:
        json.dump(pick, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
