import asyncio
from stats_client import LiveStatsManager

async def test():
    mgr = LiveStatsManager()
    try:
        await mgr.update_live_stats()
        print("Stats success!")
    except Exception as e:
        print("Stats error:", e)

asyncio.run(test())
