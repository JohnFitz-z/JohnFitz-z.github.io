#!/usr/bin/env python3
"""
Publish the pick database to the website in one step.

    python3 tools/publish.py /tmp/ml/export [--require 2026-10-08]

1. Rebuilds data/picks.json from an ArtifactData export (model/export_site.py),
   checking every field.
2. Rebuilds every page of the site (site/build.py), including a page per pick.
Then commit everything with `git add -A` and push.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    export_dir, rest = argv[0], argv[1:]
    r = subprocess.run([sys.executable, os.path.join(ROOT, "model", "export_site.py"), export_dir,
                        os.path.join(ROOT, "data", "picks.json")] + rest)
    if r.returncode != 0:
        print("Data export failed; the site was not rebuilt.")
        return r.returncode
    r = subprocess.run([sys.executable, os.path.join(ROOT, "site", "build.py")])
    return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
