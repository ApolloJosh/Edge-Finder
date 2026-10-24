# Edge Finder

Prices PrizePicks, Underdog, Fliff and Kalshi player props against the sharp books'
fair odds and flags the few worth betting. NBA and NFL. On NFL days it shows
Gridiron Edge's read beside each pick as a second opinion.

It runs itself on GitHub Actions and publishes the board to GitHub Pages, so it works
from your phone with your Mac asleep. It only reads prices. **It never places a bet.**

**Board:** https://apollojosh.github.io/Edge-Finder/

## How it runs

Every 15 minutes from about 10 AM to 1 AM Central, a GitHub Actions run:

1. **Pulls each game twice**: about 90 minutes before tip (the day's news) and about 30
   minutes before (after lineups post). Games are grouped by tip time, so a 6:00 and a
   9:00 slate each get their own pulls.
2. **Takes a closing snapshot** about 30 minutes before every game you bet, pulling only the
   markets you bet. That's what closing line value (CLV) is measured against.
3. **Runs any commands you sent as issues** (log a bet, record a result, refresh).
4. **Republishes the site** if anything changed.

On NFL game days it also opens Gridiron Edge in a headless browser, lets it scan, clicks
**Export for Edge Finder**, and loads the file, at most every 3 hours.

The database lives on the repo's `state` branch as a single commit that's replaced each run,
so the repo doesn't grow. Lines for players you bet are kept for good; everything else is
pruned after 3 days.

## One-time setup

1. **Odds API key**: get a free key at [the-odds-api.com](https://the-odds-api.com), then in this repo:
   Settings → Secrets and variables → Actions → New repository secret → name `ODDS_API_KEY`.
2. **Pages**: Settings → Pages → Source: **GitHub Actions**.
3. **Gridiron Edge** needs v17 or later pushed (the Export for Edge Finder button).

## Using it

1. Open the board on your phone. Flagged picks beat the sharp market.
2. Tick the picks you actually play, pick the entry type and stake, tap **Log bet on GitHub**,
   then **Submit** on the issue it opens. A run starts right away; Edge Finder replies on the
   issue with the logged bet within a couple of minutes and closes it.
3. When a bet settles, open **Bets & CLV** and tap Win / Loss / Push. For a flex entry that
   partly hit, open an issue titled like `result 12 partial --hits 4`.
4. Lineup news? The home page has **Refresh NBA now** / **Refresh NFL now** (costs credits).

Only issues opened by the repo owner run anything, and only these commands:
`bet`, `result`, `refresh`, `ge-import`. Other issues are left alone.

The Actions tab → Edge Finder → **Run workflow** also offers: refresh-nba, refresh-nfl,
gridiron-edge (export now), probe (check every feed answers), site-only.

## Reading the board

- **Fair**: the sharp books' chance of the pick hitting, margin removed. Two de-vig methods are
  computed and the one less generous to your side is used. Lines need 2 sharp books.
- **Pick'em**: flagged when Fair beats an entry's per-pick breakeven by 1 point. *Lowest bar* is
  the app's easiest entry; *Clears* lists every entry it beats.
- **Best entries**: top flagged picks on one app, one per game (picks in the same game are
  correlated and can pay less), with the entry's expected return.
- **Fliff**: flagged at 3%+ expected value at Fliff's price.
- **Kalshi**: after the taker fee on 10 contracts; flagged at 3%+ return. Size = contracts offered.
- **adj**: a sharp line sat a little off this one (say 24.5 vs 23.5), so its price was moved using
  the stat's typical spread. Exact matches are stronger.
- **Gridiron Edge** (NFL): its probability at the book's line plus EDGE. *agrees* (55%+),
  *check news* (45% or less), *runs high* (Pass Yds, Pass+Rush, Rush+Rec, RB receptions, TE Rec
  Yds still sit too high in Gridiron Edge). It never decides what's flagged.

Breakevens today: PrizePicks Flex 6 54.2%, Power 5 54.9%, Power 2 57.7%; Underdog 3-pick at 6x 55.0%.

## Judging it: closing line value first

The Bets & CLV page shows average CLV overall, by app, by week, and for NFL by whether
Gridiron Edge agreed. Consistently positive CLV is the earliest real sign of an edge; win-loss
takes ~1,500 bets to mean much. **Keep stakes at $1–5 until CLV stays positive over a few
hundred bets.**

## Credits

Props cost 1 credit per market per game; all ten books count as one region.

| | Credits |
|---|---|
| NBA night, 8 games × 5 markets × 2 pulls | ~80 |
| NFL Sunday, 13 games × 7 markets × 2 pulls | ~180 |
| Closing snapshot, per game you bet | 1–3 |

The free 500 a month covers about a week of testing. Running every night needs the $30/month
plan (20,000 credits). Safety rails in `config.json` → `auto`: `daily_credit_cap` (250) and
`credit_floor` (keeps 40 in reserve for closing snapshots). Fewer pulls: set
`board_offsets_min` to `[30]`.

## Settings worth knowing (`config.json`)

- **entries**: payout tables. PrizePicks is from its help center (Oct 2026). **Underdog's are
  placeholders: check the app, fix them, and delete `"verify": true`.**
- **auto**: schedule offsets, caps, which leagues run.
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
- Results aren't graded automatically yet; tap them on the Bets page.
- Demons/goblins and Underdog boosted picks are left out (they live in separate markets).
- Scheduled GitHub runs can start a few minutes late at busy times, so "30 minutes before tip"
  is approximate. Use Refresh when news breaks.

## Files

- `edgefinder.py`: every command
- `ef/`: the code (`fair.py` holds the math, `auto.py` the schedule, `web.py` the site and issues)
- `tools/ge_export.py`: drives Gridiron Edge headlessly
- `.github/workflows/edge-finder.yml`: the schedule
- `tests/`: `python3 -m unittest discover -s tests`
