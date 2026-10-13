#!/usr/bin/env python3
"""
The pick database: one JSON file per list in db/picks/<id>.json (id = YYYY-MM-DD, or YYYY-MM-DD-2 for a
second list on the same day). This folder is the source of truth; the website is built from it.

    python3 tools/db.py list                      # ids, newest last
    python3 tools/db.py get 2026-10-13            # print one document
    python3 tools/db.py set 2026-10-13 pick.json  # create or replace
    python3 tools/db.py update 2026-10-13 patch.json   # merge top-level fields (e.g. price_check, card)

Python callers: `import db; db.load(id)`, `db.save(id, doc)`, `db.all_docs()`.
"""

import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "db", "picks")


def path(pid):
    if not pid or "/" in pid or pid.startswith("."):
        raise ValueError(f"bad id {pid!r}")
    return os.path.join(DIR, f"{pid}.json")


def ids():
    return sorted(os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(DIR, "*.json")))


def load(pid):
    try:
        with open(path(pid)) as f:
            d = json.load(f)
    except FileNotFoundError:
        return None
    return d.get("data", d) if isinstance(d, dict) else d


def save(pid, doc):
    os.makedirs(DIR, exist_ok=True)
    tmp = path(pid) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path(pid))


def all_docs():
    return [(i, load(i)) for i in ids()]


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "list":
        print("\n".join(ids()))
    elif cmd == "get":
        d = load(argv[1])
        if d is None:
            print(f"no document {argv[1]}")
            return 1
        print(json.dumps(d, indent=1, ensure_ascii=False))
    elif cmd in ("set", "update"):
        with open(argv[2]) as f:
            new = json.load(f)
        new = new.get("data", new)
        if cmd == "update":
            cur = load(argv[1])
            if cur is None:
                print(f"no document {argv[1]} to update")
                return 1
            cur.update(new)
            new = cur
        save(argv[1], new)
        print(f"saved {argv[1]}")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
