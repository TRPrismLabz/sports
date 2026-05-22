import os
import json
import asyncio
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# We fall back to a mock client if not configured so the app doesn't crash on boot without env vars
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    print("WARNING: Supabase URL or Key is missing. Database operations will fail.")

async def init_db():
    # Supabase schema is managed via the supabase_schema.sql script.
    # No local init is needed.
    pass

async def upsert_game(game: dict):
    if not supabase: return
    def _run():
        data = {
            "id": game["id"],
            "sport": game.get("sport", "Unknown"),
            "home_team": game.get("home_team", "Unknown"),
            "away_team": game.get("away_team", "Unknown"),
            "commence_time": game.get("commence_time"),
            "status": "upcoming"
        }
        supabase.table("games").upsert(data).execute()
    await asyncio.to_thread(_run)

async def save_odds_snapshot(game_id: str, market_type: str, bookmaker: str, outcome: str, price: float, point: float = None, player: str = None):
    if not supabase: return
    def _run():
        data = {
            "game_id": game_id,
            "market_type": market_type,
            "bookmaker": bookmaker,
            "outcome": outcome,
            "price": price,
            "point": point,
            "player": player
        }
        supabase.table("odds_snapshots").insert(data).execute()
    await asyncio.to_thread(_run)

async def save_analysis(game_id: str, market_type: str, outcome: str, true_prob: float, market_prob: float, edge: float, confidence: float, recommended_bet: str, best_price: float, best_bookmaker: str, kelly_fraction: float, kelly_amount: float, ev_pct: float, signals: list, reasoning: str, player: str = None):
    if not supabase: return
    def _run():
        data = {
            "game_id": game_id,
            "market_type": market_type,
            "outcome": outcome,
            "player": player,
            "true_prob": true_prob,
            "market_prob": market_prob,
            "edge": edge,
            "confidence": confidence,
            "recommended_bet": recommended_bet,
            "best_price": best_price,
            "best_bookmaker": best_bookmaker,
            "kelly_fraction": kelly_fraction,
            "kelly_amount": kelly_amount,
            "ev_pct": ev_pct,
            "signal_breakdown": signals,
            "reasoning": reasoning
        }
        # Upsert requires the exact matching of the unique constraint
        supabase.table("analysis_results").upsert(data, on_conflict="game_id, market_type, outcome, player").execute()
    await asyncio.to_thread(_run)

async def get_all_games(sport: str = None) -> list:
    if not supabase: return []
    def _run():
        query = supabase.table("games").select("*").eq("status", "upcoming")
        if sport:
            query = query.eq("sport", sport)
        res = query.order("commence_time", desc=False).execute()
        return res.data
    return await asyncio.to_thread(_run)

async def get_top_opportunities(min_edge: float = 0.03, limit: int = 50, sport: str = None, sort: str = "best") -> list:
    if not supabase: return []
    def _run():
        query = supabase.table("analysis_results").select("*, games!inner(sport, home_team, away_team, commence_time, status)").gte("edge", min_edge).eq("games.status", "upcoming")
        if sport:
            query = query.eq("games.sport", sport)
        
        # We fetch all matching edges, sort in Python because Supabase inner join sorting can be complex
        res = query.execute()
        data = res.data
        
        # Flatten the join
        results = []
        for r in data:
            row = r.copy()
            g = r.pop("games")
            row["sport"] = g["sport"]
            row["home_team"] = g["home_team"]
            row["away_team"] = g["away_team"]
            row["commence_time"] = g["commence_time"]
            results.append(row)
            
        if sort == "upcoming":
            results.sort(key=lambda x: (x["commence_time"], -x["edge"]))
        else:
            results.sort(key=lambda x: -x["edge"])
            
        return results[:limit]
    return await asyncio.to_thread(_run)

async def get_game_count() -> dict:
    if not supabase: return {}
    def _run():
        res = supabase.table("games").select("sport").eq("status", "upcoming").execute()
        counts = {}
        for r in res.data:
            s = r["sport"]
            counts[s] = counts.get(s, 0) + 1
        return counts
    return await asyncio.to_thread(_run)

async def get_user_bankroll(username: str) -> float:
    if not supabase: return 1000.0
    def _run():
        res = supabase.table("app_users").select("bankroll").eq("username", username).execute()
        if res.data and "bankroll" in res.data[0]:
            return float(res.data[0]["bankroll"] or 1000.0)
        return 1000.0
    return await asyncio.to_thread(_run)

async def update_user_bankroll(username: str, new_bankroll: float):
    if not supabase: return
    def _run():
        supabase.table("app_users").update({"bankroll": new_bankroll}).eq("username", username).execute()
    await asyncio.to_thread(_run)

async def verify_user(username: str, password_hash: str) -> bool:
    if not supabase: return False
    def _run():
        res = supabase.table("app_users").select("*").eq("username", username).eq("password_hash", password_hash).execute()
        return len(res.data) > 0
    return await asyncio.to_thread(_run)
