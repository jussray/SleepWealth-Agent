"""HTTP/UI carrier for the governed crypto sandbox wallet.

This module is intentionally simulation-only. It accepts no credentials, exposes
no transfer/deposit endpoint, and never creates real-money authority.
"""

import argparse
import asyncio
import json
import os
import threading
from hashlib import sha256
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from approvals.queue import ApprovalQueue, ApprovalStatus, approval_fingerprint
from broker.base import Order
from broker.crypto_sandbox import CryptoSandboxBroker


SANDBOX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sleep Wealth · Crypto Sandbox Wallet</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;--ink:#07110f;--panel:#0d1916;--line:#24453c;--mint:#80ffd1;--violet:#b88cff;--sand:#f4e7c7;--muted:#9ab5aa;--coral:#ff8f7d}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 80% 8%,rgba(184,140,255,.18),transparent 30%),radial-gradient(circle at 12% 82%,rgba(128,255,209,.12),transparent 28%),var(--ink);color:var(--sand);padding:24px;display:grid;place-items:center}
main{width:min(920px,100%);background:linear-gradient(180deg,#10201b,var(--panel));border:1px solid var(--line);border-radius:26px 8px 26px 8px;padding:30px;box-shadow:18px 18px 0 rgba(184,140,255,.12)}
.top{display:flex;gap:8px;flex-wrap:wrap}.badge{border:1px solid var(--line);border-radius:999px;padding:8px 11px;font:800 .72rem/1 ui-monospace,monospace;color:var(--mint)}.danger{color:var(--coral)}
h1{font-size:clamp(2.7rem,8vw,5rem);line-height:.9;letter-spacing:-.055em;margin:22px 0 10px}p{color:var(--muted);line-height:1.55;max-width:720px}
.wallet{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:22px 0}.metric{background:#091410;border:1px solid var(--line);border-radius:16px 4px 16px 4px;padding:16px}.metric span{display:block;color:var(--muted);font-size:.72rem;text-transform:uppercase}.metric strong{display:block;margin-top:7px;font-size:1.35rem}
form{display:grid;grid-template-columns:1.2fr .8fr .8fr .8fr;gap:10px;margin-top:20px}label{display:grid;gap:7px;color:var(--muted);font-size:.74rem;text-transform:uppercase}input,select,button{font:inherit;border:1px solid var(--line);background:#08120f;color:var(--sand);padding:12px;border-radius:12px 4px 12px 4px}button{cursor:pointer;background:var(--mint);color:#06100d;font-weight:900}.actions{display:flex;gap:10px;margin-top:12px}.actions button{flex:1}.actions .approve{background:var(--violet)}button:disabled{opacity:.42;cursor:not-allowed}
.truth{margin-top:18px;border-left:4px solid var(--coral);background:rgba(255,143,125,.08);padding:13px;color:#d7c4ba}pre{min-height:180px;max-height:360px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#050b09;border:1px solid var(--line);padding:15px;border-radius:16px 4px 16px 4px;color:#bfe6d6;font:500 .76rem/1.5 ui-monospace,monospace}
@media(max-width:720px){.wallet{grid-template-columns:1fr}form{grid-template-columns:1fr 1fr}}@media(max-width:500px){body{padding:12px}main{padding:20px}form{grid-template-columns:1fr}.actions{flex-direction:column}}
</style>
</head>
<body>
<main>
<div class="top"><span class="badge">CRYPTO SANDBOX WALLET</span><span class="badge danger">$0 REAL MONEY · LIVE MONEY DISABLED</span></div>
<h1>Wallet-shaped. Fund-safe.</h1>
<p>Exercise the full proposal → approval → simulated transaction → receipt path without private keys, deposits, transfers, or real funds.</p>
<section class="wallet" aria-label="Sandbox wallet">
<div class="metric"><span>Cash</span><strong id="wallet-cash">…</strong></div>
<div class="metric"><span>Equity</span><strong id="wallet-equity">…</strong></div>
<div class="metric"><span>Mode</span><strong id="wallet-mode">sandbox</strong></div>
</section>
<form id="proposal-form">
<label>Token<input id="symbol" value="MOM8" maxlength="24"></label>
<label>Quantity<input id="qty" value="10" inputmode="decimal"></label>
<label>Side<select id="side"><option value="buy">Buy</option><option value="sell">Sell</option></select></label>
<label>Synthetic price<input id="price" value="0.50" inputmode="decimal"></label>
</form>
<div class="actions">
<button id="create-proposal" type="button">1 · Create proposal</button>
<button id="approve-proposal" class="approve" type="button" disabled>2 · Approve + simulate</button>
</div>
<div class="truth"><strong>Authority lock:</strong> approval applies only to the exact sandbox proposal fingerprint. Continuity markers are evidence, not authority. No real money can move from this surface.</div>
<pre id="result" aria-live="polite">Ready to create a sandbox proposal.</pre>
</main>
<script>
const result=document.getElementById('result');
const approve=document.getElementById('approve-proposal');
let proposalId=null;
async function refreshWallet(){
  const response=await fetch('/api/wallet');const data=await response.json();
  document.getElementById('wallet-cash').textContent=`$${Number(data.cash).toFixed(2)}`;
  document.getElementById('wallet-equity').textContent=`$${Number(data.equity).toFixed(2)}`;
  document.getElementById('wallet-mode').textContent=data.wallet_mode;
}
document.getElementById('create-proposal').addEventListener('click',async()=>{
  approve.disabled=true;proposalId=null;result.textContent='Creating proposal…';
  const body={symbol:document.getElementById('symbol').value,qty:Number(document.getElementById('qty').value),side:document.getElementById('side').value,price:Number(document.getElementById('price').value)};
  const response=await fetch('/api/proposals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json();result.textContent=JSON.stringify(data,null,2);
  if(data.status==='pending'){proposalId=data.proposal_id;approve.disabled=false}
});
approve.addEventListener('click',async()=>{
  if(!proposalId)return;
  approve.disabled=true;result.textContent='Approving exact proposal + simulating…';
  const response=await fetch(`/api/proposals/${encodeURIComponent(proposalId)}/approve`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const data=await response.json();result.textContent=JSON.stringify(data,null,2);await refreshWallet();
});
refreshWallet();
</script>
</body>
</html>
"""


def _marker(kind: str, payload: dict) -> dict:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    fingerprint = sha256(encoded).hexdigest()
    return {
        "fingerprint": fingerprint,
        "cookie": f"crypto-sandbox-{kind}-v1:{fingerprint[:24]}",
    }


class CryptoSandboxSession:
    """One in-memory wallet session with exact-proposal approval binding."""

    def __init__(self, initial_cash: float = 100.0):
        self.broker = CryptoSandboxBroker(initial_cash=float(initial_cash))
        self.queue = ApprovalQueue(state_path=None, session_id="crypto-sandbox-http")
        self._connected = False
        self._lock = threading.RLock()

    async def _ensure_connected(self) -> None:
        if not self._connected:
            if not await self.broker.connect():
                raise RuntimeError("crypto sandbox wallet connection failed")
            self._connected = True

    async def wallet(self) -> dict:
        with self._lock:
            await self._ensure_connected()
            summary = await self.broker.get_account_summary()
            return {
                **summary,
                "status": "ok",
                "authority": "sandbox-simulation-only",
                "live_execution": False,
            }

    async def propose(self, symbol: str, qty: float, side: str, price: float) -> dict:
        with self._lock:
            await self._ensure_connected()
            symbol = str(symbol).strip().upper()
            side = str(side).strip().lower()
            if not symbol:
                raise ValueError("symbol is required")
            if side not in {"buy", "sell"}:
                raise ValueError("side must be 'buy' or 'sell'")
            try:
                qty = float(qty)
                price = float(price)
            except (TypeError, ValueError) as exc:
                raise ValueError("qty and price must be numbers") from exc
            if qty <= 0 or price <= 0:
                raise ValueError("qty and price must be greater than zero")

            self.broker.set_market_price(symbol, price)
            account = await self.broker.get_account_summary()
            estimated_cost = qty * price
            reasons = []
            if side == "buy" and estimated_cost > float(account["cash"]):
                reasons.append("insufficient sandbox cash")
            if side == "sell" and qty > float(self.broker.positions.get(symbol, 0.0)):
                reasons.append("insufficient sandbox asset balance")

            evaluation = {
                "allowed": not reasons,
                "reason": "; ".join(reasons) if reasons else "OK",
                "wallet_mode": "sandbox",
                "real_money": False,
                "live_execution": False,
                "price": price,
                "estimated_cost": estimated_cost,
                "authority_ceiling": "sandbox-simulation-only",
            }
            order = Order(symbol=symbol, qty=qty, side=side, asset_class="crypto")
            if not evaluation["allowed"]:
                return {
                    "status": "blocked",
                    "stage": "evaluation",
                    "order": {
                        "symbol": symbol,
                        "qty": qty,
                        "side": side,
                        "asset_class": "crypto",
                    },
                    "evaluation": evaluation,
                    "real_money": False,
                    "live_execution": False,
                }

            proposal_id = self.queue.add(order, evaluation)
            fingerprint = approval_fingerprint(order, evaluation)
            marker = _marker(
                "proposal",
                {"proposal_id": proposal_id, "approval_fingerprint": fingerprint},
            )
            return {
                "status": "pending",
                "stage": "approval",
                "proposal_id": proposal_id,
                "order": {
                    "symbol": symbol,
                    "qty": qty,
                    "side": side,
                    "asset_class": "crypto",
                },
                "evaluation": evaluation,
                "proposal_fingerprint": fingerprint,
                "proposal_cookie": marker["cookie"],
                "authority": "none-until-explicit-sandbox-approval",
                "real_money": False,
                "live_execution": False,
            }

    async def approve_and_execute(self, proposal_id: str) -> dict:
        with self._lock:
            await self._ensure_connected()
            request = self.queue.get(str(proposal_id))
            if request is None:
                raise ValueError("proposal not found")
            if request.status is not ApprovalStatus.PENDING:
                return {
                    "status": "blocked",
                    "stage": "approval",
                    "proposal_id": request.proposal_id,
                    "reason": f"proposal status is {request.status.value}, not pending",
                    "real_money": False,
                    "live_execution": False,
                }
            if not request.evaluation.get("allowed", False):
                return {
                    "status": "blocked",
                    "stage": "approval",
                    "proposal_id": request.proposal_id,
                    "reason": "proposal evaluation is not allowed",
                    "real_money": False,
                    "live_execution": False,
                }
            if not self.queue.approve(
                request.proposal_id,
                "explicit crypto sandbox UI approval",
            ):
                raise RuntimeError("sandbox approval could not be recorded")
            if not self.queue.approval_is_intact(request.proposal_id):
                raise RuntimeError("sandbox approval fingerprint mismatch")
            approved = self.queue.get(request.proposal_id)
            approved_fingerprint = approved.approved_fingerprint if approved else None
            if not self.queue.begin_execution(request.proposal_id):
                raise RuntimeError("sandbox proposal could not enter execution")

            self.broker.set_market_price(
                request.order.symbol,
                float(request.evaluation["price"]),
            )
            execution = await self.broker.submit_order(request.order)
            if execution.get("status") == "rejected":
                self.queue.mark_execution_rejected(
                    request.proposal_id,
                    str(execution.get("reason") or "sandbox order rejected"),
                )
                return {
                    "status": "blocked",
                    "stage": "execution",
                    "proposal_id": request.proposal_id,
                    "execution": execution,
                    "approval_fingerprint": approved_fingerprint,
                    "real_money": False,
                    "live_execution": False,
                }

            order_id = execution.get("order_id")
            if not order_id or not self.queue.mark_executed(request.proposal_id, order_id):
                raise RuntimeError("sandbox execution receipt could not be persisted")
            wallet = await self.broker.get_account_summary()
            outcome = _marker(
                "outcome",
                {
                    "proposal_id": request.proposal_id,
                    "approval_fingerprint": approved_fingerprint,
                    "execution_fingerprint": execution.get("continuity_fingerprint"),
                    "order_id": order_id,
                },
            )
            return {
                "status": "executed",
                "stage": "complete",
                "proposal_id": request.proposal_id,
                "approval_fingerprint": approved_fingerprint,
                "approval_cookie": f"crypto-sandbox-approval-v1:{str(approved_fingerprint)[:24]}",
                "execution": execution,
                "wallet": wallet,
                "outcome_fingerprint": outcome["fingerprint"],
                "outcome_cookie": outcome["cookie"],
                "authority": "sandbox-simulation-only",
                "truth": "explicit approval bound to this exact sandbox proposal; no real money moved",
                "real_money": False,
                "live_execution": False,
            }


class CryptoSandboxHandler(BaseHTTPRequestHandler):
    server_version = "SleepWealthCryptoSandbox/0.1"

    @property
    def session(self) -> CryptoSandboxSession:
        return self.server.sandbox_session

    def _json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, default=str, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str):
        body = html.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode())
        if not isinstance(payload, dict):
            raise TypeError("request body must be a JSON object")
        return payload

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self._html(SANDBOX_HTML)
        if path == "/health":
            return self._json(
                {
                    "status": "ok",
                    "wallet_mode": "sandbox",
                    "real_money": False,
                    "live_execution": False,
                }
            )
        if path == "/api/wallet":
            try:
                return self._json(asyncio.run(self.session.wallet()))
            except RuntimeError as exc:
                return self._json(
                    {"status": "error", "reason": str(exc), "real_money": False},
                    HTTPStatus.BAD_GATEWAY,
                )
        return self._json({"status": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self._body()
            if path == "/api/proposals":
                result = asyncio.run(
                    self.session.propose(
                        payload.get("symbol", "MOM8"),
                        payload.get("qty", 10),
                        payload.get("side", "buy"),
                        payload.get("price", 0.5),
                    )
                )
                status = HTTPStatus.CREATED if result["status"] == "pending" else HTTPStatus.OK
                return self._json(result, status)
            if path.startswith("/api/proposals/") and path.endswith("/approve"):
                proposal_id = path.removeprefix("/api/proposals/").removesuffix("/approve").strip("/")
                if not proposal_id:
                    raise ValueError("proposal id is required")
                return self._json(asyncio.run(self.session.approve_and_execute(proposal_id)))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return self._json(
                {
                    "status": "invalid",
                    "reason": str(exc),
                    "real_money": False,
                    "live_execution": False,
                },
                HTTPStatus.BAD_REQUEST,
            )
        except RuntimeError as exc:
            return self._json(
                {
                    "status": "error",
                    "reason": str(exc),
                    "real_money": False,
                    "live_execution": False,
                },
                HTTPStatus.BAD_GATEWAY,
            )
        return self._json({"status": "not_found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, fmt, *args):
        print(f"[crypto-sandbox] {self.address_string()} - {fmt % args}")


def serve(host="127.0.0.1", port=8767):
    initial_cash = float(os.getenv("SLEEPWEALTH_CRYPTO_SANDBOX_CASH", "100"))
    server = ThreadingHTTPServer((host, port), CryptoSandboxHandler)
    server.sandbox_session = CryptoSandboxSession(initial_cash=initial_cash)
    print(f"Sleep Wealth crypto sandbox listening on http://{host}:{port}")
    print("wallet=sandbox | real_money=false | live_execution=false")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="Sleep Wealth crypto sandbox wallet lab")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
