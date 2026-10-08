#!/usr/bin/env python3
"""
Build the Morning Line website from site/ into the repository root, where
GitHub Pages serves it.

    python3 site/build.py            # build
    python3 site/build.py --check    # build into a temp folder and report, touching nothing

Inputs
    site/site.json        site name and public URL
    site/templates/       base layout, page bodies, partials, service worker
    site/assets/          CSS and ES-module JavaScript
    site/static/          icons and the web app manifest
    data/picks.json       every pick (written by model/export_site.py)

Outputs (repository root)
    index.html, results/, stats/, bankroll/, method/, 404.html
    pick/<date>/index.html   one page per pick, with its own title and link preview
    assets/                  versioned copies of site/assets
    sw.js, manifest.webmanifest, icons, robots.txt, .nojekyll

Only the Python standard library is used, so it runs anywhere Python 3 does.
"""

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")

PAGES = [
    # page key, template, output path, title, description
    ("today", "today.html", "index.html", "Morning Line", "Today's researched pick, with every reason shown and every result kept."),
    ("results", "results.html", "results/index.html", "Results · Morning Line", "Every Morning Line pick and how it finished."),
    ("stats", "stats.html", "stats/index.html", "Stats · Morning Line", "Record, units, closing line value and model accuracy."),
    ("bankroll", "bankroll.html", "bankroll/index.html", "Bankroll · Morning Line", "Track your own bets and balance."),
    ("method", "method.html", "method/index.html", "How it works · Morning Line", "How each Morning Line pick is researched, priced and graded."),
    ("404", "404.html", "404.html", "Not found · Morning Line", "That page doesn't exist."),
]
NAV = ["today", "results", "stats", "bankroll", "method"]
GENERATED = ["index.html", "404.html", "results", "stats", "bankroll", "method", "pick", "assets", "sw.js",
             "manifest.webmanifest", "favicon.png", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "robots.txt"]


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def fill(tpl, values):
    out = tpl
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_a-z]+\}\}", out)
    if left:
        raise SystemExit(f"Unfilled template placeholders: {sorted(set(left))}")
    return out


def asset_version():
    h = hashlib.sha1()
    for base in ("assets", "templates", "static"):
        for dirpath, _, files in sorted(os.walk(os.path.join(SITE, base))):
            for name in sorted(files):
                p = os.path.join(dirpath, name)
                h.update(p.replace(SITE, "").encode())
                with open(p, "rb") as f:
                    h.update(f.read())
    return h.hexdigest()[:10]


def load_picks():
    p = os.path.join(ROOT, "data", "picks.json")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        j = json.load(f)
    picks = j.get("picks", []) if isinstance(j, dict) else j
    out = []
    for x in picks:
        if not isinstance(x, dict):
            continue
        pid = str(x.get("id") or x.get("date") or "")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", pid):
            continue
        out.append(dict(x, id=pid))
    return out


def fmt_day(d):
    import datetime
    try:
        dt = datetime.date.fromisoformat(d)
        return dt.strftime("%b ") + str(dt.day)
    except ValueError:
        return d


def render_page(base, page, body, title, desc, url, site_url, v, pick_id=None, og_title=None):
    values = {
        "TITLE": html.escape(title), "DESC": html.escape(desc, quote=True), "URL": url, "SITE": site_url,
        "OG_TITLE": html.escape(og_title or title, quote=True), "PAGE": page, "V": v, "CONTENT": body,
        "PICK_ATTR": f' data-pick="{html.escape(pick_id, quote=True)}"' if pick_id else "",
    }
    for key in NAV:
        values["CUR_" + key] = ' aria-current="page"' if key == page else ""
    return fill(base, values)


def build(out_root, quiet=False):
    cfg = json.loads(read(SITE, "site.json"))
    site_url = cfg["url"].rstrip("/")
    v = asset_version()
    base = read(SITE, "templates", "base.html")
    bank_card = read(SITE, "templates", "partials", "bank_card.html")
    picks = load_picks()

    # clear old output
    for name in GENERATED:
        p = os.path.join(out_root, name)
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.exists(p):
            os.remove(p)

    written = []

    # pages
    for key, tpl, out, title, desc in PAGES:
        body = read(SITE, "templates", "pages", tpl).replace("{{BANK_CARD}}", bank_card)
        path_url = "/" + out.replace("index.html", "")
        if key == "404":
            path_url = "/404.html"
        page_html = render_page(base, key, body, title, desc, site_url + path_url, site_url, v)
        write(os.path.join(out_root, out), page_html)
        written.append(out)

    # one page per pick
    pick_tpl = read(SITE, "templates", "pages", "pick.html")
    for p in picks:
        bet = str(p.get("bet") or "Pick")
        when = fmt_day(str(p.get("date") or p["id"]))
        status = str(p.get("status") or "pending").replace("_", " ")
        odds = p.get("odds_decimal")
        summary = str(p.get("summary") or "")
        result = f"{status.title()}: {p.get('final_score')}. " if p.get("final_score") else ""
        desc = f"{result}{bet} at {odds:.2f}. {summary}" if isinstance(odds, (int, float)) else f"{result}{bet}. {summary}"
        desc = desc.strip()[:280]
        noscript = (f'<noscript><div class="t-head"><h1 class="t-bet">{html.escape(bet)}</h1>'
                    f'<p class="t-event">{html.escape(str(p.get("event") or ""))}</p><p>{html.escape(summary)}</p></div></noscript>')
        body = pick_tpl.replace("{{NOSCRIPT}}", noscript)
        out = f"pick/{p['id']}/index.html"
        title = f"{bet} · {when} · Morning Line"
        write(os.path.join(out_root, out),
              render_page(base, "pick", body, title, desc, f"{site_url}/pick/{p['id']}/", site_url, v,
                          pick_id=p["id"], og_title=f"{bet} · {when}"))
        written.append(out)

    # assets, with import specifiers versioned so a deploy never mixes old and new modules
    src_assets = os.path.join(SITE, "assets")
    js_files = []
    for dirpath, _, files in os.walk(src_assets):
        for name in files:
            src = os.path.join(dirpath, name)
            rel = os.path.relpath(src, src_assets)
            dst = os.path.join(out_root, "assets", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if name.endswith(".js"):
                code = read(src)
                code = re.sub(r'(from\s+"\./[^"?]+\.js)"', r'\1?v=' + v + '"', code)
                code = re.sub(r'(import\s+"\./[^"?]+\.js)"', r'\1?v=' + v + '"', code)
                write(dst, code)
                js_files.append("/assets/" + rel.replace(os.sep, "/"))
            else:
                shutil.copyfile(src, dst)
            written.append("assets/" + rel)

    # static files
    for name in os.listdir(os.path.join(SITE, "static")):
        shutil.copyfile(os.path.join(SITE, "static", name), os.path.join(out_root, name))
        written.append(name)
    write(os.path.join(out_root, "robots.txt"), "User-agent: *\nDisallow: /\n")
    write(os.path.join(out_root, ".nojekyll"), "")

    # service worker
    core = ["/", "/results/", "/stats/", "/bankroll/", "/method/", "/404.html", "/manifest.webmanifest",
            "/favicon.png", "/icon-192.png", f"/assets/css/main.css?v={v}"] + [f"{j}?v={v}" for j in sorted(js_files)]
    sw = fill(read(SITE, "templates", "sw.js"), {"V": v, "CORE": json.dumps(core)})
    write(os.path.join(out_root, "sw.js"), sw)
    written.append("sw.js")

    if not quiet:
        print(f"Built {len(written)} files (version {v}): {len(PAGES)} pages, {len(picks)} pick pages")
    return {"version": v, "files": written, "picks": len(picks)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="build into a temp folder only")
    a = ap.parse_args(argv)
    if a.check:
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(os.path.join(ROOT, "data"), os.path.join(tmp, "data"))
            build(tmp)
        return 0
    build(ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
