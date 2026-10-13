#!/usr/bin/env python3
"""
Afternoon price check with no AI: reprice today's list at the latest odds and mark any bet whose edge
has gone, so the website drops it from the money plan.

    python3 tools/price_check.py [--feed ../feed] [--date YYYY-MM-DD]

Uses the afternoon snapshot on the feed branch (odds/latest_afternoon.json, or latest.json), the same
tools the morning run uses (tools/close_from_feed.py --fresh, model/pricing.py recheck), and writes the
"price_check" block into db/picks/<id>.json for every list dated today.
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "model"))
import db  # noqa: E402
import pricing as P  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=os.environ.get("FEED_DIR") or os.path.join(ROOT, "..", "feed"))
    ap.add_argument("--date")
    a = ap.parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc)
    today = a.date or now.astimezone(ZoneInfo("America/Halifax")).date().isoformat()
    cfg = P.load_config()
    ids = [i for i in db.ids() if i == today or i.startswith(today + "-")]
    if not ids:
        print("No list today.")
        return 0
    for pid in ids:
        doc = db.load(pid)
        tmp = f"/tmp/pc_{pid}.json"
        out = f"/tmp/pc_{pid}_fresh.json"
        with open(tmp, "w") as f:
            json.dump(doc, f)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "close_from_feed.py"), a.feed, tmp, "--fresh", "--out", out],
                           capture_output=True, text=True)
        print(r.stdout.strip())
        if r.returncode != 0 or not os.path.exists(out):
            print(f"{pid}: no fresh prices")
            continue
        with open(out) as f:
            fresh = json.load(f)
        bets = {"main": doc} | {c.get("key"): c for c in doc.get("card") or []} | {b.get("key"): b for b in doc.get("backups") or []}
        for k in list(fresh):
            b = bets.get(k)
            st = b and b.get("start_time")
            conditional = str((b or {}).get("price_source", "")).startswith("minimum")  # "bet only at X or better": John checks Stake himself
            if not b or not st or conditional or dt.datetime.fromisoformat(str(st).replace("Z", "+00:00")) <= now:
                fresh.pop(k)
        if not fresh:
            print(f"{pid}: nothing left to check")
            continue
        upd = P.recheck(doc, fresh, cfg, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        doc.update(upd)
        db.save(pid, doc)
        pc = upd["price_check"]
        for k, v in pc.items():
            if isinstance(v, dict):
                print(f"{pid} {k}: {v.get('bet')} now {v.get('odds_decimal')} (was {v.get('was_odds_decimal')}), "
                      f"edge {v.get('ev', 0) * 100:+.1f}% {'still good' if v.get('value') else 'NO LONGER WORTH IT'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
