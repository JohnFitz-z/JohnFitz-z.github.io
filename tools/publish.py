#!/usr/bin/env python3
"""
Publish the pick database to the website in one step.

    python3 tools/publish.py [db] [--require 2026-10-08]

1. Rebuilds data/picks.json from the database folder (db/, one JSON file per list under db/picks/;
   any folder laid out the same way works), checking every field (model/export_site.py).
2. Rebuilds every page of the site (site/build.py), including a page per pick.
Then commit everything with `git add -A` and push.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv):
    if argv and not argv[0].startswith("--"):
        export_dir, rest = argv[0], argv[1:]
    else:
        export_dir, rest = os.path.join(ROOT, "db"), argv
    r = subprocess.run([sys.executable, os.path.join(ROOT, "model", "export_site.py"), export_dir,
                        os.path.join(ROOT, "data", "picks.json")] + rest)
    if r.returncode != 0:
        print("Data export failed; the site was not rebuilt.")
        return r.returncode
    r = subprocess.run([sys.executable, os.path.join(ROOT, "site", "build.py")])
    return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
