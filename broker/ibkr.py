"""Interactive Brokers adapter.

Built on `ib_async` talking to a headless IB Gateway.

Repository policy is stronger than a factory convention: this adapter itself is
paper-only. Construction, connection, reconnect, reads, and writes all fail
closed unless three independent signals agree:

1. the configured socket port is a known paper port (7497 TWS / 4002 Gateway)
2. every broker-reported managed account begins with ``DU``
3. the caller explicitly requested paper mode

No successful reconnect resumes trading implicitly. A reconnect only restores a
paper connection after re-proving the broker/account boundary.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from .base import BaseBroker, Order, Position

TWS_LIVE_PORT = 7496
TWS_PAPER_PORT = 7497
GATEWAY_LIVE_PORT = 4001
GATEWAY_PAPER_PORT = 4002

PAPER_PORTS = {TWS_PAPER_PORT, GATEWAY_PAPER_PORT}
PAPER_ACCOUNT_PREFIX = "DU"
MARKET_DATA_DELAYED = 3
DONE_STATES = {"Filled", "Cancelled", "ApiCancelled"}


class PaperModeViolation(RuntimeError):
    """Raised whenever the adapter cannot prove the repository paper boundary."""


@dataclass
class IBKRBroker(BaseBroker):
    """IBKR paper adapter. Live construction is intentionally unsupported."""

    paper_mode: bool = True
    host: str = "127.0.0.1"
    port: int = GATEWAY_PAPER_PORT
    client_id: int = 11
    account: Optional[str] = None
    use_delayed_data: bool = True
    connect_timeout: float = 8.0
    request_interval_seconds: float = 0.03

    ib: object = field(default=None, init=False, repr=False)
    managed_accounts: List[str] = field(default_factory=list, init=False)
    _connected: bool = field(default=False, init=False)
    _last_request_at: float = field(default=0.0, init=False, repr=False)
    _request_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self._assert_paper_configuration()
        if self.request_interval_seconds < 0:
            raise ValueError("request_interval_seconds must be >= 0")

    # ---- lifecycle ---------------------------------------------------

    def _assert_paper_configuration(self) -> None:
        if not self.paper_mode:
            raise PaperModeViolation(
                "Live IBKR construction is disabled by repository policy. Use paper_mode=True."
            )
        if self.port not in PAPER_PORTS:
            raise PaperModeViolation(
                f"IBKR paper adapter requires a paper port {sorted(PAPER_PORTS)}; got {self.port}."
            )

    async def _pace(self) -> None:
        """Keep adapter-originated socket traffic comfortably below IBKR pacing limits."""
        if self.request_interval_seconds <= 0:
            return
        async with self._request_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            wait = self.request_interval_seconds - (now - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = loop.time()

    async def connect(self) -> bool:
        self._assert_paper_configuration()
        try:
            from ib_async import IB
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "ib_async is required for the IBKR paper adapter. Install the pinned "
                "project IBKR dependency before using this broker."
            ) from exc

        self.ib = IB()
        try:
            await self.ib.connectAsync(
                self.host,
                self.port,
                clientId=self.client_id,
                timeout=self.connect_timeout,
            )
            self.managed_accounts = list(self.ib.managedAccounts())

            if not self.managed_accounts:
                raise PaperModeViolation(
                    "No managed accounts returned. Cannot prove paper identity."
                )
            if not self.is_paper_only():
                live = [
                    account
                    for account in self.managed_accounts
                    if not account.startswith(PAPER_ACCOUNT_PREFIX)
                ]
                raise PaperModeViolation(
                    f"Broker identity is not provably paper; non-DU accounts={live}."
                )

            if self.account is None:
                if len(self.managed_accounts) != 1:
                    raise PaperModeViolation(
                        "Multiple managed accounts require an explicit account selection."
                    )
                self.account = self.managed_accounts[0]
            elif self.account not in self.managed_accounts:
                raise PaperModeViolation(
                    f"Configured account {self.account!r} is not managed by this session."
                )

            if self.use_delayed_data:
                await self._pace()
                self.ib.reqMarketDataType(MARKET_DATA_DELAYED)

            self._connected = bool(self.ib.isConnected())
            if not self._connected:
                raise ConnectionError("IBKR socket did not remain connected after handshake.")
            return True
        except Exception:
            if self.ib is not None and getattr(self.ib, "isConnected", lambda: False)():
                self.ib.disconnect()
            self._connected = False
            raise

    async def reconnect(self, max_attempts: int = 5, base_delay: float = 0.5) -> bool:
        """Reconnect with bounded exponential backoff and re-prove paper identity.

        This never restores or resubmits orders. Callers must separately decide
        whether any paper workflow should continue after reconnect evidence exists.
        """
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if base_delay < 0:
            raise ValueError("base_delay must be >= 0")

        last_error: Optional[Exception] = None
        for attempt in range(max_attempts):
            await self.disconnect()
            if attempt:
                await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
            try:
                return await self.connect()
            except PaperModeViolation:
                raise
            except Exception as exc:  # pragma: no cover - timing/network dependent
                last_error = exc

        raise ConnectionError(
            f"IBKR paper reconnect failed after {max_attempts} attempt(s): {last_error}"
        )

    async def disconnect(self) -> None:
        if self.ib is not None and getattr(self.ib, "isConnected", lambda: False)():
            self.ib.disconnect()
        self._connected = False
        self.managed_accounts = []

    # ---- reads -------------------------------------------------------

    async def get_account_summary(self) -> dict:
        self._require_connection()
        await self._pace()
        rows = await self.ib.accountSummaryAsync(self.account)
        cash = equity = available_funds = 0.0
        for row in rows:
            if row.currency not in ("USD", ""):
                continue
            if row.tag == "TotalCashValue":
                cash = float(row.value)
            elif row.tag == "NetLiquidation":
                equity = float(row.value)
            elif row.tag == "AvailableFunds":
                available_funds = float(row.value)
        return {
            "cash": cash,
            "equity": equity,
            "available_funds": available_funds,
            "account": self.account,
            "paper": True,
            "timestamp": datetime.now(timezone.utc),
        }

    async def get_positions(self) -> List[Position]:
        self._require_connection()
        out = []
        for position in self.ib.positions(self.account):
            if position.position == 0:
                continue
            out.append(
                Position(
                    symbol=position.contract.symbol,
                    qty=float(position.position),
                    avg_price=float(position.avgCost),
                )
            )
        return out

    async def get_market_data(self, symbol: str) -> dict:
        import math

        self._require_connection()
        contract = await self._qualify(symbol)
        await self._pace()
        [ticker] = await self.ib.reqTickersAsync(contract)

        def clean(value):
            if value is None:
                return None
            if isinstance(value, float) and math.isnan(value):
                return None
            return float(value)

        candidates = (
            clean(ticker.last),
            clean(ticker.close),
            clean(ticker.marketPrice()),
        )
        price = next((value for value in candidates if value is not None), None)
        return {
            "symbol": symbol,
            "price": price,
            "bid": clean(ticker.bid),
            "ask": clean(ticker.ask),
            "delayed": self.use_delayed_data,
            "timestamp": datetime.now(timezone.utc),
        }

    async def get_order_status(self, order_id: str) -> dict:
        self._require_connection()
        for trade in self.ib.trades():
            if (
                str(trade.order.orderId) == str(order_id)
                or str(trade.order.permId) == str(order_id)
            ):
                status = trade.orderStatus
                return {
                    "order_id": order_id,
                    "status": status.status,
                    "filled": float(status.filled),
                    "remaining": float(status.remaining),
                    "avg_fill_price": float(status.avgFillPrice or 0.0),
                    "done": status.status in DONE_STATES,
                }
        return {"order_id": order_id, "status": "not_found"}

    # ---- writes: paper only -----------------------------------------

    async def submit_order(self, order: Order, cash_qty: Optional[float] = None) -> dict:
        """Submit a paper market order after re-proving the paper boundary."""
        self._require_connection()

        side_raw = str(order.side).strip().lower()
        if side_raw not in {"buy", "sell"}:
            return {"status": "rejected", "reason": "side must be 'buy' or 'sell'"}

        if cash_qty is not None and float(cash_qty) <= 0:
            return {"status": "rejected", "reason": "cash_qty must be > 0"}
        if cash_qty is None and order.qty <= 0:
            return {"status": "rejected", "reason": "qty must be > 0"}

        from ib_async import MarketOrder

        try:
            contract = await self._qualify(order.symbol)
            side = "BUY" if side_raw == "buy" else "SELL"
            if cash_qty is not None:
                ib_order = MarketOrder(side, 0, cashQty=float(cash_qty))
            else:
                ib_order = MarketOrder(side, float(order.qty))

            ib_order.account = self.account
            await self._pace()
            trade = self.ib.placeOrder(contract, ib_order)
            await asyncio.sleep(0)

            status = trade.orderStatus
            if status.status == "ValidationError":
                reason = trade.log[-1].message if trade.log else "validation error"
                return {"status": "rejected", "reason": reason}

            return {
                "order_id": str(trade.order.orderId),
                "perm_id": str(trade.order.permId),
                "status": status.status,
                "filled": float(status.filled),
                "avg_fill_price": float(status.avgFillPrice or 0.0),
                "timestamp": datetime.now(timezone.utc),
            }
        except PaperModeViolation:
            raise
        except Exception as exc:
            return {"status": "rejected", "reason": f"{type(exc).__name__}: {exc}"}

    async def cancel_order(self, order_id: str) -> bool:
        self._require_connection()
        for trade in self.ib.trades():
            if str(trade.order.orderId) == str(order_id):
                await self._pace()
                self.ib.cancelOrder(trade.order)
                return True
        return False

    async def cancel_all(self) -> bool:
        """Paper kill-switch primitive. Pull every working paper order."""
        self._require_connection()
        await self._pace()
        self.ib.reqGlobalCancel()
        return True

    # ---- proof -------------------------------------------------------

    def is_paper_only(self) -> bool:
        port_ok = self.port in PAPER_PORTS
        accounts_ok = bool(self.managed_accounts) and all(
            account.startswith(PAPER_ACCOUNT_PREFIX) for account in self.managed_accounts
        )
        return bool(port_ok and accounts_ok and self.paper_mode)

    def paper_proof(self) -> dict:
        return {
            "port": self.port,
            "port_is_paper": self.port in PAPER_PORTS,
            "managed_accounts": list(self.managed_accounts),
            "all_accounts_paper": bool(self.managed_accounts)
            and all(
                account.startswith(PAPER_ACCOUNT_PREFIX)
                for account in self.managed_accounts
            ),
            "configured_paper": self.paper_mode,
            "provably_paper": self.is_paper_only(),
        }

    # ---- internals ---------------------------------------------------

    async def _qualify(self, symbol: str):
        from ib_async import Stock

        self._require_connection()
        contract = Stock(symbol, "SMART", "USD")
        await self._pace()
        await self.ib.qualifyContractsAsync(contract)
        return contract

    def _require_connection(self) -> None:
        socket_connected = bool(
            self.ib is not None
            and getattr(self.ib, "isConnected", lambda: False)()
        )
        if not self._connected or not socket_connected:
            self._connected = False
            raise RuntimeError("IBKR adapter is not connected. Reconnect and re-prove paper mode.")
        if not self.is_paper_only():
            self._connected = False
            if self.ib is not None and socket_connected:
                self.ib.disconnect()
            raise PaperModeViolation(
                "IBKR session no longer satisfies the paper proof; disconnected fail-closed."
            )
