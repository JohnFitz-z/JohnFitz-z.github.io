# Morning Line pricing method

This is the playbook the daily run follows. The research finds the facts; `pricing.py` turns them into probabilities, expected value, a stake and a minimum price using the same math every day. All tunable numbers live in `config.json`.

## Daily flow

1. Shortlist 4–5 candidate bets from today's slate.
2. For each one, collect market prices from at least two books, the sport model inputs below, and up to four adjustments.
3. Write them to `candidates.json` in the format below.
4. Run `python3 model/pricing.py price candidates.json --out priced.json --pick-out pick.json`.
5. The top-ranked candidate is the pick. Add the written fields (summary, reasoning, risks, sources) to `pick.json` and save it.

Ranking uses expected log growth at the full Kelly stake. It rewards a big edge relative to the risk, so a +3% edge at 1.80 beats a +3% edge at 4.50. If no candidate has a positive edge, the engine still returns the best one at the minimum stake and flags it `no_edge`.

## How a probability is built

| Step | What happens |
|---|---|
| Market | Each book's two-way or three-way prices have the margin removed (power method). The median across books is the market's fair probability. |
| Model | A score model for the sport prices the exact bet, including pushes on whole lines, half results on quarter lines, extra innings and overtime. |
| Blend | Market and model are combined in log-odds space, 60% market and 40% model. The market is usually right, so it gets the larger share. |
| Adjust | Up to four researched factors the model can't see. Small, medium and large move the log-odds by 0.04, 0.08 and 0.12 (about 1, 2 and 3 points near 50%). The total is capped at 0.20 (about 5 points). |
| Bet | Expected value at the real price, quarter-Kelly stake (1 unit = 1% of bankroll, 0.25u to 2u), and the lowest price that still gives at least +1% EV ("take it at"). |

Confidence comes from EV: High at +4% or more, Medium at +2% to +4%, Low below +2%.

## Sport models and the inputs to collect

Give either the direct expected scores or the building blocks. Direct values must already include home advantage. Building blocks get home advantage added by the code.

### MLB: runs model (negative binomial)

```json
"model_inputs": {
  "home": { "off": 104, "opp_sp": 4.60, "opp_sp_ip": 4.5, "opp_pen": 3.70 },
  "away": { "off": 106, "opp_sp": 3.50, "opp_sp_ip": 5.5, "opp_pen": 3.60 },
  "park": 95
}
```

- `off`: the batting team's wRC+ (100 = average). Use the last 30 days blended with the season if there's a big gap, and use the split against the starter's hand when it's available.
- `opp_sp`: the opposing starter's ERA estimator, preferably SIERA or xFIP (season, or blended with last season early in the year).
- `opp_sp_ip`: innings the opposing starter is expected to pitch. Use about 5.5 for a normal start, 4–4.5 for a short leash or opener, and 6+ for an ace on full rest.
- `opp_pen`: the opposing bullpen's xFIP or SIERA. Lower it when the best relievers are rested and raise it when they're unavailable.
- `park`: home park run factor (100 = neutral).
- Or give direct values: `"home_runs": 4.4, "away_runs": 3.9`.

Totals and run lines include extra innings (the winner finishes one run ahead).

### NHL: goals model (Poisson)

```json
"model_inputs": {
  "home": { "xgf60": 2.40, "xga60": 2.70, "goalie_gsax60": -0.10 },
  "away": { "xgf60": 2.60, "xga60": 2.30, "goalie_gsax60": 0.35 }
}
```

- `xgf60` / `xga60`: 5v5 expected goals for and against per 60 minutes (score and venue adjusted if possible), from Natural Stat Trick, MoneyPuck or Evolving-Hockey.
- `goalie_gsax60`: that team's confirmed or expected starter's goals saved above expected per 60 (positive = good). Confirm the starter before using it.
- Or give direct values: `"home_goals": 3.1, "away_goals": 2.7` (regulation).

Moneylines, puck lines and totals include overtime and the shootout, with a shootout win counted as one goal.

### Soccer: goals model (Poisson with Dixon-Coles)

```json
"model_inputs": {
  "home": { "xgf": 2.0, "xga": 0.9 },
  "away": { "xgf": 1.5, "xga": 1.4 },
  "league_avg": 1.4
}
```

- `xgf` / `xga`: non-penalty xG for and against per match (FBref, Understat, FotMob), weighted toward recent matches.
- `league_avg`: average goals per team per match in that league.
- Or give direct values: `"home_goals": 1.7, "away_goals": 1.0`.

Covers the 90-minute result (home, draw, away), draw no bet, handicaps including quarter lines, totals and both teams to score.

### NFL, CFL, NCAAF, NBA, WNBA, NCAAB: points model

```json
"model_inputs": { "home_rating": 5.0, "away_rating": 4.5, "total": 48.5 }
```

- `home_rating` / `away_rating`: points better than an average team on a neutral field, from a reputable power rating (for example ESPN FPI, Massey, Sagarin, KenPom, Torvik, or net rating for the NBA). Adjust for confirmed injuries to key players before entering it.
- Home field is added from `config.json` (NFL 1.6, NBA 2.2, NCAAB 3.0 and so on). Add `"neutral": true` for neutral sites or `"hfa": 1.0` to override.
- `total`: your projected combined score, from pace and efficiency. Without it, totals are priced from the market alone.
- Or give direct values: `"margin": 3.5` (home minus away, home field included).

NFL and CFL margins are reweighted toward the key numbers 3, 7, 10 and 14, so pushes on whole-number spreads are priced properly.

### Tennis, MMA and anything else

No score model. The pick is priced from the market, with adjustments only.

## Adjustments

Use them only for things the model inputs don't already include. If the starting pitcher's numbers are in `opp_sp`, his recent form isn't an adjustment unless something has changed that the numbers don't show yet.

Good adjustments: late lineup or injury news not yet in the ratings, a bullpen used heavily the previous nights, travel and rest (back-to-backs, short weeks, long road trips), weather (wind at Wrigley, heavy rain), a team that has clinched or is eliminated, a confirmed goalie change after the inputs were set.

```json
"adjustments": [
  { "factor": "Brewers bullpen used heavily the last two nights", "direction": "+", "size": "small",
    "note": "Top three relievers threw 60+ pitches combined in Games 2 and 3." }
]
```

`direction` is relative to the selection: `+` makes the bet more likely to win. Use small unless the evidence is strong.

## candidates.json format

```json
{
  "date": "2026-10-07",
  "candidates": [
    {
      "id": "short-unique-id",
      "sport": "MLB",
      "league": "NLDS Game 4",
      "event": "Brewers @ Padres",
      "home": "Padres",
      "away": "Brewers",
      "start_time": "2026-10-07T23:08:00-03:00",
      "market": "moneyline",
      "selection": "home",
      "line": null,
      "price": 1.80,
      "market_odds": [
        { "book": "DraftKings", "prices": { "home": -125, "away": 105 } },
        { "book": "FanDuel",    "prices": { "home": -128, "away": 108 } }
      ],
      "model_inputs": { },
      "adjustments": [ ]
    }
  ]
}
```

- `market`: `moneyline`, `spread`, `total`, `draw_no_bet` or `btts`.
- `selection`: `home`, `away`, `draw`, `over`, `under`, `yes` or `no`.
- `line`: the selection's own line. For a spread that's the handicap on the chosen side (Bills +3 is `"selection": "away", "line": 3`). For a total it's the total. Use `null` for moneylines.
- `price`: the price to bet, in decimal or American. Use the consensus best price that's widely available; Stake is usually close to it.
- `market_odds`: every outcome of the market for each book, at the same line as the bet (a book quoting a different line is skipped). Soccer moneylines need all three outcomes. Draw no bet uses the three-way prices.
- `start_time`: ISO 8601 with the Atlantic offset. Check the time zone conversion.

## Closing line value

When a pick is graded, look up the closing prices for both sides of the same market (Covers, OddsShark, Action Network and ESPN game pages list them) and run:

```
python3 model/pricing.py clv --taken 1.75 --selection home --close home=-150 away=+130
```

Save the result on the pick as `close`: `{"odds_decimal": 1.667, "fair_prob": 0.584, "clv": 0.022, "source": "Covers"}`. Positive CLV means the price moved our way after the pick. Over many picks that's the best early sign of a real edge, well before the win-loss record says anything. If a reliable closing price can't be found, leave `close` out rather than guessing.

## Checks

`python3 -m unittest model/test_pricing.py` runs the tests. They cover odds conversion, margin removal, every sport model, pushes, quarter lines, Kelly staking, the minimum price and the worked example in `example_candidates.json`.
