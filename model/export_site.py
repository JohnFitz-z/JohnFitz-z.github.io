#!/usr/bin/env python3
"""
Build the website's picks.json from an export of the pick database.

    python3 model/export_site.py /tmp/ml-export picks.json [--require 2026-10-07]

The export directory is what ArtifactData writes with out_dir: one JSON file
per pick under <dir>/picks/<date>.json. Every pick is checked and cleaned so
a typo in one field can't break the page: numbers stored as text become
numbers, percentages above 1 become fractions, and anything still wrong is
reported. Exits non-zero if a required date is missing or a pick is unusable.
"""

import argparse
import datetime
import glob
import json
import os
import sys

NUMERIC = ("odds_decimal", "odds_american", "units", "model_prob", "implied_prob", "fair_prob", "ev",
           "min_odds_decimal", "min_odds_american", "result_units")
PROBS = ("model_prob", "implied_prob", "fair_prob")
STATUSES = {"pending", "won", "lost", "push", "void", "half_won", "half_lost"}
REQUIRED = ("date", "sport", "event", "bet", "odds_decimal", "status")


def to_num(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return float(str(v).replace("%", "").replace("+", "").strip())
    except ValueError:
        return "bad"


def clean(p, problems):
    pid = p.get("id") or p.get("date") or "?"
    for k in NUMERIC:
        if k in p:
            v = to_num(p[k])
            if v == "bad":
                problems.append(f"{pid}: {k} isn't a number ({p[k]!r}), removed")
                p.pop(k)
            else:
                p[k] = v
    for k in PROBS:
        v = p.get(k)
        if isinstance(v, (int, float)) and v > 1:
            p[k] = v / 100
    if isinstance(p.get("ev"), (int, float)) and abs(p["ev"]) > 1:
        p["ev"] = p["ev"] / 100
    st = str(p.get("status") or "pending").lower().replace("-", "_")
    if st not in STATUSES:
        problems.append(f"{pid}: unknown status {p.get('status')!r}, shown as pending")
        st = "pending"
    p["status"] = st
    if st in ("won", "lost", "half_won", "half_lost") and not isinstance(p.get("result_units"), (int, float)):
        problems.append(f"{pid}: graded {st} but result_units is missing")
    backups = p.get("backups")
    if backups is not None and not isinstance(backups, list):
        problems.append(f"{pid}: backups isn't a list, removed")
        p.pop("backups")
    for i, b in enumerate(p.get("backups") or []):
        if not isinstance(b, dict):
            continue
        b.setdefault("key", f"b{i + 1}")
        for k in NUMERIC:
            if k in b:
                v = to_num(b[k])
                b[k] = None if v == "bad" else v
        for k in PROBS:
            if isinstance(b.get(k), (int, float)) and b[k] > 1:
                b[k] = b[k] / 100
        bst = str(b.get("status") or "pending").lower().replace("-", "_")
        b["status"] = bst if bst in STATUSES else "pending"
        if bst in ("won", "lost", "half_won", "half_lost") and not isinstance(b.get("result_units"), (int, float)):
            problems.append(f"{pid}: backup {b['key']} graded {bst} but result_units is missing")
    close = p.get("close")
    if isinstance(close, dict):
        for k in ("odds_decimal", "fair_prob", "clv"):
            if k in close:
                v = to_num(close[k])
                close[k] = None if v == "bad" else v
    for k in REQUIRED:
        if p.get(k) in (None, ""):
            problems.append(f"{pid}: missing {k}")
    return p


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("export_dir")
    ap.add_argument("out")
    ap.add_argument("--require", help="date (YYYY-MM-DD) that must be present")
    a = ap.parse_args(argv)

    files = sorted(glob.glob(os.path.join(a.export_dir, "picks", "*.json")))
    if not files:
        files = sorted(glob.glob(os.path.join(a.export_dir, "*.json")))
    picks, problems = [], []
    for f in files:
        with open(f) as fh:
            j = json.load(fh)
        body = dict(j.get("data", j)) if isinstance(j, dict) else None
        if not body:
            problems.append(f"{os.path.basename(f)}: not a pick document")
            continue
        body.setdefault("id", os.path.splitext(os.path.basename(f))[0])
        body.setdefault("date", body["id"])
        picks.append(clean(body, problems))
    picks.sort(key=lambda p: p.get("date", ""))

    out = {"updated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "picks": picks}
    with open(a.out, "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    graded = sum(1 for p in picks if p["status"] not in ("pending", "void"))
    print(f"Wrote {len(picks)} picks ({graded} graded) to {a.out}")
    for msg in problems:
        print("WARNING", msg)
    if a.require and not any(p.get("date") == a.require for p in picks):
        print(f"ERROR: no pick for {a.require}")
        return 1
    if any("missing date" in m or "missing bet" in m or "missing odds_decimal" in m for m in problems):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
