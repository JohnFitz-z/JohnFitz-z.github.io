"""Tests for the error finder's detectors (run: python3 -m unittest tools/feed/test_errors.py)."""

import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "model"))
import errors as E  # noqa: E402
import pricing as P  # noqa: E402
import soccer_fit as F  # noqa: E402

CFG = dict(min_minutes_to_start=20, max_hours_to_start=120, min_price=1.3, max_price=5.0, max_pinnacle_margin=0.08,
           min_ev=0.03, min_ev_offline=0.04, min_ev_self=0.05, max_ev=0.25, take_at_ev=0.015, kelly_fraction=0.25,
           max_units=1.0, steam_move=0.03, max_fit_error=0.02)
MCFG = P.load_config()

META = {
    "101": {"name": "Full Time Result", "type": "1x2", "line": 0, "period": "fulltime", "outcomes": {"101": "1", "102": "X", "103": "2"}},
    "1010": {"name": "Over Under Full Time", "type": "totals", "line": 2.5, "period": "fulltime", "outcomes": {"1010": "Over", "1011": "Under"}},
    "1012": {"name": "Over Under Full Time", "type": "totals", "line": 3.5, "period": "fulltime", "outcomes": {"1012": "Over", "1013": "Under"}},
    "10176": {"name": "Over Under Full Time", "type": "totals", "line": 3.25, "period": "fulltime", "outcomes": {"10176": "Over", "10177": "Under"}},
    "1068": {"name": "Asian Handicap", "type": "spreads", "line": -0.5, "period": "fulltime", "outcomes": {"1068": "1", "1069": "2"}},
    "104": {"name": "Both Teams To Score", "type": "bothteamsscore", "line": 0, "period": "fulltime", "outcomes": {"104": "Yes", "105": "No"}},
}


def book_prices(dist, margin, overrides=None, only=None):
    """Prices for every META market from a model distribution, with a bookmaker margin."""
    out = {}
    for mid, m in META.items():
        if only and mid not in only:
            continue
        probs = {oid: P.breakeven_prob(F.price_market(dist, m, name)) for oid, name in m["outcomes"].items()}
        s = sum(probs.values())
        out[mid] = {oid: round(1 / (p / s * (1 + margin)), 3) for oid, p in probs.items()}
    for (mid, oid), price in (overrides or {}).items():
        out[mid][oid] = price
    return out


def fixture(book, markets, start):
    return {"fixtureId": "fx1", "tournamentId": 7, "participant1Id": 1, "participant2Id": 2, "startTime": start,
            "bookmakerOdds": {book: {"fixturePath": "https://stake.com/x", "markets": {
                mid: {"outcomes": {oid: {"players": {"0": {"price": pr, "active": True, "limit": 100}}} for oid, pr in outs.items()}}
                for mid, outs in markets.items()}}}}


class Detectors(unittest.TestCase):
    def setUp(self):
        self.t0 = E.now()
        self.start = (self.t0 + dt.timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.dist = F._dist(1.6, 1.1, MCFG)
        self.tour = {7: {"name": "Primera", "category": "Chile", "sport": "soccer"}}

    def run_finder(self, stake_mk, pin_mk):
        stake = {"fx1": fixture("stake", stake_mk, self.start)}
        pin = {"fx1": fixture("pinnacle", pin_mk, self.start)} if pin_mk else {}
        return E.find_errors(stake, pin, CFG, META, {"1": "Colo-Colo", "2": "U. de Chile"}, self.tour, self.t0, {})

    def test_fit_recovers_goals(self):
        tg = F.anchor_targets(book_prices(self.dist, 0.04), META)
        lh, la, _, rms = F.fit(tg["p_home"], tg["p_away"], tg["p_over"], tg["line"], MCFG)
        self.assertAlmostEqual(lh, 1.6, delta=0.03)
        self.assertAlmostEqual(la, 1.1, delta=0.03)
        self.assertLess(rms, 0.005)

    def test_fair_prices_raise_nothing(self):
        errs, stats, _, _ = self.run_finder(book_prices(self.dist, 0.06), book_prices(self.dist, 0.03, only={"101", "1010", "1068"}))
        self.assertEqual(errs, [])
        self.assertGreater(stats["offline_priced"], 0)

    def test_offline_line_mispriced(self):
        # Pinnacle has only the main markets; Stake's over 3.25 is far too generous
        stake = book_prices(self.dist, 0.06, overrides={("10176", "10176"): 3.4})
        errs, _, _, _ = self.run_finder(stake, book_prices(self.dist, 0.03, only={"101", "1010", "1068"}))
        self.assertEqual([(e["type"], e["market_id"], e["outcome_id"]) for e in errs], [("offline", "10176", "10176")])
        self.assertGreater(errs[0]["ev"], 0.04)
        self.assertIn("Colo-Colo", errs[0]["model_goals"])

    def test_stale_same_market(self):
        stake = book_prices(self.dist, 0.06, overrides={("101", "103"): 4.6})
        pin = book_prices(self.dist, 0.03)
        errs, _, _, _ = self.run_finder(stake, pin)
        self.assertEqual([(e["type"], e["outcome"]) for e in errs], [("stale", "2")])

    def test_self_check_without_pinnacle(self):
        stake = book_prices(self.dist, 0.06, overrides={("104", "104"): 2.3})
        errs, _, _, _ = self.run_finder(stake, None)
        self.assertEqual([(e["type"], e["market"], e["outcome"]) for e in errs], [("self", "Both Teams To Score", "Yes")])

    def test_obvious_typo_left_out(self):
        stake = book_prices(self.dist, 0.06, overrides={("1012", "1012"): 4.9})  # fair is about 3.3
        errs, stats, _, _ = self.run_finder(stake, book_prices(self.dist, 0.03, only={"101", "1010"}))
        self.assertEqual(errs, [])
        self.assertEqual(stats["palpable_skipped"], 1)

    def test_steam_note(self):
        pin_now = book_prices(self.dist, 0.03)
        stake = book_prices(self.dist, 0.06, overrides={("101", "103"): 4.6})
        last = {"fx1": {"t": "2026-10-10T13:00:00Z", "s": {"101": {"103": 4.6}}, "p": {"101": {"103": round(pin_now["101"]["103"] * 1.08, 3)}}}}
        stake_fx = {"fx1": fixture("stake", stake, self.start)}
        pin_fx = {"fx1": fixture("pinnacle", pin_now, self.start)}
        errs, stats, _, _ = E.find_errors(stake_fx, pin_fx, CFG, META, {}, self.tour, self.t0, last)
        self.assertEqual(stats["steam"], 1)
        self.assertIn("Pinnacle moved", errs[0]["steam"])


if __name__ == "__main__":
    unittest.main()
