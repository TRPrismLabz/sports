"""
Configuration — Sports Betting EV Engine
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Server ─────────────────────────────────────────────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8001"))

# ── Odds API ───────────────────────────────────────────────────────────────────
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# ── Sports & Leagues ───────────────────────────────────────────────────────────
SPORTS = {
    "NRL": {
        "key": "rugbyleague_nrl",
        "label": "NRL Rugby League",
        "emoji": "🏉",
        "color": "#ff6b00",
        "markets": [
            "h2h",           # Head-to-head (match winner)
            "totals",        # Over/Under total points
            "spreads",       # Line/Handicap
            "h2h_lay",       # Lay betting
        ],
        "prop_markets": [
            "player_tries",           # Try scorer markets
            "player_first_try",       # First try scorer
            "player_anytime_try",     # Anytime try scorer
            "player_points",          # Player points scored
            "player_assists",         # Assists / try assists
            "player_kicks",           # Kicks in play
            "player_tackles",         # Tackle count
            "player_runs",            # Runs
            "team_tries",             # Team total tries
            "half_totals",            # First half totals
            "winning_margin",         # Winning margin bands
        ]
    },
    "NBA": {
        "key": "basketball_nba",
        "label": "NBA Basketball",
        "emoji": "🏀",
        "color": "#c9a227",
        "markets": [
            "h2h",
            "totals",
            "spreads",
        ],
        "prop_markets": [
            "player_points",
            "player_rebounds",
            "player_assists",
            "player_threes",
            "player_blocks",
            "player_steals",
            "player_turnovers",
            "player_points_rebounds_assists",
            "player_points_rebounds",
            "player_points_assists",
            "player_first_basket",
            "team_totals",
            "half_spreads",
            "half_totals",
            "quarter_totals",
        ]
    },
    "AFL": {
        "key": "aussierules_afl",
        "label": "AFL Football",
        "emoji": "🦘",
        "color": "#00c2ff",
        "markets": [
            "h2h",
            "totals",
            "spreads",
        ],
        "prop_markets": [
            "player_disposals",       # Disposals (kicks + handballs)
            "player_kicks",           # Kicks
            "player_handballs",       # Handballs
            "player_marks",           # Marks
            "player_goals",           # Goals kicked
            "player_behinds",         # Behinds
            "player_tackles",         # Tackles
            "player_hitouts",         # Hit-outs (rucks)
            "player_contested_possessions",
            "player_clearances",      # Clearances
            "player_inside_50s",      # Inside 50s
            "player_goal_assists",    # Goal assists
            "player_score_involvements",
            "player_first_goal",      # First goalkicker
            "player_anytime_goal",    # Anytime goalkicker
            "winning_margin",
            "half_totals",
            "quarter_totals",
        ]
    }
}

# ── Analysis Parameters ─────────────────────────────────────────────────────────
MIN_EDGE_THRESHOLD = 0.03       # 3% minimum edge to flag
MIN_CONFIDENCE = 0.35           # Minimum confidence score
REFRESH_INTERVAL_MINUTES = 15   # How often to refresh odds
MAX_BOOKMAKERS = 10             # Max bookmakers to compare

# ── Kelly Criterion ─────────────────────────────────────────────────────────────
DEFAULT_KELLY_FRACTION = 0.25   # Quarter Kelly (conservative)
MAX_SINGLE_POSITION_PCT = 0.05  # Max 5% of bankroll on single bet
MAX_TOTAL_EXPOSURE_PCT = 0.40   # Max 40% of bankroll at risk

# ── EV Model Weights ────────────────────────────────────────────────────────────
# Logit-space regression betas for each signal
BETAS = {
    "market": 0.88,          # Consensus market anchor
    "line_movement": 0.55,   # Odds line movement signal
    "sharp_money": 0.65,     # Sharp / public money split
    "poisson": 0.70,         # Poisson/statistical model
    "form": 0.40,            # Recent form & head-to-head
    "public_fade": 0.30,     # Fade public heavy favorites
}
