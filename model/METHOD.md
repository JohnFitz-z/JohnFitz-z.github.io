# Morning Line pricing method

This is the playbook the daily run follows. The research finds the facts; `pricing.py` turns them into probabilities, expected value, a stake and a minimum price using the same math every day. All tunable numbers live in `config.json`.

## Daily flow: screen wide, then dig deep

1. **Build the slate from the data feed.** Clone the `feed` branch and run `python3 tools/feed_to_slate.py <feed> --date TODAY --goalies goalies.json --out slate.json`. It writes every game today with moneyline, spread and total from every book (Pinnacle and Betfair Exchange included), NHL inputs from MoneyPuck and MLB inputs from the MLB Stats API. `goalies.json` is `{"Bruins": "Jeremy Swayman", ...}` from Daily Faceoff. Then add `model_inputs` for the games it lists as needing them (football and basketball ratings, soccer xG), using the bulk sources below. Add team totals and first-five markets by hand when a page lists them. If the feed is missing or stale (more than 6 hours old), build the slate by hand as below.
2. **Screen**: `python3 model/pricing.py screen slate.json --top 8 --out screen.json --candidates-out shortlist.json`. Every side of every market is priced; the best eight (at most two per game) go to the shortlist.
3. **Research the shortlist**: confirm starters, goalies, lineups and injuries; replace quick inputs with careful ones; add adjustments. Edit `shortlist.json` (it's a candidates file) and drop any candidate whose inputs turn out to be wrong or unavailable.
4. **Price**: `python3 model/pricing.py price shortlist.json --out priced.json --pick-out pick.json`. The top bet is the pick; the next two best from **other games** are backups 1 and 2, each with its own take-at price.
5. Add the written fields (summary, reasoning, risks, sources, notes on the candidates) to `pick.json` and save it.

## Data feed

A GitHub Action (`.github/workflows/feed.yml`) writes to the `feed` branch:

| File | What | When (Atlantic, summer) |
|---|---|---|
| `odds/latest.json`, `odds/DATE/morning.json` | Every game in every active sport, all books in the us and eu regions (Pinnacle, Betfair Exchange, DraftKings, FanDuel, BetMGM, Caesars, BetOnline...) | 6:35 AM |
| `odds/latest_afternoon.json` | Same, for the price check | 3:25 PM |
| `odds/closing/DATE.json` | Each game's last snapshot before it starts (10–40 minutes out) | every 30 min, 8:20 AM–3:50 AM |
| `stats/nhl.json` | MoneyPuck 5v5 xGF/60, xGA/60 by team and goalie GSAx, this season and last | 6:35 AM |
| `stats/mlb/latest.json` | Probable starters with their pitching lines, team batting and pitching, this season and last | 6:35 AM |
| `log/*.json`, `odds/usage.json` | What ran, errors, odds credits left | each run |

Odds come from The Odds API (secret `ODDS_API_KEY`). On the free plan (500 credits a month) the feed switches to a budget mode by itself: European books only (Pinnacle, Betfair Exchange, BetOnline, William Hill, Unibet...), the morning snapshot covers the sports with a game in the next 24 hours in priority order (NHL, NFL, NBA, MLB, NCAAF, then soccer) until that day's share of credits is used, the afternoon snapshot covers only the sports of today's pick and backups, and closing lines are saved only for today's pick and backups. `log/morning.json` lists any sport skipped for budget; those games need odds from the bulk pages. On a paid plan it fetches every sport, US and European books, and every game's closing line. Clone with `git clone --depth 1 --branch feed https://github.com/JohnFitz-z/JohnFitz-z.github.io.git <dir>`.

- Closing line value: `python3 tools/close_from_feed.py <feed> pick.json [--backup b1]` prints the `close` object, measured against Pinnacle's close (then Betfair, then the median).
- Price check: `python3 tools/close_from_feed.py <feed> today.json --fresh --out fresh.json` builds `fresh.json` from the afternoon snapshot.

Ranking uses expected log growth at the full Kelly stake. It rewards a big edge relative to the risk, so a +3% edge at 1.80 beats a +3% edge at 4.50. Candidates priced from the market alone can never show an edge (they copy the market and pay its margin), so they always rank below candidates with a model behind them. If no candidate has a positive edge, the engine still returns the best one at the minimum stake and flags it `no_edge`.

Screening dozens of bets and taking the best one favours bets where the model happens to be too optimistic. That's why the shortlist gets careful research before anything is posted, and why the closing line is tracked: if the picks don't beat the close over time, the model is overrating its edges.

## Slate file format

```json
{
  "date": "2026-10-09",
  "games": [
    {
      "id": "nhl-bos-mtl",
      "sport": "NHL",
      "league": "Regular season",
      "home": "Canadiens",
      "away": "Bruins",
      "start_time": "2026-10-09T19:00:00-03:00",
      "model_inputs": { "home": { "xgf60": 2.45, "xga60": 2.75, "goalie_gsax60": -0.1 },
                        "away": { "xgf60": 2.70, "xga60": 2.35, "goalie_gsax60": 0.3 } },
      "markets": [
        { "market": "moneyline", "books": [ { "book": "DraftKings", "prices": { "home": 120, "away": -142 } },
                                            { "book": "FanDuel", "prices": { "home": 118, "away": -140 } } ] },
        { "market": "total", "line": 6.5, "books": [ { "book": "DraftKings", "prices": { "over": 100, "under": -120 } } ] },
        { "market": "spread", "line": 1.5, "books": [ { "book": "DraftKings", "prices": { "home": -210, "away": 175 } } ] },
        { "market": "team_total", "team": "away", "line": 3.5, "books": [ { "book": "DraftKings", "prices": { "over": 105, "under": -125 } } ] }
      ]
    }
  ]
}
```

- For `spread`, `line` is the **home** team's line (home +1.5 here); the engine prices both sides.
- For `total` and `team_total`, `line` is the total. Team totals need `"team": "home"` or `"away"`.
- Markets: `moneyline`, `spread`, `total`, `team_total`, `draw_no_bet`, `btts`, and for MLB the first-five-innings versions `moneyline_f5`, `spread_f5`, `total_f5`, `team_total_f5`.
- The price used for each side is the median across the books listed. Every book entry needs all sides of the market at that line.
- See `example_slate.json` for a full worked slate.

## Bulk inputs: where to get them quickly

Use WebFetch on a page that lists every team and ask for the numbers back as JSON. Good sources (if one blocks, try the next):

| Need | Sources |
|---|---|
| Odds for the whole slate | Covers odds pages, VegasInsider odds pages, OddsShark, Action Network, ESPN scoreboard (moneyline, spread, total by book) |
| MLB probable starters | MLB.com probable pitchers, ESPN, Rotowire |
| MLB team offense (wRC+, or OPS+ as a stand-in) | FanGraphs team batting, Baseball-Reference team batting |
| MLB starter and bullpen quality (SIERA/xFIP, or FIP/ERA as a stand-in) | FanGraphs, Baseball-Reference, ESPN |
| MLB park factors | FanGraphs Guts, Baseball Savant |
| NHL 5v5 xGF/60 and xGA/60 | Natural Stat Trick team table, MoneyPuck |
| NHL starting goalies and GSAx/60 | Daily Faceoff starting goalies, MoneyPuck goalies |
| Soccer xG and xGA per match | FBref league stats, Understat, FotMob |
| NFL / NCAAF power ratings | ESPN FPI, SP+, Massey, Sagarin |
| NBA / WNBA ratings and pace | NBA.com or Basketball-Reference net rating, offensive and defensive rating, pace; ESPN BPI early in the season |
| NCAAB ratings | Bart Torvik, KenPom |
| CFL ratings | Season point differential per game |

For a projected total in points sports: NBA total ≈ average pace × (home ORtg + away DRtg + away ORtg + home DRtg) / 200; football totals from each team's points scored and allowed per game, weighted toward recent games. Quick inputs only need to be roughly right; careful inputs come in the research step.

## Backups and the afternoon price check

The pick document carries `backups`: two bets from different games, each with its own odds, take-at price, units and EV. Only the main pick counts toward the record; backups are graded too so the bankroll tracker can follow whichever bet was placed.

At 3:53 PM a separate run gets fresh prices for the main pick and both backups and runs:

```
python3 model/pricing.py recheck pick.json --fresh fresh.json --out update.json
```

`fresh.json` holds the new prices per bet: `{"main": {"price": 1.85, "market_odds": [...]}, "b1": {...}, "b2": {...}}`. Use the same side keys as the bet's original `market_odds` (home/away, over/under, home/draw/away). If `price` is left out, the median of the books for the bet's selection is used. If `price` is more than 12% off that median, the bet gets a `warning` (usually a home/away mix-up) and is never recommended; fix the file and rerun. The output is a `price_check` block to merge into the pick: the current odds, EV and take-at price for each bet, and `recommend`: the first of main, backup 1, backup 2 that still has at least +1% EV at the current price, or `none`. The recorded odds of the pick don't change; the price check only says which bet to place now.

## Backtests

Settings are tuned on past seasons, not guessed. The "Backtest data" GitHub workflow downloads history to `backtest/` on the feed branch; `python3 tools/backtest/nhl.py <feed> --tune` replays every game using only what was known that morning and searches the settings.

NHL, October 2026 run (2022-23 to 2025-26, 5,248 games; log loss, lower is better):

| | Model | No-skill baseline |
|---|---|---|
| Moneyline (incl. OT/shootout) | 0.6685 | 0.6904 |
| Over/under 5.5 | 0.6819 | 0.6832 |
| Over/under 6.5 | 0.6889 | 0.6898 |

- The moneyline model has real skill and is well calibrated after tuning. Totals barely beat a flat rate, so NHL totals use 85% market / 15% model (`blend_overrides` in `config.json`).
- Tuned settings, now live: all-situation expected goals (better than 5v5 only), last season regressed 40% toward the league average, this season takes over at about 25 games, goalie GSAx weight 0.25 (was 1.0), home ice 1.04 / 0.975, league regulation goals 3.03.
- Tuned on 2022-25 and tested on 2025-26 alone, the new settings also beat the old ones, so this isn't overfitting.
- Next: with historical Pinnacle prices, fit the model-vs-market weight per sport and the minimum edge to bet.

## How a probability is built

| Step | What happens |
|---|---|
| Market | Each book's two-way or three-way prices have the margin removed (power method). When a sharp book prices the market (Pinnacle, Betfair Exchange, Circa, Matchbook; weights in `config.json`), the sharp margin-free price is the market's fair probability, because sharp prices are the best public forecast. Otherwise it's the median across books. The bet price in a slate is the median of the non-sharp books, since that's closer to what Stake offers. |
| Model | A score model for the sport prices the exact bet, including pushes on whole lines, half results on quarter lines, extra innings and overtime. |
| Blend | Market and model are combined in log-odds space, 50% market and 50% model. |
| Adjust | Up to four researched factors the model can't see. Small, medium and large move the log-odds by 0.04, 0.08 and 0.12 (about 1, 2 and 3 points near 50%). The total is capped at 0.20 (about 5 points). |
| Bet | Expected value at the real price, quarter-Kelly stake (1 unit = 1% of bankroll, 0.25u to 2u), and the lowest price that still gives at least +1% EV ("take it at"). |

Confidence comes from EV: High at +4% or more, Medium at +2% to +4%, Low below +2%.

Bad-input guard: when the model is more than 0.35 in log-odds (about 9 points near 50%) away from the market, the bet is marked as suspect and ranks below every normal bet. A gap that big is almost always a wrong input (starter, goalie, home/away swap, stale or stand-in stats), not an edge. Check the inputs; if they're right after research, the gap stands but the bet still ranks below normal ones.

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

First-five-innings markets use the same inputs but count only the opposing starter (plus the bullpen if `opp_sp_ip` is under 5), which is where a big starter mismatch shows up most clearly. A tie after five innings is a push on the first-five moneyline.

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

- `market`: `moneyline`, `spread`, `total`, `team_total`, `draw_no_bet` or `btts`; for MLB also `moneyline_f5`, `spread_f5`, `total_f5` and `team_total_f5` (first five innings, a tie after five is a push). Team totals also need `"team": "home"` or `"away"`.
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

`python3 -m unittest model/test_pricing.py` runs the tests. They cover odds conversion, margin removal, every sport model, team totals, first-five innings, pushes, quarter lines, Kelly staking, the minimum price, slate screening, backups, the price recheck and the worked examples in `example_candidates.json` and `example_slate.json`.
