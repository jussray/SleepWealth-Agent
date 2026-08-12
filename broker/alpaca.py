import os
from datetime import datetime, timezone
from typing import List

import httpx

from .base import BaseBroker, Order, Position


class AlpacaBroker(BaseBroker):
    """Alpaca REST adapter. Paper by default; live only when paper_mode=False."""

    BASE_URL_PAPER = "https://paper-api.alpaca.markets"
    BASE_URL_LIVE = "https://api.alpaca.markets"
    DATA_URL = "https://data.alpaca.markets"

    def __init__(self, paper_mode: bool = True, api_key: str = None,
                 api_secret: str = None, **kwargs):
        self.paper_mode = paper_mode
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.api_secret = api_secret or os.getenv("ALPACA_API_SECRET")
        self.base_url = self.BASE_URL_PAPER if paper_mode else self.BASE_URL_LIVE

    @property
    def _headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": self.api_key or "",
            "APCA-API-SECRET-KEY": self.api_secret or "",
        }

    async def connect(self) -> bool:
        if not self.api_key or not self.api_secret:
            print("[ALPACA] ALPACA_API_KEY / ALPACA_API_SECRET not set")
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/v2/account", headers=self._headers)
            if resp.status_code == 200:
                print(f"[ALPACA] connected in {'PAPER' if self.paper_mode else 'LIVE'} mode")
                return True
            print(f"[ALPACA] auth failed: HTTP {resp.status_code}")
            return False
        except Exception as exc:
            print(f"[ALPACA] connection error: {exc}")
            return False

    async def get_account_summary(self) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.base_url}/v2/account", headers=self._headers)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}"}
        data = resp.json()
        return {
            "cash": float(data.get("cash", 0)),
            "equity": float(data.get("equity", 0)),
            "timestamp": datetime.now(timezone.utc),
        }

    async def get_positions(self) -> List[Position]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.base_url}/v2/positions", headers=self._headers)
        if resp.status_code != 200:
            return []
        return [
            Position(
                symbol=p["symbol"],
                qty=float(p["qty"]),
                avg_price=float(p["avg_entry_price"]),
            )
            for p in resp.json()
        ]

    async def submit_order(self, order: Order) -> dict:
        payload = {
            "symbol": order.symbol,
            "qty": str(order.qty),
            "side": order.side,
            "type": "market",
            "time_in_force": "gtc" if order.asset_class == "crypto" else "day",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/v2/orders", json=payload, headers=self._headers
            )
        if resp.status_code in (200, 201):
            data = resp.json()
            return {
                "order_id": data["id"],
                "status": data["status"],
                "timestamp": datetime.now(timezone.utc),
            }
        return {"status": "rejected", "reason": f"HTTP {resp.status_code}: {resp.text[:200]}"}

    async def cancel_order(self, order_id: str) -> bool:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.delete(
                f"{self.base_url}/v2/orders/{order_id}", headers=self._headers
            )
        return resp.status_code in (200, 204)

    async def get_order_status(self, order_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base_url}/v2/orders/{order_id}", headers=self._headers
            )
        if resp.status_code != 200:
            return {"status": "not_found"}
        data = resp.json()
        avg = data.get("filled_avg_price")
        return {
            "order_id": data["id"],
            "status": data["status"],
            "filled_qty": float(data.get("filled_qty") or 0),
            "filled_price": float(avg) if avg else None,
        }

    async def get_market_data(self, symbol: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.DATA_URL}/v2/stocks/{symbol}/quotes/latest", headers=self._headers
            )
        if resp.status_code != 200:
            return {}
        q = resp.json().get("quote", {})
        return {
            "symbol": symbol,
            "price": float(q.get("ap") or 0),
            "bid": float(q.get("bp") or 0),
            "ask": float(q.get("ap") or 0),
            "timestamp": datetime.now(timezone.utc),
        }

    def is_paper_only(self) -> bool:
        return False
