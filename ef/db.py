"""SQLite storage. Pulls are appended, never overwritten. Lines for players you
bet are kept for good (they are the closing-line record); the rest is pruned
after a few days so the database stays small."""
import os
import sqlite3

from .config import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS pulls (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  league TEXT NOT NULL,
  kind TEXT NOT NULL,              -- 'board' | 'close'
  credits_used INTEGER,
  credits_remaining INTEGER,
  events INTEGER,
  note TEXT
);

CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  league TEXT NOT NULL,
  commence_time TEXT NOT NULL,
  home TEXT,
  away TEXT
);

-- One row per side per line per book per pull.
CREATE TABLE IF NOT EXISTS lines (
  pull_id INTEGER NOT NULL,
  ts TEXT NOT NULL,
  league TEXT NOT NULL,
  event_id TEXT,
  book TEXT NOT NULL,
  market TEXT NOT NULL,
  player TEXT NOT NULL,
  player_key TEXT NOT NULL,
  side TEXT NOT NULL,              -- 'over' | 'under'
  point REAL,
  price REAL,                      -- decimal odds; for Kalshi 1/ask
  multiplier REAL,                 -- pick'em per-pick multiplier when given
  ask REAL,                        -- Kalshi: dollars per contract to buy this side
  size REAL,                       -- Kalshi: contracts available at the ask
  ref TEXT,                        -- Kalshi market ticker / extra info
  game_date TEXT                   -- Kalshi: date from the ticker, YYYY-MM-DD
);
CREATE INDEX IF NOT EXISTS lines_pull ON lines (pull_id);
CREATE INDEX IF NOT EXISTS lines_lookup ON lines (league, player_key, market);
CREATE INDEX IF NOT EXISTS lines_event ON lines (event_id, pull_id);

-- Which scheduled pulls have already happened, so a late or repeated run
-- never pays for the same slot twice.
CREATE TABLE IF NOT EXISTS auto_slots (
  slot TEXT PRIMARY KEY,
  ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ge_proj (
  imported_at TEXT NOT NULL,
  saved_at TEXT,
  year INTEGER, week INTEGER,
  player TEXT, player_key TEXT, pos TEXT, team TEXT, opp TEXT,
  ge_market TEXT, market TEXT,
  median REAL, p25 REAL, p75 REAL, score REAL,
  biased INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ge_lookup ON ge_proj (player_key, market);

-- Codes printed on a board, so a bet can be logged by code.
CREATE TABLE IF NOT EXISTS board_picks (
  board_ts TEXT NOT NULL,
  league TEXT NOT NULL,
  code TEXT NOT NULL,
  pull_id INTEGER,
  event_id TEXT, commence_time TEXT,
  book TEXT, market TEXT, player TEXT, player_key TEXT, side TEXT, point REAL,
  price REAL, multiplier REAL, ask REAL, ref TEXT,
  fair_p REAL, n_sharp INTEGER, ge_p REAL, ge_score REAL,
  flagged INTEGER, edge REAL
);
CREATE INDEX IF NOT EXISTS board_picks_code ON board_picks (league, board_ts, code);

CREATE TABLE IF NOT EXISTS bets (
  id INTEGER PRIMARY KEY,
  placed_at TEXT NOT NULL,
  league TEXT NOT NULL,
  book TEXT NOT NULL,
  entry_type TEXT,                 -- 'pp5', 'ud3', 'straight', 'kalshi'
  stake REAL,
  contracts REAL,
  result TEXT,                     -- NULL | win | loss | push | partial
  payout REAL,
  notes TEXT,
  graded_by TEXT                   -- 'auto' (ESPN) | NULL (by hand)
);

CREATE TABLE IF NOT EXISTS bet_legs (
  bet_id INTEGER NOT NULL,
  leg INTEGER NOT NULL,
  event_id TEXT, commence_time TEXT,
  market TEXT, player TEXT, player_key TEXT, side TEXT, point REAL,
  price REAL,                      -- decimal odds taken (sportsbook) / ask (Kalshi)
  fair_p REAL,                     -- sharp fair probability when placed
  breakeven REAL,                  -- pick'em per-pick breakeven of the entry
  ge_p REAL, ge_score REAL,
  close_fair_p REAL, close_ts TEXT, close_n INTEGER,
  flagged INTEGER, edge REAL,      -- was it flagged on the board, and by how much
  actual REAL, leg_result TEXT,    -- from the box score: hit | miss | push | void | review
  PRIMARY KEY (bet_id, leg)
);
"""


# Columns added after the first release, so older databases pick them up.
ADDED = [
    ("board_picks", "flagged", "INTEGER"), ("board_picks", "edge", "REAL"),
    ("bets", "graded_by", "TEXT"),
    ("bet_legs", "flagged", "INTEGER"), ("bet_legs", "edge", "REAL"),
    ("bet_legs", "actual", "REAL"), ("bet_legs", "leg_result", "TEXT"),
]


def migrate(con):
    for table, col, typ in ADDED:
        have = {r[1] for r in con.execute("PRAGMA table_info(%s)" % table)}
        if have and col not in have:
            con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))
    con.commit()


def connect(path=None):
    ensure_dirs()
    con = sqlite3.connect(path or os.environ.get("EDGEFINDER_DB") or DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)     # creates anything missing; never alters existing tables
    migrate(con)                  # adds columns introduced after a database was created
    return con
