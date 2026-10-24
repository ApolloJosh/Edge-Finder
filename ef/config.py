"""Paths, settings and the API key."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
BOARDS_DIR = os.path.join(ROOT, "boards")
INPUTS_DIR = os.path.join(ROOT, "inputs")
DB_PATH = os.path.join(DATA_DIR, "edgefinder.db")


class Config(dict):
    @property
    def sharp_weights(self):
        return self["books"]["sharp"]

    @property
    def pickem_books(self):
        return self["books"]["pickem"]

    @property
    def sportsbooks(self):
        return self["books"]["sportsbook"]

    def all_books(self):
        b = list(self.pickem_books) + list(self.sportsbooks) + list(self.sharp_weights)
        seen, out = set(), []
        for x in b:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    def league(self, name):
        lg = self["leagues"].get(name)
        if not lg:
            raise SystemExit("Unknown league '%s'. Choose from: %s" % (name, ", ".join(self["leagues"])))
        return lg

    def max_gap(self, market):
        g = self["max_line_gap"]
        return float(g.get(market, g.get("default", 1.0)))

    def entries(self, book):
        return {k: v for k, v in self["entries"].get(book, {}).items() if not k.startswith("_")}


def load_config(path=None):
    path = path or os.path.join(ROOT, "config.json")
    with open(path) as f:
        return Config(json.load(f))


def load_aliases():
    path = os.path.join(ROOT, "aliases.json")
    try:
        with open(path) as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def load_env():
    """Read KEY=value lines from .env next to edgefinder.py into os.environ."""
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def odds_api_key():
    load_env()
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key or key.startswith("paste"):
        raise SystemExit(
            "No Odds API key yet.\n"
            "  1. Get a free key at https://the-odds-api.com\n"
            "  2. Run this, replace paste-your-key-here with the key, and save:\n\n"
            "  cd \"%s\" && [ -f .env ] || printf 'ODDS_API_KEY=paste-your-key-here\\n' > .env; open -e .env\n" % ROOT
        )
    return key


def ensure_dirs():
    for d in (DATA_DIR, BOARDS_DIR, INPUTS_DIR):
        os.makedirs(d, exist_ok=True)
