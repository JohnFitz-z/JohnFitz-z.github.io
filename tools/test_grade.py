"""Tests for the no-AI grader (run: python3 -m unittest tools/test_grade.py)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grade as G  # noqa: E402


class Settle(unittest.TestCase):
    def test_moneyline_and_draws(self):
        self.assertEqual(G.settle_scores("moneyline", "home", None, 5, 3), "won")
        self.assertEqual(G.settle_scores("moneyline", "away", None, 5, 3), "lost")
        self.assertEqual(G.settle_scores("moneyline", "draw", None, 1, 1), "won")
        self.assertEqual(G.settle_scores("moneyline", "home", None, 1, 1), "lost")      # soccer 1X2 side on a draw
        self.assertEqual(G.settle_scores("moneyline_f5", "home", None, 2, 2), "push")   # first-five tie
        self.assertEqual(G.settle_scores("draw_no_bet", "away", None, 0, 0), "void")

    def test_spreads_and_quarter_lines(self):
        self.assertEqual(G.settle_scores("spread", "home", -1.5, 3, 1), "won")
        self.assertEqual(G.settle_scores("spread", "home", -1.5, 3, 2), "lost")
        self.assertEqual(G.settle_scores("spread", "away", 1.5, 3, 2), "won")
        self.assertEqual(G.settle_scores("spread", "away", 7.0, 24, 17), "push")
        self.assertEqual(G.settle_scores("spread", "home", -0.25, 1, 1), "half_lost")
        self.assertEqual(G.settle_scores("spread", "home", -0.75, 2, 1), "half_won")

    def test_totals(self):
        self.assertEqual(G.settle_scores("total", "under", 2.75, 4, 1), "lost")
        self.assertEqual(G.settle_scores("total", "under", 2.75, 2, 1), "half_lost")   # 3 goals: 2.5 loses, 3.0 pushes
        self.assertEqual(G.settle_scores("total", "over", 2.75, 2, 1), "half_won")
        self.assertEqual(G.settle_scores("total", "over", 6.0, 4, 2), "push")
        self.assertEqual(G.settle_scores("team_total", "under", 3.5, 3, 7, "away"), "lost")
        self.assertEqual(G.settle_scores("btts", "yes", None, 2, 1), "won")

    def test_units(self):
        self.assertEqual(G.result_units("won", 1.25, 2.15), 1.44)
        self.assertEqual(G.result_units("half_lost", 1.0, 1.9), -0.5)
        self.assertEqual(G.result_units("void", 1.0, 1.9), 0.0)

    def test_kind_and_names(self):
        self.assertEqual(G.kind_of({"market": "Puck line"}), "spread")
        self.assertEqual(G.kind_of({"market_key": "player_points"}), "player_points")
        self.assertEqual(G.kind_of({"input": {"market": "total_f5"}}), "total_f5")
        self.assertTrue(G.name_match("Brewers", "Milwaukee Brewers"))
        self.assertTrue(G.name_match("Atlético Madrid", "Atletico Madrid"))
        self.assertFalse(G.name_match("Rangers", "Texas Rangers FC Dallas") and G.name_match("Rangers", "Glasgow"))


if __name__ == "__main__":
    unittest.main()
