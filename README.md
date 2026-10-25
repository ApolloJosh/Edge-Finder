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
7. Logged something wrong? Every bet on Results has **Edit** (the stake; for Kalshi, what you spent and the
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

- **Fair**: the sharp books' chance of the pick hitting, margin removed. Two de-vig methods are
  computed and the one less generous to your side is used. Lines need 2 sharp books.
- **Pick'em**: flagged when Fair beats an entry's per-pick breakeven by 1 point. *Lowest bar* is
  the app's easiest entry; *Clears* lists every entry it beats.
- **Best entries**: top flagged picks on one app, one per game (picks in the same game are
  correlated and can pay less), with the entry's expected return.
- **Fliff**: flagged at 3%+ expected value at Fliff's price.
- **Kalshi**: after Kalshi's fee (0.07 × P × (1 − P) a share, what buying by the dollar costs); flagged at
  3%+ return with 5+ contracts on offer. A dollar stake logs as fractional shares, the way Kalshi fills it;
  with one Kalshi pick selected you can type the exact shares Kalshi shows before saving.
- **adj**: a sharp line sat a little off this one (say 24.5 vs 23.5), so its price was moved using
  the stat's typical spread. Exact matches are stronger.
- **Gridiron Edge** (NFL): its probability at the book's line plus EDGE. *agrees* (55%+),
  *check news* (45% or less), *runs high* (Pass Yds, Pass+Rush, Rush+Rec, RB receptions, TE Rec
  Yds still sit too high in Gridiron Edge). It never decides what's flagged.

Breakevens today: PrizePicks Flex 6 54.2%, Power 5 54.9%, Power 2 57.7%; Underdog 3-pick at 6x 55.0%.

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
