#!/usr/bin/env python3
"""
Error finder: compare Stake's prices with Pinnacle's margin-free prices across many leagues
and flag any Stake price that pays more than the fair price. Runs on GitHub Actions
(standard library only) and writes to the `feed` branch under errors/.

    python3 tools/feed/errors.py --out <feed dir> [--config tools/feed/errors_config.json]

Data: OddsPapi v4 (env ODDSPAPI_KEY). One request returns one bookmaker's odds for many
tournaments, and OddsPapi uses the same fixture, market and outcome ids for every bookmaker,
so Stake and Pinnacle line up exactly. Free plan: 250 requests a month, so lists of sports,
tournaments, markets and teams are cached for a week and each scan costs two requests.

Writes:
  errors/latest.json         the current errors (what the site shows)
  errors/log/YYYY-MM.json    every error ever flagged, with the Pinnacle price tracked to kick-off
                             (closing line value) once the game starts
  errors/cache/*.json        weekly caches
  errors/usage.json          requests used this month
Optional env NTFY_TOPIC: phone alert (ntfy app) for new errors at or above alert_ev.
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "model"))
import pricing as P  # noqa: E402

API = "https://api.oddspapi.io/v4"
UA = "MorningLineErrorFinder/1.0"


def now():
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_t(s):
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(path, obj, pretty=False):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=1 if pretty else None, separators=None if pretty else (",", ":"), ensure_ascii=False)


class Client:
    def __init__(self, key, out, cfg, log):
        self.key, self.out, self.cfg, self.log = key, out, cfg, log
        self.usage_path = os.path.join(out, "errors", "usage.json")
        month = now().strftime("%Y-%m")
        u = load(self.usage_path, {})
        self.usage = u if u.get("month") == month else {"month": month, "requests": 0}

    def left(self):
        return self.cfg["monthly_requests"] - self.usage["requests"]

    _last_call = 0.0

    def get(self, path, **params):
        if self.left() <= 0:
            raise RuntimeError("monthly request budget used up")
        params["apiKey"] = self.key
        url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
        self.usage["requests"] += 1
        save(self.usage_path, self.usage)
        last = None
        for i in range(4):
            wait = 1.5 - (time.time() - Client._last_call)  # OddsPapi allows about one request a second
            if wait > 0:
                time.sleep(wait)
            Client._last_call = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:300]
                last = f"HTTP {e.code}: {body}"
                if e.code == 429:
                    try:
                        ms = json.loads(body).get("error", {}).get("retryMs") or 1500
                    except ValueError:
                        ms = 1500
                    time.sleep(ms / 1000 + 0.5)
                    continue
                if e.code in (400, 401, 403, 404, 422):
                    break
            except Exception as e:
                last = str(e)
            time.sleep(3)
        raise RuntimeError(f"{path}: {last}")


def cached(client, name, fetch, max_age_days=7):
    path = os.path.join(client.out, "errors", "cache", f"{name}.json")
    c = load(path)
    if c and (now() - parse_t(c["fetched_at"])).days < max_age_days:
        return c["data"]
    data = fetch()
    save(path, {"fetched_at": iso(now()), "data": data})
    return data


def as_list(x):
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        for k in ("data", "items", "results"):
            if isinstance(x.get(k), list):
                return x[k]
        return list(x.values())
    return []


def pick_tournaments(client, cfg, state, t0, must=()):
    """Choose this scan's leagues. The free plan allows 5 leagues per request, so the finder rotates:
    leagues not checked for a while come first, and leagues where Stake has been wrong before get a boost."""
    import math
    sports = as_list(cached(client, "sports", lambda: client.get("sports"), max_age_days=30))
    by_slug = {str(s.get("slug") or s.get("sportSlug") or "").lower(): s.get("sportId") for s in sports}
    cands = []
    for slug in cfg["sports"]:
        sid = by_slug.get(slug)
        if sid is None:
            client.log["errors"].append(f"sport '{slug}' not found")
            continue
        tours = as_list(cached(client, f"tournaments_{sid}", lambda: client.get("tournaments", sportId=sid),
                               max_age_days=cfg["tournament_list_days"]))
        for t in tours:
            name = f"{t.get('tournamentName', '')} {t.get('categoryName', '')}".lower()
            if (t.get("upcomingFixtures") or 0) <= 0 or any(x in name for x in cfg["skip_words"]):
                continue
            st = state.get(str(t["tournamentId"]), {})
            last = parse_t(st["last"]) if st.get("last") else None
            hours = (t0 - last).total_seconds() / 3600 if last else 96
            hit_rate = (st.get("hits", 0) + 1) / (st.get("scans", 0) + 2)
            score = 3 * hit_rate + min(hours, 96) / 24 + 0.5 * math.log1p(t.get("upcomingFixtures") or 0)
            if st.get("empty", 0) and not st.get("stake_seen", 0):
                score -= 5 * st["empty"]  # Stake hasn't offered this league when checked
            if t["tournamentId"] in must:
                score += 100  # re-check leagues with a flagged error kicking off soon, to get its closing line
            cands.append((score, slug, sid, t))
    cands.sort(key=lambda x: -x[0])
    chosen, sport_of = [], {}
    for _, slug, sid, t in cands[: cfg["tournaments_per_scan"]]:
        chosen.append(t)
        sport_of[t["tournamentId"]] = slug
    return chosen, sport_of, len(cands)


def compact_markets(raw, sport_ids):
    out = {}
    for m in raw:
        if not isinstance(m, dict) or m.get("playerProp") or (sport_ids and m.get("sportId") not in sport_ids):
            continue
        out[str(m.get("marketId"))] = {
            "name": m.get("marketName") or f"Market {m.get('marketId')}", "type": m.get("marketType"),
            "line": m.get("handicap"), "period": m.get("period"), "sport": m.get("sportId"),
            "outcomes": {str(o.get("outcomeId")): o.get("outcomeName") for o in (m.get("outcomes") or []) if isinstance(o, dict)}}
    return out


def market_meta(client, sport_ids):
    """Market id -> name, type, line, period and outcome names (cached for a month, kept compact)."""
    path = os.path.join(client.out, "errors", "cache", "markets.json")
    c = load(path)
    if c and isinstance(c.get("data"), dict) and (now() - parse_t(c["fetched_at"])).days < 30:
        return c["data"]
    if c and isinstance(c.get("data"), list) and (now() - parse_t(c["fetched_at"])).days < 30:
        data = compact_markets(c["data"], sport_ids)  # convert an old raw cache without spending a request
    else:
        data = compact_markets(as_list(client.get("markets")), sport_ids)
    save(path, {"fetched_at": c["fetched_at"] if c and isinstance(c.get("data"), list) else iso(now()), "data": data})
    return data


def participant_names(client, sport_ids):
    names = {}
    for sid in sport_ids:
        try:
            raw = cached(client, f"participants_{sid}", lambda: client.get("participants", sportId=sid))
        except Exception as e:
            client.log["errors"].append(f"participants {sid}: {e}")
            continue
        if isinstance(raw, dict) and not any(isinstance(v, list) for v in raw.values()):
            names.update({str(k): v for k, v in raw.items()})
        else:
            for p in as_list(raw):
                if isinstance(p, dict):
                    names[str(p.get("participantId"))] = p.get("participantName") or p.get("name")
    return names


def odds_for(client, bookmaker, tournament_ids, chunk):
    fixtures = {}
    for i in range(0, len(tournament_ids), chunk):
        ids = ",".join(str(t) for t in tournament_ids[i:i + chunk])
        try:
            got = client.get("odds-by-tournaments", bookmaker=bookmaker, tournamentIds=ids, oddsFormat="decimal")
        except RuntimeError as e:
            if "HTTP 404" in str(e):  # the bookmaker has no games in these leagues
                continue
            raise
        for fx in as_list(got):
            if isinstance(fx, dict) and fx.get("fixtureId"):
                fixtures[fx["fixtureId"]] = fx
    return fixtures


def market_prices(fx, book):
    """{market_id: {outcome_id: (price, active, limit)}} for one bookmaker on one fixture."""
    b = (fx.get("bookmakerOdds") or {}).get(book) or {}
    out = {}
    for mid, m in (b.get("markets") or {}).items():
        o = {}
        for oid, oc in (m.get("outcomes") or {}).items():
            pl = (oc.get("players") or {}).get("0") or {}
            price = pl.get("price")
            if isinstance(price, (int, float)) and price > 1:
                o[str(oid)] = (float(price), bool(pl.get("active", True)), pl.get("limit"))
        if o:
            out[str(mid)] = o
    return out, b.get("fixturePath")


WHY = {
    "stale": "Stake pays more than Pinnacle's fair price for the same bet.",
    "offline": "Pinnacle doesn't offer this line; its fair price is worked out from Pinnacle's main markets for the game.",
    "self": "Stake's price disagrees with its own main markets for this game (Pinnacle has no price for it).",
}


def _pick_outcome(e_fields, cfg, kind, o, price):
    """EV, size and take-at for one outcome distribution at Stake's price; None if not an error."""
    ev = P.expected_value(o, price)
    floor = {"stale": cfg["min_ev"], "offline": cfg["min_ev_offline"], "self": cfg["min_ev_self"]}[kind]
    if ev < floor:
        return None, "below"
    if ev > cfg["max_ev"]:
        return None, "palpable"
    k = P.kelly_fraction(o, price)
    units = min(max(round(k * cfg["kelly_fraction"] * 100 / 0.25) * 0.25, 0.25), cfg["max_units"])
    be = P.breakeven_prob(o)
    return dict(e_fields, type=kind, why=WHY[kind], ev=round(ev, 4), fair_prob=round(be, 4), fair_odds=round(1 / be, 3),
                take_at=P.min_price(o, cfg["take_at_ev"]), units=units), "ok"


def find_errors(stake_fx, pin_fx, cfg, meta, pnames, tour_info, t0, last_prices):
    """Three detectors:
      stale    Stake vs Pinnacle on the same market (Pinnacle margin removed)
      offline  Stake lines Pinnacle doesn't offer, priced from a goals model fitted to Pinnacle's main markets
      self     no Pinnacle price: Stake lines priced from a model fitted to Stake's own main markets
    Edges above max_ev are treated as obvious errors Stake would void and left out.
    Returns (errors, stats, fair_now, prices_now)."""
    import soccer_fit as F
    from pricing import load_config
    mcfg = load_config()
    errors, fair_now, prices_now = [], {}, {}
    stats = {"stale_compared": 0, "offline_priced": 0, "self_priced": 0, "palpable_skipped": 0, "steam": 0, "fit_failed": 0}
    for fid, sfx in stake_fx.items():
        start = parse_t(sfx.get("startTime"))
        if not start or start <= t0 + dt.timedelta(minutes=cfg["min_minutes_to_start"]):
            continue
        if start > t0 + dt.timedelta(hours=cfg["max_hours_to_start"]):
            continue
        pfx = pin_fx.get(fid) or {}
        smk, link = market_prices(sfx, "stake")
        pmk, _ = market_prices(pfx, "pinnacle")
        prices_now[fid] = {"t": iso(t0), "s": {m: {o: v[0] for o, v in outs.items()} for m, outs in smk.items()},
                           "p": {m: {o: v[0] for o, v in outs.items()} for m, outs in pmk.items()}}
        prev = last_prices.get(fid) or {}
        tour = tour_info.get(sfx.get("tournamentId"), {})
        base = {"fixture_id": fid, "tournament_id": sfx.get("tournamentId"), "sport": tour.get("sport"),
                "league": tour.get("name"), "country": tour.get("category"), "start_time": iso(start), "stake_link": link,
                "home": pnames.get(str(sfx.get("participant1Id")), f"Team {sfx.get('participant1Id')}"),
                "away": pnames.get(str(sfx.get("participant2Id")), f"Team {sfx.get('participant2Id')}")}

        def fields(mid, oid, price):
            m = meta.get(mid, {})
            return dict(base, id=f"{fid}:{mid}:{oid}", market_id=mid, outcome_id=oid, market=m.get("name", f"Market {mid}"),
                        outcome=(m.get("outcomes") or {}).get(oid) or oid, stake_price=round(price, 3))

        # 1) same market at both books
        same = set()
        for mid, souts in smk.items():
            pouts = pmk.get(mid)
            if not pouts or set(pouts) != set(souts) or len(pouts) < 2 or not all(a for _, a, _ in pouts.values()):
                continue
            decs = {k: v[0] for k, v in pouts.items()}
            margin = sum(1 / d for d in decs.values()) - 1
            if margin > cfg["max_pinnacle_margin"] or margin < -0.01:
                continue
            same.add(mid)
            fair = F.devig(decs)
            stats["stale_compared"] += 1
            for oid, (price, active, _) in souts.items():
                fair_now[(fid, mid, oid)] = fair[oid]
                if not active or not (cfg["min_price"] <= price <= cfg["max_price"]):
                    continue
                o = {"win": fair[oid], "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "loss": 1 - fair[oid]}
                e, why = _pick_outcome(fields(mid, oid, price), cfg, "stale", o, price)
                stats["palpable_skipped"] += why == "palpable"
                if e:
                    e.update(pinnacle_price=pouts[oid][0], pinnacle_margin=round(margin, 4), pinnacle_limit=pouts[oid][2])
                    pp = ((prev.get("p") or {}).get(mid) or {}).get(oid)
                    sp = ((prev.get("s") or {}).get(mid) or {}).get(oid)
                    if pp and sp and abs(sp - price) < 1e-9 and abs(pp - pouts[oid][0]) / pp >= cfg["steam_move"]:
                        e["steam"] = f"Pinnacle moved {pp:.2f} → {pouts[oid][0]:.2f} since {prev.get('t', '')[11:16]} UTC; Stake hasn't changed"
                        stats["steam"] += 1
                    errors.append(e)

        # 2) and 3) soccer goal markets priced from a fitted model
        if tour.get("sport") != "soccer":
            continue
        anchor_book, anchor_mk = ("pinnacle", pmk) if pmk else ("stake", smk)
        tg = F.anchor_targets({m: {o: v[0] for o, v in outs.items()} for m, outs in anchor_mk.items()}, meta)
        if not tg:
            continue
        lh, la, dist, rms = F.fit(tg["p_home"], tg["p_away"], tg["p_over"], tg["line"], mcfg)
        if rms > cfg["max_fit_error"]:
            stats["fit_failed"] += 1
            continue
        kind = "offline" if anchor_book == "pinnacle" else "self"
        anchor_ids = set()
        if kind == "self":  # the markets the fit came from can't be judged against themselves
            anchor_ids = {tg["total_market"]} | {m for m in smk if meta.get(m, {}).get("type") == "1x2" and meta.get(m, {}).get("period") == "fulltime"}
        for mid, souts in smk.items():
            if mid in same or mid in anchor_ids:
                continue
            m = meta.get(mid)
            if not m:
                continue
            for oid, (price, active, _) in souts.items():
                o = F.price_market(dist, m, m["outcomes"].get(oid))
                if not o:
                    continue
                be = P.breakeven_prob(o)
                if be <= 0 or be >= 1:
                    continue
                fair_now[(fid, mid, oid)] = be
                stats[f"{kind}_priced"] += 1
                if not active or not (cfg["min_price"] <= price <= cfg["max_price"]):
                    continue
                e, why = _pick_outcome(fields(mid, oid, price), cfg, kind, o, price)
                stats["palpable_skipped"] += why == "palpable"
                if e:
                    e.update(model_goals=f"{base['home']} {lh:.2f}, {base['away']} {la:.2f}", anchor=anchor_book)
                    errors.append(e)
    errors.sort(key=lambda e: -e["ev"])
    return errors, stats, fair_now, prices_now


def update_log(out, errors, fair_now, t0):
    """Keep every flagged error and track its fair price until kick-off (closing line value)."""
    path = os.path.join(out, "errors", "log", f"{t0.strftime('%Y-%m')}.json")
    log = load(path, {})
    new = []
    for e in errors:
        if e["id"] not in log:
            log[e["id"]] = dict(e, first_seen=iso(t0), last_seen=iso(t0), close_fair=e["fair_prob"], close_at=iso(t0))
            new.append(e)
        else:
            log[e["id"]].update(last_seen=iso(t0), best_price=max(log[e["id"]].get("best_price", 0), e["stake_price"]))
    for rec in log.values():
        start = parse_t(rec["start_time"])
        if not start or start <= t0:
            continue
        f = fair_now.get((rec["fixture_id"], rec["market_id"], rec["outcome_id"]))
        if f:
            rec.update(close_fair=round(f, 4), close_at=iso(t0))
    for rec in log.values():
        rec["clv"] = round(rec["stake_price"] * rec["close_fair"] - 1, 4)
        rec["closed"] = bool(parse_t(rec["start_time"]) and parse_t(rec["start_time"]) <= t0)
    save(path, log)
    return new, log


def alert(topic, new, cfg):
    hits = [e for e in new if e["ev"] >= cfg["alert_ev"]]
    if not topic or not hits:
        return 0
    lines = [f"{e['outcome']} {e['market']} — {e['away']} @ {e['home']}: Stake {e['stake_price']} (fair {e['fair_odds']}, "
             f"+{e['ev'] * 100:.1f}%), take {e['take_at']}+" for e in hits[:5]]
    req = urllib.request.Request(f"https://ntfy.sh/{urllib.parse.quote(topic)}", data="\n".join(lines).encode(),
                                 headers={"Title": f"Error finder: {len(hits)} new", "Click": "https://johnfitz-z.github.io/errors/",
                                          "Tags": "moneybag"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
        return len(hits)
    except Exception:
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", default=os.path.join(HERE, "errors_config.json"))
    a = ap.parse_args(argv)
    cfg = load(a.config)
    t0 = now()
    log = {"started_at": iso(t0), "errors": []}
    key = os.environ.get("ODDSPAPI_KEY", "").strip()
    latest_path = os.path.join(a.out, "errors", "latest.json")
    if not key:
        log["errors"].append("ODDSPAPI_KEY is not set")
        prev = load(latest_path, {})
        save(latest_path, dict(prev, status="waiting for key", checked_at=iso(t0)) if prev.get("errors")
             else {"status": "waiting for key", "checked_at": iso(t0), "errors": []}, pretty=True)
        save(os.path.join(a.out, "errors", "run.json"), log, pretty=True)
        print(json.dumps(log))
        return 0
    client = Client(key, a.out, cfg, log)
    try:
        if client.left() < cfg["reserve_requests"] + 2:
            raise RuntimeError(f"only {client.left()} requests left this month; skipping the scan")
        rot_path = os.path.join(a.out, "errors", "cache", "rotation.json")
        rotation = load(rot_path, {})
        month_log = load(os.path.join(a.out, "errors", "log", f"{t0.strftime('%Y-%m')}.json"), {})
        soon = {r.get("tournament_id") for r in month_log.values() if r.get("tournament_id") is not None
                and parse_t(r["start_time"]) and t0 < parse_t(r["start_time"]) <= t0 + dt.timedelta(hours=30)}
        tours, sport_of, n_cands = pick_tournaments(client, cfg, rotation, t0, must=soon)
        tour_info = {t["tournamentId"]: {"name": t.get("tournamentName"), "category": t.get("categoryName"),
                                         "sport": sport_of.get(t["tournamentId"])} for t in tours}
        ids = [t["tournamentId"] for t in tours]
        mnames = market_meta(client, {15, 10, 11, 12, 13, 14})
        stake = odds_for(client, "stake", ids, cfg["tournaments_per_request"])
        stake_tours = {fx.get("tournamentId") for fx in stake.values()}
        pin_ids = [t for t in ids if t in stake_tours]  # don't spend a request on leagues Stake doesn't offer
        pin = odds_for(client, "pinnacle", pin_ids, cfg["tournaments_per_request"]) if pin_ids else {}
        sport_ids = {fx.get("sportId") for fx in stake.values() if fx.get("sportId") is not None}
        pnames = participant_names(client, sorted(sport_ids)) if cfg.get("fetch_team_names", True) else {}
        lp_path = os.path.join(a.out, "errors", "cache", "last_prices.json")
        last_prices = load(lp_path, {})
        errs, stats, fair_now, prices_now = find_errors(stake, pin, cfg, mnames, pnames, tour_info, t0, last_prices)
        last_prices.update(prices_now)
        last_prices = {k: v for k, v in last_prices.items() if (t0 - parse_t(v["t"])).days < 6}
        save(lp_path, last_prices)
        compared = stats["stale_compared"] + stats["offline_priced"] + stats["self_priced"]
        hit_tours = {stake[e["fixture_id"]].get("tournamentId") for e in errs if e["fixture_id"] in stake}
        for tid in ids:
            st = rotation.setdefault(str(tid), {"scans": 0, "hits": 0})
            n_stake = sum(1 for fx in stake.values() if fx.get("tournamentId") == tid)
            st["stake_seen"] = st.get("stake_seen", 0) + n_stake
            st["empty"] = st.get("empty", 0) + (0 if n_stake else 1)
            st.update(last=iso(t0), scans=st["scans"] + 1, hits=st["hits"] + (1 if tid in hit_tours else 0),
                      name=tour_info[tid]["name"], country=tour_info[tid]["category"])
        save(rot_path, rotation)
        new, history = update_log(a.out, errs, fair_now, t0)
        sent = alert(os.environ.get("NTFY_TOPIC", "").strip(), new, cfg)
        closed = [r for r in history.values() if r.get("closed")]
        save(latest_path, {
            "status": "ok", "scanned_at": iso(t0), "tournaments": len(ids), "leagues_available": n_cands,
            "leagues_scanned": [f"{tour_info[t]['category']} · {tour_info[t]['name']}" for t in ids], "stake_fixtures": len(stake),
            "both_books": sum(1 for f in stake if f in pin), "markets_compared": compared, "min_ev": cfg["min_ev"],
            "detectors": stats, "by_type": {k: sum(1 for e in errs if e["type"] == k) for k in ("stale", "offline", "self")},
            "requests_left_this_month": client.left(), "errors": errs[: cfg["max_listed"]],
            "month": {"flagged": len(history), "closed": len(closed),
                      "avg_ev": round(sum(r["ev"] for r in history.values()) / len(history), 4) if history else None,
                      "avg_clv": round(sum(r["clv"] for r in closed) / len(closed), 4) if closed else None,
                      "beat_close": sum(1 for r in closed if r["clv"] > 0)},
        }, pretty=True)
        if stake:
            sample = next(iter(stake.values()))
            save(os.path.join(a.out, "errors", "debug_sample.json"), {"stake_fixture": sample, "pinnacle_fixture": pin.get(sample["fixtureId"])}, pretty=True)
        log.update(tournaments=len(ids), stake_fixtures=len(stake), pinnacle_fixtures=len(pin), compared=compared, detectors=stats,
                   errors_found=len(errs), new=len(new), alerts=sent, requests_left=client.left())
    except Exception as e:
        log["errors"].append(str(e))
        prev = load(latest_path, {})
        save(latest_path, dict(prev, status=f"error: {str(e)[:160]}", checked_at=iso(t0)), pretty=True)
    log["finished_at"] = iso(now())
    save(os.path.join(a.out, "errors", "run.json"), log, pretty=True)
    print(json.dumps(log, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
