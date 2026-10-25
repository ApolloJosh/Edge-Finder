"""The math: fair odds from sharp books, moving a probability to a nearby line,
pick'em breakevens, and the expected return of a whole entry.

Nothing here touches the network or the database, so it is all unit-tested.
"""
import math

from .util import N01

# ---------------------------------------------------------------- de-vig


def devig_pair(dec_over, dec_under):
    """Strip the bookmaker margin from a two-way price.

    Returns (multiplicative, power) fair probabilities for the OVER side.
    Multiplicative scales both sides down equally. Power raises both implied
    probabilities to the k that makes them sum to 1, which puts more of the
    margin on the longshot. They agree near 50/50 and drift apart at the
    extremes, so the board takes the less generous of the two for whichever
    side it is pricing.
    """
    po, pu = 1.0 / dec_over, 1.0 / dec_under
    total = po + pu
    mult = po / total
    if total <= 1.0:  # no margin (or an arb) - nothing to remove
        return mult, mult
    lo, hi = 1.0, 20.0
    for _ in range(80):
        k = (lo + hi) / 2
        if po ** k + pu ** k > 1.0:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    return mult, po ** k


# ---------------------------------------------------------------- distributions

# Spread of each stat around its line, used ONLY to move a sharp probability a
# short distance to a book's different line. Never used to invent a probability
# from nothing.
#   NBA counts: sd = k * sqrt(line). Points k=1.40 gives sd 7.0 at 25 and 4.8 at
#   12, which matches typical game-to-game spread; rebounds/assists/threes are
#   close to Poisson (k~1). Starting values - calibrate from closing lines later.
#   NFL: sd = cv * line, cv measured by Gridiron Edge across 2024-25
#   (docs/markets.md in that repo).
STAT_MODELS = {
    # NBA
    "player_points": ("sqrt", 1.40),
    "player_rebounds": ("sqrt", 1.10),
    "player_assists": ("sqrt", 1.15),
    "player_threes": ("sqrt", 1.00),
    "player_blocks": ("sqrt", 1.00),
    "player_steals": ("sqrt", 1.00),
    "player_turnovers": ("sqrt", 1.00),
    "player_points_rebounds_assists": ("sqrt", 1.45),
    "player_points_rebounds": ("sqrt", 1.40),
    "player_points_assists": ("sqrt", 1.40),
    "player_rebounds_assists": ("sqrt", 1.20),
    # NFL (cv from Gridiron Edge docs/markets.md)
    "player_pass_yds": ("cv", 0.342),
    "player_pass_rush_yds": ("cv", 0.326),
    "player_pass_attempts": ("cv", 0.299),
    "player_pass_completions": ("cv", 0.304),
    "player_rush_yds": ("cv", 0.566),
    "player_rush_attempts": ("cv", 0.383),
    "player_rush_reception_yds": ("cv", 0.492),
    "player_reception_yds": ("cv", 0.651),
    "player_receptions": ("cv", 0.526),
}

# The narrowest spread a stat is allowed to have. Low lines (a backup tight
# end's 7.5 receiving yards, a pocket passer's 1.5 rushing yards) come from
# lumpy distributions - lots of zeros, the odd long play - and cv x line would
# call them tightly bunched, which turns a few yards of line difference into a
# huge, fake probability gap. First NFL board (Oct 25) flagged 172 such rungs.
SIGMA_FLOOR = {
    "player_pass_yds": 50, "player_pass_rush_yds": 50, "player_pass_attempts": 6,
    "player_pass_completions": 4.5, "player_rush_yds": 15, "player_rush_attempts": 3,
    "player_rush_reception_yds": 18, "player_reception_yds": 15, "player_receptions": 1.3,
}


def stat_sigma(market, line):
    kind, k = STAT_MODELS.get(market, ("sqrt", 1.2))
    line = max(float(line), 0.5)
    if kind == "cv":
        sigma = max(k * line, 1.0)
    else:
        sigma = max(k * math.sqrt(line), 0.5)
    return max(sigma, SIGMA_FLOOR.get(market, 0.0))


def _is_whole(x):
    return abs(x - round(x)) < 1e-9


def side_probs(mu, sigma, line):
    """(P over wins, P under wins, P push) for an integer-valued stat modelled
    as Normal(mu, sigma) with a continuity correction. Half-point lines never
    push; whole-number lines push when the stat lands exactly on them."""
    if _is_whole(line):
        hi = N01.cdf((line + 0.5 - mu) / sigma)
        lo = N01.cdf((line - 0.5 - mu) / sigma)
        return 1 - hi, lo, hi - lo
    c = N01.cdf((line - mu) / sigma)
    return 1 - c, c, 0.0


def cond_over(mu, sigma, line):
    """P(over) given the bet doesn't push - what a de-vigged two-way price means."""
    o, u, _ = side_probs(mu, sigma, line)
    return o / (o + u) if o + u > 0 else 0.5


def implied_mean(p_over, line, sigma):
    """The mean that makes P(over line) = p_over (push-adjusted)."""
    p_over = min(max(p_over, 1e-4), 1 - 1e-4)
    lo, hi = line - 8 * sigma, line + 8 * sigma
    for _ in range(80):
        mid = (lo + hi) / 2
        if cond_over(mid, sigma, line) < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def shift_over(p_over, from_line, to_line, market):
    """Move a fair P(over) from one line to another for the same player/stat."""
    if abs(from_line - to_line) < 1e-9:
        return p_over
    sigma = stat_sigma(market, from_line)
    mu = implied_mean(p_over, from_line, sigma)
    return cond_over(mu, sigma, to_line)


# ---------------------------------------------------------------- consensus


MAX_SHIFT = 0.08   # never move a sharp probability more than this to reach another line


def consensus(quotes, target_line, market, weights, max_gap, max_shift=MAX_SHIFT):
    """Fair P(over target_line) from several sharp books.

    quotes: list of dicts {book, point, over, under} with decimal prices.
    Books whose line is more than max_gap away, or whose price would have to
    move more than max_shift to reach this line, are dropped rather than
    stretched. Returns None when nothing usable remains, else a dict with the
    conservative over/under probabilities and what went into them.
    """
    num_m = num_p = den = 0.0
    used, gaps = [], []
    for q in quotes:
        gap = abs(q["point"] - target_line)
        if gap > max_gap + 1e-9:
            continue
        m0, p0 = devig_pair(q["over"], q["under"])
        m = shift_over(m0, q["point"], target_line, market)
        p = shift_over(p0, q["point"], target_line, market)
        if max(abs(m - m0), abs(p - p0)) > max_shift + 1e-9:
            continue
        w = weights.get(q["book"], 0.5)
        num_m += w * m
        num_p += w * p
        den += w
        used.append(q["book"])
        gaps.append(gap)
    if den == 0:
        return None
    m, p = num_m / den, num_p / den
    return {
        "over": min(m, p),
        "under": min(1 - m, 1 - p),
        "mid_over": (m + p) / 2,
        "books": used,
        "n": len(used),
        "max_gap": max(gaps) if gaps else 0.0,
        "exact": all(g < 1e-9 for g in gaps),
    }


# ---------------------------------------------------------------- pick'em


def poisson_binomial(ps):
    """Distribution of the number of hits when each pick has its own p."""
    dist = [1.0]
    for p in ps:
        nxt = [0.0] * (len(dist) + 1)
        for k, v in enumerate(dist):
            nxt[k] += v * (1 - p)
            nxt[k + 1] += v * p
        dist = nxt
    return dist


def entry_return(ps, pays, boost=1.0):
    """Expected payout per $1 for an entry. pays maps hits -> multiplier.
    `boost` multiplies the all-correct tier (Underdog per-pick multipliers)."""
    dist = poisson_binomial(ps)
    n = len(ps)
    total = 0.0
    for k, prob in enumerate(dist):
        m = float(pays.get(str(k), pays.get(k, 0)))
        if k == n:
            m *= boost
        total += prob * m
    return total


def breakeven(n, pays):
    """Per-pick hit rate at which an n-pick entry with these payouts breaks even
    (every pick assumed equally likely and independent)."""
    lo, hi = 0.30, 0.95
    for _ in range(80):
        mid = (lo + hi) / 2
        if entry_return([mid] * n, pays) < 1.0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------- Kalshi


def kalshi_fee(price, contracts=10, multiplier=1.0, rate=0.07):
    """Kalshi taker fee per contract in dollars:
    round_up(0.07 * C * P * (1 - P)) to the cent, spread over C contracts."""
    raw = rate * multiplier * contracts * price * (1 - price)
    cents = math.ceil(round(raw * 100, 6))
    return cents / 100.0 / contracts
