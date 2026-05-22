import asyncio
from odds_client import OddsClient
import os
from dotenv import load_dotenv

load_dotenv()
client = OddsClient()

async def test():
    games = await client.fetch_games("rugbyleague_nrl")
    print("Games:", len(games))
    if games:
        print("First Game:", games[0])
        odds = await client.fetch_event_odds("rugbyleague_nrl", games[0]["id"], ["h2h"], "au")
        print("Odds Bookmakers:", len(odds.get("bookmakers", [])))
    await client.close()

asyncio.run(test())
