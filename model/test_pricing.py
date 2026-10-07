"""Tests for the pricing engine. Run: python3 -m unittest model/test_pricing.py -v"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pricing as P  # noqa: E402

CFG = P.load_config()
EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "example_candidates.json")


def binary(p):
    return {"win": p, "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "loss": 1 - p}


class Odds(unittest.TestCase):
    def test_conversions(self):
        self.assertAlmostEqual(P.to_decimal(-134), 1 + 100 / 134)
        self.assertAlmostEqual(P.to_decimal("+114"), 2.14)
        self.assertAlmostEqual(P.to_decimal("1.75"), 1.75)
        self.assertAlmostEqual(P.to_decimal("EVEN"), 2.0)
        self.assertEqual(P.decimal_to_american(2.5), 150)
        self.assertEqual(P.decimal_to_american(1.5), -200)
        for a in (-250, -110, 100, 145, 320):
            self.assertEqual(P.decimal_to_american(P.to_decimal(a)), a)
        with self.assertRaises(ValueError):
            P.to_decimal(0.9)

    def test_remove_vig(self):
        for method in ("power", "proportional"):
            f = P.remove_vig([1.91, 1.91], method)
            self.assertAlmostEqual(f[0], 0.5, places=9)
            f = P.remove_vig([P.to_decimal(-134), P.to_decimal(114), ], method)
            self.assertAlmostEqual(sum(f), 1, places=9)
            f3 = P.remove_vig([1.6, 4.3, 5.6], method)
            self.assertAlmostEqual(sum(f3), 1, places=9)
        # power takes more margin off the long shot than proportional does
        pw = P.remove_vig([1.25, 4.0], "power")[0]
        pr = P.remove_vig([1.25, 4.0], "proportional")[0]
        self.assertGreater(pw, pr)


class Models(unittest.TestCase):
    def dists(self):
        t = {"off": 100, "opp_sp": 4.15, "opp_sp_ip": 5.5, "opp_pen": 4.15}
        return {
            "mlb": P.mlb_dist({"home": t, "away": t}, CFG),
            "nhl": P.nhl_dist({"home_goals": 3.1, "away_goals": 2.7}, CFG),
            "soccer": P.soccer_dist({"home_goals": 1.6, "away_goals": 1.1}, CFG),
            "nfl": P.points_dist("NFL", {"margin": 3.0, "total": 45.5}, CFG),
            "nba": P.points_dist("NBA", {"margin": -4.0, "total": 224}, CFG),
            "ncaaf": P.points_dist("NCAAF", {"margin": 1.0, "total": 55}, CFG),
        }

    def test_distributions_sum_to_one(self):
        for name, d in self.dists().items():
            self.assertAlmostEqual(sum(d.margin.values()), 1, places=6, msg=name)
            self.assertAlmostEqual(sum(d.total.values()), 1, places=6, msg=name)

    def test_no_ties_where_games_cant_tie(self):
        for name in ("mlb", "nhl", "nba", "ncaaf"):
            self.assertLess(self.dists()[name].margin.get(0, 0), 1e-9, msg=name)

    def test_moneyline_sides_add_up(self):
        for name, d in self.dists().items():
            h = P.evaluate(d, "moneyline", "home", None)["win"]
            a = P.evaluate(d, "moneyline", "away", None)["win"]
            x = P.evaluate(d, "moneyline", "draw", None)["win"] if d.three_way else 0
            push = P.evaluate(d, "moneyline", "home", None)["push"]
            self.assertAlmostEqual(h + a + x + push, 1, places=6, msg=name)

    def test_home_field(self):
        t = {"off": 100, "opp_sp": 4.15, "opp_sp_ip": 5.5, "opp_pen": 4.15}
        d = P.mlb_dist({"home": t, "away": t}, CFG)
        p = P.evaluate(d, "moneyline", "home", None)["win"]
        self.assertTrue(0.52 < p < 0.545, p)
        g = {"xgf60": 2.55, "xga60": 2.55, "goalie_gsax60": 0}
        d = P.nhl_dist({"home": g, "away": g}, CFG)
        p = P.evaluate(d, "moneyline", "home", None)["win"]
        self.assertTrue(0.52 < p < 0.55, p)

    def test_half_line_complements(self):
        d = self.dists()["mlb"]
        h = P.evaluate(d, "spread", "home", -1.5)["win"]
        a = P.evaluate(d, "spread", "away", 1.5)["win"]
        self.assertAlmostEqual(h + a, 1, places=9)
        o = P.evaluate(d, "total", "over", 8.5)["win"]
        u = P.evaluate(d, "total", "under", 8.5)["win"]
        self.assertAlmostEqual(o + u, 1, places=9)

    def test_whole_line_push_matches(self):
        d = self.dists()["nfl"]
        h = P.evaluate(d, "spread", "home", -3)
        a = P.evaluate(d, "spread", "away", 3)
        self.assertAlmostEqual(h["push"], a["push"], places=9)
        self.assertAlmostEqual(h["win"], a["loss"], places=9)

    def test_nfl_key_numbers(self):
        d = self.dists()["nfl"]
        push3 = P.evaluate(d, "spread", "home", -3)["push"]
        push4 = P.evaluate(d, "spread", "home", -4)["push"]
        self.assertGreater(push3, 2 * push4)
        self.assertTrue(0.06 < push3 < 0.11, push3)

    def test_quarter_line_is_average_of_neighbours(self):
        d = self.dists()["soccer"]
        price = 1.95
        q = P.expected_value(P.evaluate(d, "spread", "home", -0.75), price)
        a = P.expected_value(P.evaluate(d, "spread", "home", -0.5), price)
        b = P.expected_value(P.evaluate(d, "spread", "home", -1.0), price)
        self.assertAlmostEqual(q, (a + b) / 2, places=9)
        q = P.expected_value(P.evaluate(d, "total", "over", 2.25), price)
        a = P.expected_value(P.evaluate(d, "total", "over", 2.0), price)
        b = P.expected_value(P.evaluate(d, "total", "over", 2.5), price)
        self.assertAlmostEqual(q, (a + b) / 2, places=9)

    def test_draw_no_bet(self):
        d = self.dists()["soccer"]
        o = P.evaluate(d, "draw_no_bet", "home", None)
        self.assertAlmostEqual(o["push"], P.evaluate(d, "moneyline", "draw", None)["win"], places=9)


class Betting(unittest.TestCase):
    def test_reshape_hits_target(self):
        d = P.points_dist("NFL", {"margin": 2.5}, CFG)
        shape = P.evaluate(d, "spread", "home", -3)
        for q in (0.4, 0.5, 0.55, 0.62):
            o = P.reshape(shape, q)
            self.assertAlmostEqual(P.breakeven_prob(o), q, places=9)
            self.assertAlmostEqual(o["push"], shape["push"], places=12)
            self.assertAlmostEqual(sum(o.values()), 1, places=9)

    def test_breakeven_matches_price(self):
        # at the fair price EV is zero, and the break-even of a price is 1/decimal
        d = P.soccer_dist({"home_goals": 1.5, "away_goals": 1.2}, CFG)
        o = P.evaluate(d, "spread", "home", -0.25)
        self.assertAlmostEqual(P.expected_value(o, P.fair_price(o)), 0, places=9)
        self.assertAlmostEqual(1 / P.fair_price(o), P.breakeven_prob(o), places=9)

    def test_kelly_binary_closed_form(self):
        p, d = 0.55, 2.0
        b = d - 1
        self.assertAlmostEqual(P.kelly_fraction(binary(p), d), (p * b - (1 - p)) / b, places=5)
        self.assertEqual(P.kelly_fraction(binary(0.45), 2.0), 0.0)

    def test_kelly_with_push(self):
        o = {"win": 0.5, "half_win": 0, "push": 0.08, "half_loss": 0, "loss": 0.42}
        d = 1.91
        b = d - 1
        closed = (o["win"] * b - o["loss"]) / (b * (o["win"] + o["loss"]))
        self.assertAlmostEqual(P.kelly_fraction(o, d), closed, places=5)

    def test_min_price(self):
        o = binary(0.59)
        m = P.min_price(o, 0.01)
        self.assertEqual(m, 1.72)
        self.assertGreaterEqual(P.expected_value(o, m), 0.01 - 1e-12)
        self.assertLess(P.expected_value(o, m - 0.01), 0.01)

    def test_adjustment_cap(self):
        adjs = [{"factor": str(i), "direction": "+", "size": "large"} for i in range(4)]
        items, total, capped = P.adjustments_logit(adjs, CFG)
        self.assertTrue(capped)
        self.assertAlmostEqual(total, CFG["adjustments"]["max_total_logit"])
        self.assertAlmostEqual(sum(i["logit_applied"] for i in items), total)
        _, total, capped = P.adjustments_logit([{"factor": "x", "direction": "-", "size": "small"}], CFG)
        self.assertFalse(capped)
        self.assertAlmostEqual(total, -CFG["adjustments"]["logit_size"]["small"])

    def test_clv(self):
        r = P.closing_line_value(1.75, {"home": -150, "away": 130}, "home")
        fair = P.remove_vig([P.to_decimal(-150), P.to_decimal(130)])[0]
        self.assertAlmostEqual(r["clv"], round(1.75 * fair - 1, 4))
        self.assertGreater(r["clv"], 0)


class EndToEnd(unittest.TestCase):
    def test_example_file(self):
        res = P.price_file(EXAMPLE, CFG)
        self.assertEqual(res["errors"], [])
        self.assertEqual(len(res["ranked"]), 4)
        scores = [r["score"] for r in res["ranked"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        pick = res["pick"]
        for k in ("date", "sport", "event", "bet", "market", "odds_decimal", "odds_american", "units", "confidence",
                  "model_prob", "implied_prob", "fair_prob", "ev", "min_odds_decimal", "model", "status", "candidates"):
            self.assertIn(k, pick)
        for k in ("odds_decimal", "units", "model_prob", "implied_prob", "fair_prob", "ev", "min_odds_decimal"):
            self.assertIsInstance(pick[k], (int, float), k)
        for k in ("model_prob", "implied_prob", "fair_prob"):
            self.assertTrue(0 < pick[k] < 1, k)
        steps = pick["model"]["steps"]
        self.assertEqual(steps[0]["key"], "market")
        self.assertEqual(steps[-1]["key"], "final")
        self.assertAlmostEqual(steps[-1]["prob"], pick["model_prob"], places=4)
        self.assertGreaterEqual(pick["units"], CFG["staking"]["min_units"])
        self.assertLessEqual(pick["units"], CFG["staking"]["max_units"])

    def test_market_only_and_no_edge(self):
        c = {"id": "t", "sport": "Tennis", "event": "A vs B", "home": "A", "away": "B", "market": "moneyline",
             "selection": "home", "price": 1.80,
             "market_odds": [{"book": "X", "prices": {"home": 1.83, "away": 2.0}}]}
        r = P.price_candidate(c, CFG)
        self.assertEqual(r["doc"]["model"]["method"], "market_only")
        self.assertTrue(r["doc"]["no_edge"])
        self.assertEqual(r["doc"]["units"], CFG["staking"]["min_units"])
        self.assertEqual(r["doc"]["confidence"], "Low")

    def test_line_mismatch_skipped(self):
        c = {"id": "t", "sport": "NFL", "home": "H", "away": "A", "market": "spread", "selection": "home", "line": -3,
             "price": -110, "model_inputs": {"margin": 3.5},
             "market_odds": [{"book": "X", "line": -3, "prices": {"home": -110, "away": -110}},
                             {"book": "Y", "line": -2.5, "prices": {"home": -125, "away": 105}}]}
        r = P.price_candidate(c, CFG)
        self.assertEqual(len(r["doc"]["model"]["books"]), 1)
        self.assertTrue(any("different line" in w for w in r["doc"]["model"]["warnings"]))


if __name__ == "__main__":
    unittest.main()
