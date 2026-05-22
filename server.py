"""
FastAPI Server — Sports Betting Engine
"""
import asyncio
import os
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import HOST, PORT, REFRESH_INTERVAL_MINUTES, SPORTS, MIN_EDGE_THRESHOLD
from database import (
    init_db, upsert_game, save_odds_snapshot, save_analysis,
    get_all_games, get_top_opportunities, get_game_count,
    update_all_kelly_amounts
)
from odds_client import OddsClient
from analysis import SportsAnalysisEngine
from bankroll import BankrollManager
from stats_client import LiveStatsManager

odds_client = OddsClient()
stats_manager = LiveStatsManager()
engine = SportsAnalysisEngine()
bankroll_mgr = BankrollManager(bankroll=1000.0)
scheduler = AsyncIOScheduler()

_last_refresh = None
_refresh_status = "idle"


async def refresh_odds_and_analyze():
    global _last_refresh, _refresh_status
    if _refresh_status == "refreshing":
        return
    _refresh_status = "refreshing"
    print(f"[{datetime.utcnow().isoformat()}] Refreshing odds data...")
    try:
        await stats_manager.update_live_stats()
        
        total_analyzed = 0
        for sport, cfg in SPORTS.items():
            sport_key = cfg["key"]
            print(f"  [{sport}] Fetching games for {sport_key}...")
            games = await odds_client.fetch_games(sport_key)
            if not games:
                print(f"  [{sport}] No games found")
                continue
            print(f"  [{sport}] Found {len(games)} games")
            
            for g in games[:15]:
                try:
                    game_data = {
                        "id": g["id"],
                        "sport": sport,
                        "home_team": g.get("home_team", ""),
                        "away_team": g.get("away_team", ""),
                        "commence_time": g.get("commence_time", ""),
                        "status": "upcoming"
                    }
                    await upsert_game(game_data)
                    
                    # Fetch base odds for this game (H2H, Totals, Spreads)
                    base_odds = await odds_client.fetch_event_odds(sport_key, g["id"], cfg["markets"], "au")
                    bookmakers = base_odds.get("bookmakers", [])
                    
                    if not bookmakers:
                        print(f"    No bookmakers for {g.get('home_team','')} v {g.get('away_team','')}")
                        total_analyzed += 1
                        continue

                    # Helper to save a result
                    async def save_result(r):
                        if r["edge"] < MIN_EDGE_THRESHOLD:
                            return # Only save +EV bets
                            
                        kelly = bankroll_mgr.kelly_size(r["true_prob"], r["best_price"])
                        await save_analysis(
                            g["id"], r["market_type"], r["outcome"], r["true_prob"],
                            r["market_prob"], r["edge"], r["confidence"],
                            r["outcome"] if r["edge"] > MIN_EDGE_THRESHOLD else "HOLD",
                            r["best_price"], "Best Bookmaker",
                            kelly.get("adj_kelly_pct", 0), kelly.get("bet_amount", 0),
                            kelly.get("ev_pct", 0),
                            r["signals"], r["reasoning"],
                            player=r.get("player")
                        )
                    
                    # 1. H2H
                    for r in engine.analyze_h2h(game_data, bookmakers, stats_manager):
                        await save_result(r)
                    
                    # 2. Totals
                    if "totals" in cfg["markets"]:
                        for r in engine.analyze_totals(game_data, bookmakers, stats_manager):
                            await save_result(r)
                    
                    # 3. Spreads
                    if "spreads" in cfg["markets"]:
                        for r in engine.analyze_spreads(game_data, bookmakers, stats_manager):
                            await save_result(r)
                            
                    # 4. Props
                    prop_markets = cfg.get("prop_markets", [])
                    if prop_markets:
                        # Batch prop markets into groups of 4 to avoid 422 invalid market errors blocking all props
                        batch_size = 4
                        for i in range(0, len(prop_markets), batch_size):
                            batch = prop_markets[i:i + batch_size]
                            try:
                                prop_odds = await odds_client.fetch_event_odds(sport_key, g["id"], batch, "au")
                                prop_bookmakers = prop_odds.get("bookmakers", [])
                                
                                prop_data = []
                                prop_map = {}
                                for bm in prop_bookmakers:
                                    for m in bm.get("markets", []):
                                        mkey = m.get("key")
                                        if mkey not in batch:
                                            continue
                                        for oc in m.get("outcomes", []):
                                            player = oc.get("description", "Unknown Player")
                                            direction = oc.get("name", "").lower()
                                            point = oc.get("point")
                                            price = oc.get("price")
                                            # For 'anytime_try' and 'player_goals', 'point' might be missing, so we default to 0.5
                                            if point is None:
                                                point = 0.5
                                            if price is None:
                                                continue
                                            group_key = f"{mkey}_{player}_{direction}_{point}"
                                            if group_key not in prop_map:
                                                prop_map[group_key] = {
                                                    "market_key": mkey,
                                                    "player": player,
                                                    "direction": direction,
                                                    "line": float(point),
                                                    "prices": []
                                                }
                                            prop_map[group_key]["prices"].append(float(price))
                                
                                prop_data = list(prop_map.values())
                                if prop_data:
                                    for r in engine.analyze_props(game_data, prop_data, stats_manager):
                                        await save_result(r)
                            except Exception as pe:
                                print(f"    [Props] Batch {batch} failed for {g.get('id','')}: {pe}")
                            
                            await asyncio.sleep(0.3)
                    
                    total_analyzed += 1
                    await asyncio.sleep(0.3)
                except Exception as e:
                    print(f"    [ERROR] Game {g.get('id','?')}: {e}")

        _last_refresh = datetime.utcnow().isoformat()
        _refresh_status = "idle"
        print(f"  Analyzed {total_analyzed} games across all sports. Done.")
    except Exception as e:
        _refresh_status = f"error: {e}"
        print(f"[ERROR] Refresh failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(refresh_odds_and_analyze())
    scheduler.add_job(refresh_odds_and_analyze, 'interval', minutes=REFRESH_INTERVAL_MINUTES)
    scheduler.start()
    yield
    scheduler.shutdown()
    await odds_client.close()

app = FastAPI(title="Rossbets", lifespan=lifespan)

static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(html_path, "r") as f:
        return HTMLResponse(content=f.read())

from fastapi import Header, HTTPException, Depends

USERS = {
    "admin": "admin",
    "rosso": "Jack6"
}

async def verify_token(authorization: str = Header(None)):
    if not authorization or not authorization.endswith("_secret_token"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

@app.post("/api/login")
async def login(request: Request):
    data = await request.json()
    u = data.get("username")
    p = data.get("password")
    if USERS.get(u) == p:
        return {"token": f"{u}_secret_token"}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/api/status")
async def status(authorized: bool = Depends(verify_token)):
    counts = await get_game_count()
    return {
        "status": "running",
        "games_tracked": counts,
        "last_refresh": _last_refresh,
        "refresh_status": _refresh_status,
        "bankroll": bankroll_mgr.summary(),
        "quota": odds_client.quota_info
    }

@app.get("/api/games")
async def list_games(sport: str = None, authorized: bool = Depends(verify_token)):
    games = await get_all_games(sport=sport)
    return games

@app.get("/api/opportunities")
async def get_opportunities(min_edge: float = 0.03, limit: int = 50, sport: str = None, sort: str = "best", authorized: bool = Depends(verify_token)):
    opps = await get_top_opportunities(min_edge=min_edge, limit=limit, sport=sport, sort=sort)
    return opps

@app.post("/api/bankroll/set")
async def set_bankroll(request: Request, authorized: bool = Depends(verify_token)):
    data = await request.json()
    amount = float(data.get("bankroll", 1000))
    bankroll_mgr.update_bankroll(amount)
    await update_all_kelly_amounts(amount)
    return bankroll_mgr.summary()

@app.post("/api/bankroll/kelly")
async def set_kelly_mode(request: Request, authorized: bool = Depends(verify_token)):
    data = await request.json()
    fraction = float(data.get("fraction", 0.25))
    bankroll_mgr.set_kelly_fraction(fraction)
    return bankroll_mgr.summary()

@app.post("/api/refresh")
async def trigger_refresh(authorized: bool = Depends(verify_token)):
    if _refresh_status == "refreshing":
        return {"status": "already refreshing"}
    asyncio.create_task(refresh_odds_and_analyze())
    return {"status": "refresh started"}

if __name__ == "__main__":
    import uvicorn
    print(f"\n🔮 Rossbets Engine starting on http://{HOST}:{PORT}\n")
    uvicorn.run("server:app", host=HOST, port=PORT, reload=False)
