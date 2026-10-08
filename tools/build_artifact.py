#!/usr/bin/env python3
"""
Make the claude.ai artifact copy of the site from tools/artifact/page.html (the single-page version).

    python3 tools/build_artifact.py tools/artifact/page.html out.html

Same page and styles. The only differences: the artifact reads picks live from
its own database instead of picks.json, keeps the viewer's bets in their
Claude account instead of the browser, and the artifact host supplies the
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


DB_STORE = """/*STORE*/
  const Store = (() => {
    let refP = null, writing = false, queued = null;
    const getRef = () => refP || (refP = (async () => {
      try {
        const db = await window.claude.use("db"), user = await window.claude.use("user");
        if(!db || !user) return null;
        const id = await user.id();
        return id ? db.doc("data/users/" + id + "/bankroll") : null;
      } catch(e){ return null; }
    })());
    async function flush(){
      if(writing || !queued) return;
      writing = true;
      const st = queued; queued = null;
      try { const r = await getRef(); if(r) await r.set(st); } catch(e){ Store.note = "Not saved"; }
      writing = false;
      if(queued) flush();
    }
    return {
      where: "Saved privately to your Claude account, so it's the same on every device where you open this page on claude.ai. The GitHub site keeps its own separate copy.",
      note: "",
      async load(){
        const r = await getRef();
        if(!r){ this.note = "Not saving"; this.where = "Sign in to claude.ai to save your bets here."; return null; }
        try { const s = await r.get(); return s.exists ? JSON.parse(JSON.stringify(s.data())) : null; } catch(e){ return null; }
      },
      async save(st){ queued = JSON.parse(JSON.stringify(st)); flush(); return true; }
    };
  })();
  /*END STORE*/"""


def main(src, out):
    s = open(src).read()
    head = s.split("<!--HEAD-END-->", 1)[1].split("<!--BODY-START-->", 1)[0]
    body = s.split("<body>", 1)[1].rsplit("</body>", 1)[0]
    head = re.sub(r"html\{([^}]*);padding:env\([^}]*\)\}", r"html{\1}", head)
    body, n = re.subn(r"/\*LOADER\*/.*?/\*END LOADER\*/", lambda m: DB_LOADER, body, flags=re.S)
    if n != 1:
        raise SystemExit("loader markers not found")
    body, n = re.subn(r"/\*STORE\*/.*?/\*END STORE\*/", lambda m: DB_STORE, body, flags=re.S)
    if n != 1:
        raise SystemExit("store markers not found")
    with open(out, "w") as f:
        f.write("<title>Morning Line</title>\n" + head.strip() + "\n" + body.strip() + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
