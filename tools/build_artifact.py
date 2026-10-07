#!/usr/bin/env python3
"""
Make the claude.ai artifact copy of the site from index.html.

    python3 tools/build_artifact.py index.html out.html

Same page and styles. The only differences: the artifact reads picks live from
its own database instead of picks.json, and the artifact host supplies the
document skeleton and safe-area padding.
"""

import re
import sys

DB_LOADER = """/*LOADER*/
  (async () => {
    let db = null;
    try { db = window.claude && window.claude.use ? await window.claude.use("db") : null; } catch(e){ db = null; }
    if(!db){ failed = "Open this page on claude.ai while signed in to see the picks."; renderAll(); return; }
    db.collection("picks").onSnapshot(snap => {
      setPicks(snap.docs.filter(d => d.exists).map(d => Object.assign({}, d.data() || {}, {id: d.id})), null);
    }, () => {
      if(!loaded){ failed = "The pick store couldn't be reached. Reload the page to try again."; renderAll(); }
    });
  })();
  /*END LOADER*/"""


def main(src, out):
    s = open(src).read()
    head = s.split("<!--HEAD-END-->", 1)[1].split("<!--BODY-START-->", 1)[0]
    body = s.split("<body>", 1)[1].rsplit("</body>", 1)[0]
    head = re.sub(r"html\{([^}]*);padding:env\([^}]*\)\}", r"html{\1}", head)
    body, n = re.subn(r"/\*LOADER\*/.*?/\*END LOADER\*/", lambda m: DB_LOADER, body, flags=re.S)
    if n != 1:
        raise SystemExit("loader markers not found")
    with open(out, "w") as f:
        f.write("<title>Morning Line</title>\n" + head.strip() + "\n" + body.strip() + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
