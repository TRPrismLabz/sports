import asyncio
from odds_client import OddsClient
import os
from dotenv import load_dotenv
import json

load_dotenv()
client = OddsClient()

async def test():
    games = await client.fetch_games("basketball_nba")
    if games:
        g = games[0]
        odds = await client.fetch_event_odds("basketball_nba", g["id"], ["player_points", "player_rebounds"], "au")
        print(json.dumps(odds, indent=2))
    await client.close()

asyncio.run(test())
