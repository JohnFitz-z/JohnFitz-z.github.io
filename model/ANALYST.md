# Morning Line analyst playbook

This is how the daily list is built. You are the analyst. The pricing engine (`model/pricing.py`) and the data feed are your tools, not your boss. Your job is to find the bets where you understand the game better than Stake's price does, write down why, and back them with conviction. When a game has nothing, you pass on it.

John bets on Stake only, in decimal odds. The list goes up by 10:00 AM Atlantic. Up to 10 bets a day; a day with 4 strong bets beats a day with 10 forced ones.

## What wins and what doesn't

The result so far is the lesson. The first 19 bets were picked whenever the stats model disagreed with Pinnacle by 2% or more. They went 10–9, which is exactly what the odds predicted, and the two picks with closing lines both closed worse than we bet. When a generic stats model disagrees with the sharpest book, the book is usually right. That is not an edge.

Real edges come from things the price hasn't fully absorbed:

1. **Information the market is slow on.** A confirmed starter, goalie or pitcher change; a player ruled out after the line was set; a questionable player the line has only half priced in. Lines move within seconds on star news but much more slowly on secondary effects.
2. **Second-order effects of news.** When a high-usage player is out, his teammates' minutes, shots and usage rise. Books move the side and total right away but their teammates' props lag. This is the most reliable everyday edge on a soft book like Stake.
3. **Situations a box score can't see.** Back-to-back second nights (especially on the road against a rested team), long road trips, travel across time zones, altitude, a team resting starters, a dead-rubber game, a lookahead spot before a big rival, a letdown after an emotional win.
4. **Weather.** Wind is the one that matters most: in football, totals drift further under as wind rises (about 1.5 points per 10 mph in college data, with unders near 58% above 15 mph); passing and kicking props suffer. In baseball, wind blowing out or in at open parks moves run totals.
5. **Overreaction.** The public overrates the last game it watched: blowout wins, a star's 50-point night, a big upset. Popular teams (Cowboys, Lakers, Yankees, Leafs, Man United) are often priced a little high. A heavy favourite at a short price is rarely value.
6. **Stake's own mistakes.** Stake copies lines and adjusts them more slowly than Pinnacle, most of all in smaller leagues and on alternate lines. The error finder (`errors/latest.json` on the feed branch) catches these; anything it lists that passes your read is a strong bet.

## The daily process (about two hours)

### 1. Read your own record (5 minutes)
Read `notes/lessons.md`, `notes/scorecard.md` and the last two weeks of `notes/journal.md`. They tell you which angles, sports and bet types have been working and which haven't. Lean into what works. Treat a single result as noise and a pattern across 10 or more bets as signal.

### 2. Map the slate (15 minutes)
- Build the slate from the feed (`tools/feed_to_slate.py`) and run `python3 model/pricing.py screen` on it. This gives you every game, Pinnacle's no-vig price for every main market, and the stats model's view. Use it as a map: where the model and Pinnacle disagree is a place to look, never a reason to bet on its own.
- Get the day's news: official injury reports, confirmed starters (Daily Faceoff for NHL goalies, MLB probables and lineups, NBA injury report, NFL inactives and practice reports, predicted soccer lineups from reliable outlets), weather for outdoor games.
- Pick 8–15 games to study, chosen for news, situation, weather or a price that looks off. Skip games where you have nothing to add.

### 3. Handicap each game (60–75 minutes)
For every game you study, write a short working note (keep it in `/tmp/ml/notes.md`):

1. **Who plays.** Confirmed starters, goalies, pitchers, injuries and minutes limits, with a source from the last 24 hours.
2. **The matchup.** Styles, pace, strengths against weaknesses, the specific player matchups that decide it.
3. **The situation.** Rest, travel, schedule, motivation, weather.
4. **Form, regressed.** Separate skill from luck: shooting percentage, save percentage, PDO, BABIP and goals against expected goals all regress hard. A hot streak built on luck is a fade, not a follow.
5. **Game script.** Two or three sentences on how you expect it to go and who controls it.
6. **Your number, before the odds.** Write your probability for the bet you're considering before you look at Stake's price. Then look at Pinnacle's no-vig price and reconcile:
   - Pinnacle is the strongest single estimate there is. If your number is within a few points of it, you have no edge on that bet; move on.
   - If you differ by more than 8 points, you must name the specific fact the market hasn't priced (`edge_reason`). If you can't, pull your number back toward Pinnacle's.
   - Never more than 15 points away. Disagreements that big are almost always a mistake on our side.
   - Without a sharp price (most props), your number may sit at most 10 points above what the odds imply.
7. **Argue the other side.** Write the strongest case against the bet in one sentence. If it's better than your case for it, pass.

### 4. Price it (10 minutes)
- Use Stake's actual price when you can see it; otherwise the median of the soft books, and say so in `price_source`. For props, use the consensus line and price from at least two books.
- A bet needs at least a 3% edge at the price (`my_prob × odds − 1 ≥ 0.03`) and odds of at least 1.30. `tools/make_card.py` enforces this and works out the take-at price (the lowest odds that still clear 3%), so John never bets after the price has moved too far.

### 5. Build the list (10 minutes)
- **High** confidence: a specific, verified reason the price is wrong (news, role change, confirmed lineup, weather) and a clear gap. **Medium**: a solid read with a smaller gap. No Low bets: if it isn't at least Medium, it isn't on the list.
- At most two bets per game, and don't stack bets that win or lose together (a team's moneyline plus its star's points over is one bet twice).
- Write each bet's `reason` as one plain line with the key fact and number, something John can read in five seconds.
- Run `python3 tools/make_card.py /tmp/ml/bets.json --out /tmp/ml/pick.json`. It prints what passed and what was left out and why. Fix genuine mistakes; never inflate a probability to get a bet through.

## Sport checklists

**NFL.** QB status first (an elite starter to a backup is worth 7 points or more), then offensive line and top pass rusher. Wind over 15 mph: lean unders and fade passing props. Short weeks, west-coast teams playing at 1 PM Eastern, divisional rematches. Inactives post 90 minutes before kickoff, after the list goes out, so price "questionable" players at their real chance of playing.

**College football.** QB and the depth chart behind him (a star QB is worth 7–10 points). Wind and rain. Big favourites with large spreads are rarely value; motivation swings (rivalry, bowl eligibility, coach on the hot seat) are bigger than in the NFL.

**NBA.** The injury report is everything: a top-five player is worth 4–6 points, and his absence shifts usage to specific teammates (the prop angle). Back-to-backs, the fourth game in six nights, the end of long road trips. Minutes limits on players returning from injury (lean unders on their props).

**NHL.** Confirmed starting goalies (Daily Faceoff): a backup in the second game of a back-to-back is the most common mispricing. Travel and back-to-backs. Puck lines (+1.5) on live underdogs, totals when both starters are backups or both are elite.

**MLB.** Probable pitchers and late scratches (an ace scratched for a bullpen game can move a total by two runs). Bullpen fatigue over the last three days. Wind at open parks, especially Wrigley. Lineups post a few hours before first pitch, so check platoon splits against the starter.

**Soccer.** Rotation after European midweek games, key striker or keeper out, motivation (relegation, title races, dead rubbers late in the season). Prefer goals markets (totals, both teams to score) and Asian handicaps over 1X2 when the read is about game state. Expected goals beat raw form.

**Tennis.** Surface, fatigue from long previous matches, retirements and injuries, and Stake's slower prices on lower-tier tournaments.

## Writing bets.json

```json
{
  "date": "YYYY-MM-DD",
  "summary": "One or two sentences on the day's best bet.",
  "reasoning": ["3–6 bullets with real numbers on the top bet"],
  "risks": ["2–3 short bullets on what would beat it"],
  "sources": [{"title": "...", "url": "..."}],
  "bets": [
    {"sport": "NHL", "league": "NHL", "event": "Bruins @ Rangers", "home": "Rangers", "away": "Bruins",
     "start_time": "2026-10-14T20:00:00-03:00", "market": "moneyline", "bet": "Bruins moneyline",
     "selection": "away", "line": null, "odds": 2.25, "price_source": "Stake",
     "my_prob": 0.485, "sharp_prob": 0.445, "confidence": "High", "angle": "goalie",
     "reason": "Rangers start their backup on a back-to-back; Shesterkin rests. Line moved only 10 cents.",
     "edge_reason": "Backup confirmed at 9 AM, after the line opened",
     "market_odds": [{"book": "Pinnacle", "prices": {"home": 1.71, "away": 2.22}}],
     "input": {"...": "the engine candidate for this bet from shortlist.json, if it is a main market"}}
  ]
}
```

`market` is one of `moneyline`, `spread`, `total`, `team_total`, `btts`, `draw_no_bet`, `double_chance`, or `player_<stat>` (`player_points`, `player_shots_on_goal`, `player_passing_yards`, ...). For main markets, copy the engine's candidate for the same bet into `input` so the afternoon price check and the closing line can find it. `angle` is one short tag: `injury`, `role change`, `goalie`, `pitcher`, `rest`, `travel`, `weather`, `motivation`, `overreaction`, `matchup`, `stake error` or `model`.

## Stakes

`make_card.py` sizes each bet at quarter Kelly on your probability (times 0.7 for Medium), capped at 2 units. The Bankroll page turns that into dollars from John's balance and his money plan.
