"""
Database — Async SQLite for sports betting engine.
Stores games, odds snapshots, and analysis results.
"""
import json
import aiosqlite
from datetime import datetime
from typing import Optional, List

DB_PATH = "sportsbet.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                sport TEXT NOT NULL,
                home_team TEXT,
                away_team TEXT,
                commence_time TEXT,
                status TEXT DEFAULT 'upcoming',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS odds_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                market_type TEXT NOT NULL,
                bookmaker TEXT NOT NULL,
                outcome TEXT NOT NULL,
                price REAL NOT NULL,
                point REAL,
                player TEXT,
                snapshot_time TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS analysis_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                market_type TEXT NOT NULL,
                outcome TEXT NOT NULL,
                player TEXT,
                true_prob REAL,
                market_prob REAL,
                edge REAL,
                confidence REAL,
                recommended_bet TEXT,
                best_price REAL,
                best_bookmaker TEXT,
                kelly_fraction REAL DEFAULT 0,
                kelly_amount REAL DEFAULT 0,
                ev_pct REAL DEFAULT 0,
                signal_breakdown TEXT,
                reasoning TEXT,
                analyzed_at TEXT DEFAULT (datetime('now')),
                UNIQUE(game_id, market_type, outcome, player)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_analysis_game ON analysis_results(game_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_analysis_edge ON analysis_results(edge)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_odds_game ON odds_snapshots(game_id, market_type)")
        await db.commit()


async def upsert_game(game: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO games (id, sport, home_team, away_team, commence_time, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                updated_at=excluded.updated_at
        """, (
            game["id"], game["sport"], game.get("home_team", ""),
            game.get("away_team", ""), game.get("commence_time", ""),
            game.get("status", "upcoming")
        ))
        await db.commit()


async def save_odds_snapshot(game_id: str, market_type: str, bookmaker: str,
                              outcome: str, price: float, point: Optional[float] = None,
                              player: Optional[str] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO odds_snapshots (game_id, market_type, bookmaker, outcome, price, point, player)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (game_id, market_type, bookmaker, outcome, price, point, player))
        await db.commit()


async def save_analysis(game_id: str, market_type: str, outcome: str,
                         true_prob: float, market_prob: float, edge: float,
                         confidence: float, recommended_bet: str, best_price: float,
                         best_bookmaker: str, kelly_fraction: float, kelly_amount: float,
                         ev_pct: float, signal_breakdown: dict, reasoning: str,
                         player: Optional[str] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO analysis_results
                (game_id, market_type, outcome, player, true_prob, market_prob, edge,
                 confidence, recommended_bet, best_price, best_bookmaker, kelly_fraction,
                 kelly_amount, ev_pct, signal_breakdown, reasoning, analyzed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(game_id, market_type, outcome, player) DO UPDATE SET
                true_prob=excluded.true_prob, market_prob=excluded.market_prob,
                edge=excluded.edge, confidence=excluded.confidence,
                recommended_bet=excluded.recommended_bet, best_price=excluded.best_price,
                best_bookmaker=excluded.best_bookmaker, kelly_fraction=excluded.kelly_fraction,
                kelly_amount=excluded.kelly_amount, ev_pct=excluded.ev_pct,
                signal_breakdown=excluded.signal_breakdown, reasoning=excluded.reasoning,
                analyzed_at=excluded.analyzed_at
        """, (
            game_id, market_type, outcome, player or "", true_prob, market_prob, edge,
            confidence, recommended_bet, best_price, best_bookmaker, kelly_fraction,
            kelly_amount, ev_pct, json.dumps(signal_breakdown), reasoning
        ))
        await db.commit()


async def get_all_games(sport: Optional[str] = None, status: str = "upcoming") -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if sport:
            cursor = await db.execute(
                "SELECT * FROM games WHERE status=? AND sport=? ORDER BY commence_time ASC",
                (status, sport)
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM games WHERE status=? ORDER BY sport, commence_time ASC",
                (status,)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_game_analysis(game_id: str) -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM analysis_results WHERE game_id=? ORDER BY ABS(edge) DESC",
            (game_id,)
        )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("signal_breakdown"):
                try:
                    d["signal_breakdown"] = json.loads(d["signal_breakdown"])
                except Exception:
                    pass
            results.append(d)
        return results


async def get_top_opportunities(min_edge: float = 0.03, limit: int = 50,
                                 sport: Optional[str] = None, sort: str = "best") -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        order_clause = "ORDER BY g.commence_time ASC, ABS(ar.edge) DESC" if sort == "upcoming" else "ORDER BY ABS(ar.edge) DESC"
        
        if sport:
            cursor = await db.execute(f"""
                SELECT ar.*, g.sport, g.home_team, g.away_team, g.commence_time
                FROM analysis_results ar
                JOIN games g ON ar.game_id = g.id
                WHERE ar.edge >= ? AND g.status='upcoming' AND g.sport=?
                ORDER BY g.commence_time ASC, ar.edge DESC LIMIT ?
            """, (min_edge, sport, limit))
        else:
            cursor = await db.execute(f"""
                SELECT ar.*, g.sport, g.home_team, g.away_team, g.commence_time
                FROM analysis_results ar
                JOIN games g ON ar.game_id = g.id
                WHERE ar.edge >= ? AND g.status='upcoming'
                ORDER BY g.commence_time ASC, ar.edge DESC LIMIT ?
            """, (min_edge, limit))
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("signal_breakdown"):
                try:
                    d["signal_breakdown"] = json.loads(d["signal_breakdown"])
                except Exception:
                    pass
            results.append(d)
        return results


async def get_odds_history(game_id: str, market_type: str) -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM odds_snapshots
            WHERE game_id=? AND market_type=?
            ORDER BY snapshot_time DESC LIMIT 200
        """, (game_id, market_type))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_game_count() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT sport, COUNT(*) as cnt FROM games WHERE status='upcoming' GROUP BY sport")
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}

async def update_all_kelly_amounts(new_bankroll: float):
    """Dynamically updates the bet sizes for all existing opportunities when bankroll is changed."""
    async with aiosqlite.connect(DB_PATH) as db:
        # kelly_fraction is saved as a percentage (e.g., 2.5 for 2.5%)
        await db.execute("""
            UPDATE analysis_results 
            SET kelly_amount = (kelly_fraction / 100.0) * ?
        """, (new_bankroll,))
        await db.commit()
