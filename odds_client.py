"""
Odds Client — Fetches live odds from The Odds API.
Supports head-to-head, totals, spreads, and player props
for NRL, NBA, and AFL.
"""
import httpx
import asyncio
from typing import Optional
from config import ODDS_API_KEY, ODDS_API_BASE, SPORTS


class OddsClient:
    def __init__(self):
        self.api_key = ODDS_API_KEY
        self.base = ODDS_API_BASE
        self.session: Optional[httpx.AsyncClient] = None
        self._requests_remaining = 500
        self._requests_used = 0

    async def _get_session(self) -> httpx.AsyncClient:
        if not self.session or self.session.is_closed:
            self.session = httpx.AsyncClient(timeout=30.0)
        return self.session

    async def close(self):
        if self.session and not self.session.is_closed:
            await self.session.aclose()

    def _track_quota(self, headers: dict):
        self._requests_remaining = int(headers.get("x-requests-remaining", self._requests_remaining))
        self._requests_used = int(headers.get("x-requests-used", self._requests_used))

    async def fetch_games(self, sport_key: str) -> list:
        """Fetch upcoming games for a sport."""
        if not self.api_key:
            print("[OddsClient] No API key configured.")
            return []

        session = await self._get_session()
        url = f"{self.base}/sports/{sport_key}/events"
        try:
            r = await session.get(url, params={
                "apiKey": self.api_key,
                "dateFormat": "iso",
            })
            r.raise_for_status()
            self._track_quota(r.headers)
            return r.json()
        except Exception as e:
            print(f"[OddsClient] Error fetching games for {sport_key}: {e}")
            return []

    async def fetch_odds(self, sport_key: str, markets: list,
                          event_ids: Optional[list] = None,
                          regions: str = "au,uk,us") -> list:
        """Fetch odds for a sport's main markets."""
        if not self.api_key:
            return []

        session = await self._get_session()
        url = f"{self.base}/sports/{sport_key}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": ",".join(markets),
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        if event_ids:
            params["eventIds"] = ",".join(event_ids[:10])  # API limit

        try:
            r = await session.get(url, params=params)
            r.raise_for_status()
            self._track_quota(r.headers)
            return r.json()
        except Exception as e:
            print(f"[OddsClient] Error fetching odds for {sport_key}: {e}")
            return []

    async def fetch_event_odds(self, sport_key: str, event_id: str,
                                markets: list, regions: str = "au,uk,us") -> dict:
        """Fetch odds for a specific event (including props)."""
        if not self.api_key:
            return {}

        session = await self._get_session()
        url = f"{self.base}/sports/{sport_key}/events/{event_id}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": ",".join(markets[:5]),  # API limits per call
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        try:
            r = await session.get(url, params=params)
            r.raise_for_status()
            self._track_quota(r.headers)
            return r.json()
        except Exception as e:
            print(f"[OddsClient] Error fetching event odds {event_id}: {e}")
            return {}

    def decimal_to_prob(self, decimal_odds: float) -> float:
        """Convert decimal odds to implied probability (with no vig removed)."""
        if decimal_odds <= 1.0:
            return 0.99
        return 1.0 / decimal_odds

    def remove_vig(self, probs: list) -> list:
        """Remove bookmaker's vig to get true market probabilities."""
        total = sum(probs)
        if total <= 0:
            return probs
        return [p / total for p in probs]

    def best_odds(self, bookmakers: list, outcome_name: str,
                   market_key: str = "h2h") -> tuple:
        """Find best available price for a given outcome across all bookmakers."""
        best_price = 0.0
        best_book = ""
        for bm in bookmakers:
            for market in bm.get("markets", []):
                if market.get("key") != market_key:
                    continue
                for outcome in market.get("outcomes", []):
                    if outcome.get("name", "").lower() == outcome_name.lower():
                        price = float(outcome.get("price", 0))
                        if price > best_price:
                            best_price = price
                            best_book = bm.get("title", "")
        return best_price, best_book

    def get_all_prices(self, bookmakers: list, outcome_name: str,
                        market_key: str = "h2h") -> list:
        """Get all prices for an outcome across all bookmakers."""
        prices = []
        for bm in bookmakers:
            for market in bm.get("markets", []):
                if market.get("key") != market_key:
                    continue
                for outcome in market.get("outcomes", []):
                    if outcome.get("name", "").lower() == outcome_name.lower():
                        price = float(outcome.get("price", 0))
                        if price > 1.0:
                            prices.append({
                                "bookmaker": bm.get("title", ""),
                                "price": price,
                                "implied_prob": self.decimal_to_prob(price),
                            })
        return sorted(prices, key=lambda x: x["price"], reverse=True)



    @property
    def quota_info(self) -> dict:
        return {
            "requests_used": self._requests_used,
            "requests_remaining": self._requests_remaining,
        }
