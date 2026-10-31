# Edge Finder

Prices PrizePicks, Underdog, Fliff and Kalshi player props against the sharp books'
fair odds and flags the few worth betting. NBA and NFL. On NFL days it shows
Gridiron Edge's read beside each pick as a second opinion.

It runs itself on GitHub Actions and publishes the board to GitHub Pages, so it works
from your phone with your Mac asleep. It only reads prices. **It never places a bet.**

**Board:** https://apollojosh.github.io/Edge-Finder/

## How it runs

**Lines are pulled only when you tap Run NBA or Run NFL on Home**, so credits go only to
days you bet. Each button shows how many games a run covers (every game in the next 16
hours), the most it can cost, and when you last ran it. Tap once to see the cost, again to
run; it warns you if you ran that league in the last 3 hours. The new board lands in about
3 minutes (4 for NFL, which runs Gridiron Edge first: it opens Gridiron Edge in a headless
browser, lets it scan, clicks **Export for Edge Finder**, and loads the file).

Every 15 minutes, a GitHub Actions run also does the free work:

1. **Checks what a Run would cost** (listing games is free) so the buttons stay current.
2. **Takes a closing snapshot** about 30 minutes before every game you bet, pulling only the
   markets you bet: about 1 credit a game. That's what closing line value (CLV) is measured
   against. Turn it off with `"closing_snapshots": false` in `config.json`, but then CLV
   can't be measured.
3. **Grades finished bets** from ESPN box scores.
4. **Runs anything the app sent** (a saved bet, a result, a run).
5. **Republishes the site** if anything changed.

To go back to automatic pulls, set `auto.board_offsets_min` to `[90, 30]` (minutes before tip).

The database lives on the repo's `state` branch as a single commit that's replaced each run,
so the repo doesn't grow. Lines for players you bet are kept for good; everything else is
pruned after 3 days.

## One-time setup

1. **Odds API key**: get a free key at [the-odds-api.com](https://the-odds-api.com), then in this repo:
   Settings → Secrets and variables → Actions → New repository secret → name `ODDS_API_KEY`.
2. **Pages**: Settings → Pages → Source: **GitHub Actions**.
3. **Gridiron Edge** needs v17 or later pushed (the Export for Edge Finder button).

## Using it

1. **Once per phone:** open the site, tap **Settings**, then **Create the key on GitHub**. GitHub opens with
   the key filled in; under *Repository access* pick **Only select repositories → Edge-Finder**, tap
   **Generate token**, copy it, paste it back in Settings and tap **Connect**. The key can only open issues
   on this repo, lasts a year, and stays on that device.
2. Open a board. Flagged picks beat the sharp market. Tick the picks you actually play, set the entry and
   stake, and tap **Save bet**. It shows on **Results** as "recording" and is recorded within a couple of
   minutes. (Behind the scenes the app files an issue that the next run reads, records and closes; you never
   need to look at it.)
3. Closing lines are captured before each game, and **results are graded automatically** from ESPN box
   scores once the game is final. A pick'em entry with a voided or pushed leg, or a player the box score
   doesn't list, is left for you: tap Win / Loss / Push on Results.
4. Lineup news? Tap Run again (it costs credits again).
5. **Robinhood (or any app without a price feed):** open **Check**, find the player, pick the stat, set the
   line Robinhood shows (60+ means Yes = 60 or more) and its price in cents. You get a plain **Take it** or
   **Skip it**, with the most it's worth paying. Bought it? Tap **I bought it** and copy the contracts and
   cost from Robinhood's order summary; it's tracked on Results like everything else. It prices yards,
   receptions, attempts and the NBA stats from the last Run; touchdown markets aren't priced. Fees are
   assumed at 1.5¢ a contract (`config.json` → `robinhood`), and Take it needs a 3% expected return.
6. A player's number wrong or missing? Each leg on Results has **Fix stat** (or **Enter result** when the box
   score didn't have the player). Type the final number, or tick **Didn't play**; the leg becomes hit, miss,
   push or void and the bet re-settles. **Undo my fix** hands it back to the box score.
7. Cashed out early? Open bets have a **Cash out** button: enter the full amount the app paid you back and the
   bet settles at that. The record counts cash outs on their own (won-lost-push · N cashed out); profit
   includes them. **Change cash out** fixes the amount later.
8. App paid something different (a push or void re-priced a pick'em entry)? **Edit** on a settled bet has
   **Paid out**: enter what the app paid and the result follows (win, push, partial or loss). Tapping **Win** on
   an entry with a pushed or voided leg asks what it paid instead of assuming the full multiplier.
9. Logged something wrong? Every bet on Results has **Edit** (the stake; for Kalshi, what you spent and the
   shares you got, straight from Kalshi's order history) and **Delete bet**, which asks first and can be
   undone from **Deleted bets** at the bottom of Results.

**Results** shows your record, profit, closing line value and leg hit rate; a profit-over-time chart and a
CLV trend; and what's working by app, entry type, stat, flagged-vs-your-own picks, and (NFL) whether
Gridiron Edge agreed. Filter by 7 days / 30 days / all and by league.

It also shows **how close each leg came**, because a miss by one is a different result from a miss by ten:

- Each leg on a bet card has a bar centered on the line: what it got, what it needed, and how far
  past or short it finished. A miss by exactly one (one assist, one catch, one yard) is a **hook 🪝**.
- Lost bets whose only miss was a hook say **🪝 one hook from $X**.
- **Hooks 🪝** counts them; **Avg finish vs line** is how far past the line your legs finished on
  average, in standard deviations of each stat, next to what the prices you took expected.
- **How close your legs landed** is a histogram of every graded leg: misses left of the line, hits right,
  with a dashed line for where the prices expected them to land. Legs piling up just left of the line are
  mostly bad luck rather than bad reads. Closeness settles faster than win-loss, but it's still noisy under
  ~50 legs, and CLV remains the main test.

No key on a device? Save still works through GitHub: the bottom sheet has "or log it on GitHub instead".

Only issues opened by the repo owner run anything, and only these commands:
`bet`, `bet-line`, `result`, `actual`, `edit`, `delete`, `restore`, `run` (or `refresh`), `ge-import`. An issue can carry several
command lines; they run in order. Other issues are left alone.

The Actions tab → Edge Finder → **Run workflow** also offers: run-nba, run-nfl,
gridiron-edge (export now), probe (check every feed answers), site-only.

## Reading the board

Each pick is one card: the player and pick, a **score**, and three numbers. Tap a card to select it; *Details*
has the game, the sharp lines and anything adjusted. The (i) buttons explain each part in the app.

- **Score (0–100)**: the default order under both *Edges* and *All*. It starts from the sharp fair chance,
  leans toward the model's read by `config.json` → `model.weight` (Gridiron Edge 25%; Full Court Edge 25% on
  rebounds only, where a backtest shows it helps) and asks how much of a bankroll the pick deserves at its price (Kelly). That rewards a bigger edge *and* a better chance of hitting: at the same
  edge, a 58% pick scores above a 40% one. 60+ is strong, 40–59 solid, under 40 thin.
- **Edge**: how much better the app's price is than fair. Kalshi: fair ÷ (ask + fee) − 1. Fliff: fair × odds − 1.
  Pick'em: fair ÷ the per-pick breakeven of the easiest entry it clears − 1.
- **Fair**: the sharp books' chance of the pick hitting, margin removed (the less generous of two de-vig
  methods). Lines need 2 sharp books.
- **GE / FCE**: the model's chance for the pick. Gridiron Edge for the NFL; Full Court Edge for the NBA
  (below). *agrees* at 55%+, *disagrees* / *check news* at 45% or less. Gridiron Edge's *runs high* markets
  don't move the score.
- **Edges** shows picks that clear the bar: Kalshi and Fliff at 2%+ (Kalshi with 5+ contracts on offer),
  pick'em when fair beats an entry's per-pick breakeven by half a point. **All** shows everything, ranked.
- **Sort**: best score, biggest edge, **by game** (grouped under each matchup), start time, or player.
- **adj**: a sharp line sat a little off this one (say 24.5 vs 23.5), so its price was moved using the stat's
  typical spread and trimmed for that.
- **Best pick'em entries** (folded at the top): flagged picks on one app, one per game, with expected return.

### Today's budget and suggested stakes

The bar under the title is today's budget: **$25 a day, $40 on NFL Sundays** (`config.json` → `budget`), minus
everything saved today. Suggested stakes split what's left across the best Kalshi and Fliff picks by score, one
per player and stat, with no more than 25% of the day on any one bet; the card shows *Bet $N* and the save bar
starts at it. A pick'em entry gets its own suggestion when you select it. Tap the bar to change today's number.

### Full Court Edge (NBA)

Edge Finder's own NBA projection, the NBA's answer to Gridiron Edge. Every scheduled run pulls a few more days of
ESPN box scores (free; newest first, back to the start of last season). For each player and stat it projects:

- **per-minute production**: recent games count more (half-life 10 games); last season's games count half
- **minutes**: recent games, half-life 5 games
- **opponent**: how much of that stat the opponent allows against the league average this season, pulled
  halfway to average (more, early on) and kept within ±15%
- **spread**: the player's own game-to-game spread blended with the stat's typical spread

and turns that into a chance for the line. Preseason games are left out. It doesn't know injuries or who's sitting
tonight, which the sharp books do.

**It moves the score on rebounds only.** `tools/fce_backtest.py` rebuilds every past NBA board as of its pull and
grades each line against that night's box score, resampling whole player-stat-games so repeated pulls of one
line don't count as extra evidence. On Oct 31 (1,312 player-stat-games over six nights, with all of last
season's box scores in):

| market | games | sharp fair | Full Court Edge | blend 25% | blend beats sharp in |
|---|---|---|---|---|---|
| Rebounds | 275 | 0.684 | 0.688 | **0.678** | 97% of resamples |
| Points | 305 | 0.693 | 0.744 | 0.698 | 7% |
| Pts + Reb + Ast | 246 | 0.691 | 0.741 | 0.696 | 14% |
| Assists | 228 | 0.679 | 0.720 | 0.685 | 6% |
| 3-pointers | 258 | 0.682 | 0.710 | 0.685 | 16% |

(log loss; lower is better). On rebounds the blend beat the sharp price on every night with rebound lines, and
the gap held where it mattered: when Full Court Edge sat 10+ points above fair, overs hit 62% against a fair
49%. Everywhere else the sharp price is better on its own. So `model.weight.nba` is
`{"default": 0, "player_rebounds": 0.25}`: half the best in-sample weight, to allow for luck, and other markets'
reads show on the cards without moving the score. One market out of five clearing the bar can still be chance;
re-run the backtest every week or two (Actions → Run workflow → fce-backtest) and pull rebounds back to 0 if it
stops holding, or add a market that starts to. Results also tracks its reads on your bets.

## Judging it: closing line value first

The Results page shows average CLV overall and over time, and for NFL by whether
Gridiron Edge agreed. Consistently positive CLV is the earliest real sign of an edge; win-loss
takes ~1,500 bets to mean much. **Keep stakes at $1–5 until CLV stays positive over a few
hundred bets.**

## Credits

Props cost 1 credit per market per game; all ten books count as one region.

| | Credits |
|---|---|
| Run NBA, 8 games × 5 markets | up to 40 |
| Run NFL, 13 games × 7 markets | up to 91 |
| Closing snapshot, per game you bet | 1–3 |

The real cost is often lower: a market only costs when a book lists it for that game. The free
500 a month covers a handful of runs. Betting most days needs the $30/month plan (20,000
credits). A run stops before spending anything if fewer credits are left than games to pull.
With automatic pulls switched on, `config.json` → `auto` also has `daily_credit_cap` and
`credit_floor`.

## Settings worth knowing (`config.json`)

- **entries**: payout tables. PrizePicks is from its help center (Oct 2026). **Underdog's are
  placeholders: check the app, fix them, and delete `"verify": true`.**
- **manual.hours_ahead**: how far ahead a Run looks (16 hours).
- **auto**: closing snapshots on/off, automatic pull offsets (off), caps, which leagues are checked.
- **books.sharp**: which books form the fair price, and their weights.
- **thresholds**: cushion over breakeven, Fliff/Kalshi minimum EV, sharp books required.
- **max_line_gap**: how far a sharp line may be from a book's line before it's ignored.
- **leagues.\*.markets**: which props to pull. Each extra market costs 1 credit per game per pull.

If a player's name doesn't match between books, add it to `aliases.json`.

## Running it on the Mac instead

Everything also works locally (`python3 edgefinder.py run nba`, `bet`, `watch`, `clv`).
Put the key in a `.env` file:

```bash
cd "$HOME/Documents/Claude/Projects/Edge-Finder" && [ -f .env ] || printf 'ODDS_API_KEY=paste-your-key-here\n' > .env; open -e .env
```

Local runs use their own database (`data/edgefinder.db`), separate from the one on GitHub.

## What's not covered yet

- **Sleeper** isn't in any reachable feed. Its lines usually track Underdog's.
- Demons/goblins and Underdog boosted picks are left out (they live in separate markets).
- GitHub runs can start a few minutes late at busy times, so a Run or a closing snapshot can
  land a little later than planned.

## Files

- `edgefinder.py`: every command
- `ef/`: the code (`fair.py` holds the math, `auto.py` the schedule, `web.py` the site and issues)
- `tools/ge_export.py`: drives Gridiron Edge headlessly
- `.github/workflows/edge-finder.yml`: the schedule
- `tests/`: `python3 -m unittest discover -s tests`
