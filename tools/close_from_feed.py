#!/usr/bin/env python3
"""
Closing line value from the data feed, measured against the sharp close (Pinnacle, then
Betfair Exchange; the median of all books only if neither priced it).

    python3 tools/close_from_feed.py <feed dir> <pick.json> [--out close.json] [--backup b1]

<pick.json> is a pick document (as exported from the database). Prints the "close"
object to save on the pick, e.g. {"odds_decimal": 1.87, "fair_prob": 0.521, "clv": 0.031,
"source": "Pinnacle close (feed, 8:41 PM)"}. Exits 1 if the game or line isn't in the feed;
then look the close up by hand as before.
Also used by the price check: `--fresh` builds fresh.json (current prices for the main pick
and backups) from the latest odds snapshot instead of the closing file.
"""

import argparse
import datetime as dt
import json
import os
import sys
from statistics import median
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
sys.path.insert(0, HERE)
import pricing as P  # noqa: E402
from feed_to_slate import BOOK_NAMES  # noqa: E402

TZ = ZoneInfo("America/Halifax")
SHARP_ORDER = ("pinnacle", "betfair_ex_eu", "betfair_ex_uk", "matchbook")


def t(s):
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def same_team(full, short):
    full, short = str(full).lower(), str(short or "").lower()
    return bool(short) and (full == short or full.endswith(" " + short) or short in full)


def find_event(events, bet):
    start = t(bet["start_time"]) if bet.get("start_time") else None
    for ev in events:
        if not (same_team(ev["home"], bet.get("home")) and same_team(ev["away"], bet.get("away"))):
            continue
        if start and abs((t(ev["commence_time"]) - start).total_seconds()) > 4 * 3600:
            continue
        return ev
    return None


def book_prices(ev, inp):
    """{book_key: {side: price}} for the bet's market at the bet's line."""
    kind, period = P.split_market(inp["market"])
    if period != "game":
        return {}
    sel, line = inp["selection"].lower(), inp.get("line")
    out = {}
    for key, b in ev["books"].items():
        if kind == "moneyline" and "h2h" in b:
            out[key] = dict((k, v) for k, v in b["h2h"].items() if k in ("home", "away", "draw"))
        elif kind == "spread" and "spreads" in b and line is not None:
            home_line = float(line) if sel == "home" else -float(line)
            if abs(float(b["spreads"]["line"]) - home_line) < 1e-9:
                out[key] = {"home": b["spreads"]["home"], "away": b["spreads"]["away"]}
        elif kind == "total" and "totals" in b and line is not None:
            if abs(float(b["totals"]["line"]) - float(line)) < 1e-9:
                out[key] = {"over": b["totals"]["over"], "under": b["totals"]["under"]}
    return {k: v for k, v in out.items() if sel in v}


def sharp_or_median(prices):
    for key in SHARP_ORDER:
        if key in prices:
            return prices[key], BOOK_NAMES.get(key, key)
    if len(prices) >= 2:
        sides = set.intersection(*(set(p) for p in prices.values()))
        return {s: median(p[s] for p in prices.values()) for s in sides}, f"median of {len(prices)} books"
    return None, None


def bet_of(doc, key):
    if key in (None, "main"):
        return dict(doc.get("input") or {}, **{k: doc.get(k) for k in ("home", "away", "start_time") if doc.get(k)}), doc
    b = next((x for x in doc.get("backups") or [] if x.get("key") == key), None)
    if not b:
        raise SystemExit(f"no backup {key}")
    return dict(b.get("input") or {}, **{k: b.get(k) for k in ("home", "away", "start_time") if b.get(k)}), b


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("feed")
    ap.add_argument("pick")
    ap.add_argument("--backup", help="b1 or b2 instead of the main pick")
    ap.add_argument("--out")
    ap.add_argument("--fresh", action="store_true", help="write fresh.json for the price check from the latest snapshot")
    a = ap.parse_args(argv)
    with open(a.pick) as f:
        doc = json.load(f)
    doc = doc.get("data", doc)

    if a.fresh:
        snap = None
        for name in ("latest_afternoon.json", "latest.json"):
            try:
                with open(os.path.join(a.feed, "odds", name)) as f:
                    snap = json.load(f)
                break
            except OSError:
                continue
        if not snap:
            print("ERROR: no odds snapshot in the feed")
            return 1
        fresh = {}
        for key in ["main"] + [b.get("key") for b in doc.get("backups") or []]:
            inp, src = bet_of(doc, key)
            ev = find_event(snap["events"], inp)
            if not ev:
                print(f"{key}: game not in the snapshot")
                continue
            prices = book_prices(ev, inp)
            if len(prices) < 2:
                print(f"{key}: fewer than two books at line {inp.get('line')}")
                continue
            sel = inp["selection"].lower()
            soft = {k: v for k, v in prices.items() if k not in SHARP_ORDER}
            fresh[key] = {"price": round(median(v[sel] for v in (soft or prices).values()), 3),
                          "market_odds": [{"book": BOOK_NAMES.get(k, k), "prices": v} for k, v in prices.items()]}
            print(f"{key}: {src.get('bet')} now {fresh[key]['price']} across {len(prices)} books (snapshot {snap.get('fetched_at')})")
        if a.out:
            with open(a.out, "w") as f:
                json.dump(fresh, f, indent=1)
        return 0 if fresh else 1

    inp, src = bet_of(doc, a.backup)
    start = t(inp["start_time"])
    day = start.astimezone(TZ).date().isoformat()
    try:
        with open(os.path.join(a.feed, "odds", "closing", f"{day}.json")) as f:
            events = list(json.load(f)["events"].values())
    except OSError:
        print(f"ERROR: no closing file for {day}")
        return 1
    ev = find_event(events, inp)
    if not ev:
        print("ERROR: game not in the closing file")
        return 1
    prices = book_prices(ev, inp)
    close, source = sharp_or_median(prices)
    if not close:
        print(f"ERROR: no closing prices for {inp['market']} at line {inp.get('line')}")
        return 1
    taken = src.get("odds_decimal") or inp.get("price")
    res = P.closing_line_value(taken, close, inp["selection"])
    snap_at = t(ev.get("snapshot_at")).astimezone(TZ).strftime("%-I:%M %p") if ev.get("snapshot_at") else ""
    res["source"] = f"{source} close (feed, {snap_at})"
    print(json.dumps(res))
    if a.out:
        with open(a.out, "w") as f:
            json.dump(res, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
