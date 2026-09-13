"""Pump public-evidence practice sandbox with exact proposal binding.

This module is simulation-only. It performs no Pump network access, accepts no
wallet credentials, and cannot move real money. Manual public Pump evidence is
normalized by the existing observer, mirrored into the paper-only crypto
sandbox, and carried inside the approval fingerprint for the exact proposal.
"""

import argparse
import asyncio
import json
import os
from hashlib import sha256
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from math import isfinite
from urllib.parse import urlparse

from approvals.queue import approval_fingerprint
from backend.crypto_sandbox_server import CryptoSandboxHandler, CryptoSandboxSession
from broker.base import Order
from market import PumpFunPracticeShadowBridge


PUMP_SANDBOX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sleep Wealth · Pump Practice Sandbox</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;--ink:#080b14;--panel:#111429;--line:#353b68;--mint:#72f7c6;--violet:#c8a2ff;--gold:#ffd86e;--text:#f6f0dc;--muted:#a7acc6;--coral:#ff8c83}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 84% 6%,rgba(200,162,255,.2),transparent 30%),radial-gradient(circle at 10% 86%,rgba(114,247,198,.12),transparent 28%),var(--ink);color:var(--text);display:grid;place-items:center;padding:22px}
main{width:min(980px,100%);padding:30px;background:linear-gradient(180deg,#151932,var(--panel));border:1px solid var(--line);border-radius:26px 7px 26px 7px;box-shadow:16px 16px 0 rgba(255,216,110,.08)}
.top,.actions{display:flex;gap:9px;flex-wrap:wrap}.badge{padding:8px 11px;border:1px solid var(--line);border-radius:999px;color:var(--mint);font:800 .72rem/1 ui-monospace,monospace}.danger{color:var(--coral)}h1{font-size:clamp(2.7rem,8vw,5rem);line-height:.9;letter-spacing:-.06em;margin:22px 0 10px}p{color:var(--muted);line-height:1.55;max-width:800px}
.wallet{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:22px 0}.metric{background:#0b0e1e;border:1px solid var(--line);padding:15px;border-radius:15px 4px 15px 4px}.metric span{display:block;color:var(--muted);font-size:.72rem;text-transform:uppercase}.metric strong{display:block;margin-top:7px;font-size:1.3rem}
form{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:10px;margin-top:18px}label{display:grid;gap:6px;color:var(--muted);font-size:.72rem;text-transform:uppercase}input,select,button{font:inherit;border:1px solid var(--line);background:#090c19;color:var(--text);padding:12px;border-radius:11px 4px 11px 4px}button{cursor:pointer;background:var(--mint);color:#07110e;font-weight:900}.actions{margin-top:12px}.actions button{flex:1}.approve{background:var(--violet)}button:disabled{opacity:.42;cursor:not-allowed}.truth{margin-top:18px;border-left:4px solid var(--gold);background:rgba(255,216,110,.07);padding:13px;color:#ddd3b9}pre{min-height:190px;max-height:390px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#05070d;border:1px solid var(--line);padding:15px;border-radius:15px 4px 15px 4px;color:#bcead9;font:500 .75rem/1.5 ui-monospace,monospace}
@media(max-width:760px){.wallet{grid-template-columns:1fr}form{grid-template-columns:1fr 1fr}}@media(max-width:520px){body{padding:10px}main{padding:20px}form{grid-template-columns:1fr}.actions{flex-direction:column}}
</style>
</head>
<body>
<main>
<div class="top"><span class="badge">PUMP PUBLIC EVIDENCE → PRACTICE</span><span class="badge danger">NO WALLET · NO SIGNING · $0 REAL MONEY</span></div>
<h1>Observe. Bind. Practice.</h1>
<p>Paste public Pump evidence. Sleep Wealth binds that exact evidence fingerprint into a sandbox proposal, then requires a separate approval before a simulated fill.</p>
<section class="wallet" aria-label="Sandbox wallet">
<div class="metric"><span>Cash</span><strong id="wallet-cash">…</strong></div>
<div class="metric"><span>Equity</span><strong id="wallet-equity">…</strong></div>
<div class="metric"><span>Authority</span><strong>practice only</strong></div>
</section>
<form id="pump-form">
<label>Public Pump URL<input id="source-url" value="https://pump.fun/coin/example"></label>
<label>Symbol<input id="symbol" value="MOM8" maxlength="24"></label>
<label>Mint<input id="mint" placeholder="Paste public mint"></label>
<label>Observed price<input id="price" value="0.50" inputmode="decimal"></label>
<label>Quantity<input id="qty" value="10" inputmode="decimal"></label>
<label>Side<select id="side"><option value="buy">Buy</option><option value="sell">Sell</option></select></label>
</form>
<div class="actions">
<button id="create-proposal" type="button">1 · Bind evidence + create proposal</button>
<button id="approve-proposal" class="approve" type="button" disabled>2 · Approve + simulate</button>
</div>
<div class="truth"><strong>Truth lock:</strong> Pump evidence is manual and read-only. Its fingerprint is evidence, not authority. The approval applies only to the exact practice proposal fingerprint. Live money remains disabled.</div>
<pre id="result" aria-live="polite">Ready for public Pump evidence.</pre>
</main>
<script>
const result=document.getElementById('result');
const approve=document.getElementById('approve-proposal');
const prefix=window.location.pathname.startsWith('/sandbox')?'/sandbox':'';
let proposalId=null;
async function refreshWallet(){
  const response=await fetch(`${prefix}/api/wallet`);const data=await response.json();
  document.getElementById('wallet-cash').textContent=`$${Number(data.cash).toFixed(2)}`;
  document.getElementById('wallet-equity').textContent=`$${Number(data.equity).toFixed(2)}`;
}
document.getElementById('create-proposal').addEventListener('click',async()=>{
  approve.disabled=true;proposalId=null;result.textContent='Binding public evidence…';
  const body={
    evidence:{
      source_url:document.getElementById('source-url').value,
      symbol:document.getElementById('symbol').value,
      mint:document.getElementById('mint').value,
      name:'MOM OF 8',
      price:Number(document.getElementById('price').value),
      observed_at:new Date().toISOString()
    },
    qty:Number(document.getElementById('qty').value),
    side:document.getElementById('side').value
  };
  const response=await fetch(`${prefix}/api/pump-shadow/proposals`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json();result.textContent=JSON.stringify(data,null,2);
  if(data.status==='pending'){proposalId=data.proposal_id;approve.disabled=false}
});
approve.addEventListener('click',async()=>{
  if(!proposalId)return;
  approve.disabled=true;result.textContent='Approving exact evidence-bound proposal…';
  const response=await fetch(`${prefix}/api/proposals/${encodeURIComponent(proposalId)}/approve`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
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
    return {"fingerprint": fingerprint, "cookie": f"pump-sandbox-{kind}-v1:{fingerprint[:24]}"}


class PumpEvidenceSandboxSession(CryptoSandboxSession):
    """Crypto sandbox whose approval fingerprint binds exact Pump public evidence."""

    def __init__(self, initial_cash: float = 100.0):
        super().__init__(initial_cash=initial_cash)
        self.bridge = PumpFunPracticeShadowBridge()

    async def propose_from_pump_evidence(self, evidence: dict, qty=10, side="buy") -> dict:
        with self._lock:
            await self._ensure_connected()
            observation = self.bridge.observe(evidence)
            mirror = self.bridge.mirror_to_practice(observation, self.broker)
            side = str(side).strip().lower()
            if side not in {"buy", "sell"}:
                raise ValueError("side must be 'buy' or 'sell'")
            try:
                qty = float(qty)
            except (TypeError, ValueError) as exc:
                raise ValueError("qty must be a number") from exc
            if not isfinite(qty) or qty <= 0:
                raise ValueError("qty must be finite and greater than zero")

            account = await self.broker.get_account_summary()
            estimated_cost = qty * observation.price
            reasons = []
            if side == "buy" and estimated_cost > float(account["cash"]):
                reasons.append("insufficient sandbox cash")
            if side == "sell" and qty > float(self.broker.positions.get(observation.symbol, 0.0)):
                reasons.append("insufficient sandbox asset balance")

            pump_binding = {
                **mirror.to_dict(),
                "source": observation.source,
                "source_classification": observation.source_classification,
                "observed_at": observation.observed_at,
            }
            evaluation = {
                "allowed": not reasons,
                "reason": "; ".join(reasons) if reasons else "OK",
                "wallet_mode": "sandbox",
                "real_money": False,
                "live_execution": False,
                "price": observation.price,
                "estimated_cost": estimated_cost,
                "authority_ceiling": "sandbox-simulation-only",
                "pump_shadow": pump_binding,
                "public_evidence_fingerprint": observation.public_evidence_fingerprint,
                "evidence_observation_fingerprint": observation.fingerprint,
            }
            order = Order(
                symbol=observation.symbol,
                qty=qty,
                side=side,
                asset_class="crypto",
            )
            if not evaluation["allowed"]:
                return {
                    "status": "blocked",
                    "stage": "evaluation",
                    "order": {"symbol": observation.symbol, "qty": qty, "side": side, "asset_class": "crypto"},
                    "evaluation": evaluation,
                    "pump_shadow": pump_binding,
                    "real_money": False,
                    "live_execution": False,
                }

            proposal_id = self.queue.add(order, evaluation)
            fingerprint = approval_fingerprint(order, evaluation)
            marker = _marker(
                "proposal",
                {
                    "proposal_id": proposal_id,
                    "approval_fingerprint": fingerprint,
                    "public_evidence_fingerprint": observation.public_evidence_fingerprint,
                    "evidence_observation_fingerprint": observation.fingerprint,
                },
            )
            return {
                "status": "pending",
                "stage": "approval",
                "proposal_id": proposal_id,
                "order": {"symbol": observation.symbol, "qty": qty, "side": side, "asset_class": "crypto"},
                "evaluation": evaluation,
                "pump_shadow": pump_binding,
                "public_evidence_fingerprint": observation.public_evidence_fingerprint,
                "evidence_observation_fingerprint": observation.fingerprint,
                "proposal_fingerprint": fingerprint,
                "proposal_cookie": marker["cookie"],
                "authority": "none-until-explicit-sandbox-approval",
                "real_money": False,
                "live_execution": False,
            }

    async def approve_and_execute(self, proposal_id: str) -> dict:
        request = self.queue.get(str(proposal_id))
        pump_shadow = dict(request.evaluation.get("pump_shadow") or {}) if request else {}
        public_fingerprint = request.evaluation.get("public_evidence_fingerprint") if request else None
        observation_fingerprint = request.evaluation.get("evidence_observation_fingerprint") if request else None
        result = await super().approve_and_execute(proposal_id)
        if pump_shadow:
            result["pump_shadow"] = pump_shadow
            result["public_evidence_fingerprint"] = public_fingerprint
            result["evidence_observation_fingerprint"] = observation_fingerprint
            if result.get("status") == "executed":
                result["truth"] = (
                    "explicit approval bound to the exact Pump public-evidence practice proposal; "
                    "no real money moved"
                )
        return result


class PumpEvidenceSandboxHandler(CryptoSandboxHandler):
    server_version = "SleepWealthPumpSandbox/0.1"

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self._html(PUMP_SANDBOX_HTML)
        if path == "/health":
            return self._json(
                {
                    "status": "ok",
                    "wallet_mode": "sandbox",
                    "pump_public_evidence_binding": True,
                    "pump_network_access": False,
                    "real_money": False,
                    "live_execution": False,
                }
            )
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/pump-shadow/proposals":
            try:
                payload = self._body()
                evidence = payload.get("evidence")
                if not isinstance(evidence, dict):
                    raise TypeError("evidence must be a JSON object")
                result = asyncio.run(
                    self.session.propose_from_pump_evidence(
                        evidence,
                        payload.get("qty", 10),
                        payload.get("side", "buy"),
                    )
                )
                status = HTTPStatus.CREATED if result["status"] == "pending" else HTTPStatus.OK
                return self._json(result, status)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                return self._json(
                    {"status": "invalid", "reason": str(exc), "real_money": False, "live_execution": False},
                    HTTPStatus.BAD_REQUEST,
                )
            except RuntimeError as exc:
                return self._json(
                    {"status": "error", "reason": str(exc), "real_money": False, "live_execution": False},
                    HTTPStatus.BAD_GATEWAY,
                )
        return super().do_POST()


def serve(host="127.0.0.1", port=8768):
    initial_cash = float(os.getenv("SLEEPWEALTH_CRYPTO_SANDBOX_CASH", "100"))
    server = ThreadingHTTPServer((host, port), PumpEvidenceSandboxHandler)
    server.sandbox_session = PumpEvidenceSandboxSession(initial_cash=initial_cash)
    print(f"Sleep Wealth Pump evidence sandbox listening on http://{host}:{port}")
    print("pump_network_access=false | wallet=sandbox | real_money=false | live_execution=false")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="Sleep Wealth Pump public-evidence practice sandbox")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
