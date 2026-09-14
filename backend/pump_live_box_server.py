"""Read-only Pump public-evidence box bound to sandbox-only approvals."""

import argparse
import asyncio
import json
import os
import threading
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from approvals.queue import ApprovalQueue, ApprovalStatus, approval_fingerprint
from backend.pump_sandbox_receipts import PumpSandboxReceiptBook
from broker.base import Order
from broker.crypto_sandbox import CryptoSandboxBroker
from gate.pump_practice_graduation import evaluate_pump_practice_graduation
from market.pump_shadow import PumpFunPracticeShadowBridge


HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sleep Wealth · Pump Live Box</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;--bg:#071014;--p:#101921;--l:#2b4653;--c:#63f5ff;--v:#bd92ff;--i:#f6f1df;--m:#9cb3bd;--w:#ffad78}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 10% 10%,#12353c,transparent 35%),var(--bg);color:var(--i);padding:20px;display:grid;place-items:center}
main{width:min(900px,100%);background:var(--p);border:1px solid var(--l);border-radius:8px 26px;padding:26px;box-shadow:-12px 12px 0 #102b30}
.badges{display:flex;gap:7px;flex-wrap:wrap}.b{border:1px solid var(--l);border-radius:999px;padding:7px 10px;color:var(--c);font:800 .72rem ui-monospace}.warn{color:var(--w)}
h1{font-size:clamp(2.6rem,8vw,5rem);line-height:.9;letter-spacing:-.055em;margin:20px 0 10px}p{color:var(--m);line-height:1.5}
.grid{display:grid;grid-template-columns:1.2fr .8fr;gap:14px}.box{border:1px solid var(--l);padding:16px;border-radius:16px 5px;background:#091218}
form{display:grid;grid-template-columns:1fr 1fr;gap:9px}label{display:grid;gap:5px;color:var(--m);font-size:.72rem;text-transform:uppercase}.wide{grid-column:1/-1}
input,select,button{font:inherit;border:1px solid var(--l);background:#071014;color:var(--i);padding:10px;border-radius:9px 4px}button{background:var(--c);color:#061014;font-weight:900}.approve{background:var(--v)}button:disabled{opacity:.4}.actions{display:flex;gap:9px;margin-top:10px}.actions button{flex:1}
.metric{border-bottom:1px solid var(--l);padding:10px 0}.metric span{display:block;color:var(--m);font-size:.68rem;text-transform:uppercase}.metric strong{display:block;margin-top:4px;overflow-wrap:anywhere}
.truth{margin-top:12px;border-left:4px solid var(--w);padding:10px;background:#201a18}pre{white-space:pre-wrap;overflow-wrap:anywhere;min-height:180px;max-height:350px;overflow:auto;background:#050a0e;border:1px solid var(--l);padding:12px}
@media(max-width:700px){.grid{grid-template-columns:1fr}}@media(max-width:480px){form{grid-template-columns:1fr}.wide{grid-column:auto}.actions{flex-direction:column}}
</style></head><body><main>
<div class="badges"><span class="b">PUMP LIVE BOX</span><span class="b">PUBLIC EVIDENCE · READ-ONLY</span><span class="b warn">SIMULATED EXECUTION ONLY</span></div>
<h1>Evidence in. Authority stays out.</h1>
<p>Bind one current public Pump.fun observation to an exact sandbox proposal. Changing the evidence changes the proposal fingerprint.</p>
<div class="grid"><section class="box"><form>
<label class="wide">Pump source URL<input id="source-url" value="https://pump.fun/coin/MOM8"></label>
<label>Symbol<input id="symbol" value="MOM8"></label>
<label>Mint<input id="mint" value="MOM8-DEMO-MINT"></label>
<label>Observed price<input id="price" value="0.50"></label>
<label>Quantity<input id="qty" value="10"></label>
<label>Side<select id="side"><option>buy</option><option>sell</option></select></label>
<label>Observed at<input id="observed-at"></label>
</form><div class="actions">
<button id="bind" type="button">1 · Bind evidence + propose</button>
<button id="approve" class="approve" type="button" disabled>2 · Approve + simulate</button>
</div></section><section class="box">
<div class="metric"><span>Sandbox cash</span><strong id="cash">…</strong></div>
<div class="metric"><span>Sandbox equity</span><strong id="equity">…</strong></div>
<div class="metric"><span>Sandbox P&amp;L</span><strong id="pnl">…</strong></div>
<div class="metric"><span>Practice review gate</span><strong id="graduation">PRACTICE_REQUIRED</strong></div>
<div class="metric"><span>Practice samples</span><strong id="practice-samples">0 / 0</strong></div>
<div class="metric"><span>Evidence authority</span><strong id="authority">none</strong></div>
<div class="metric"><span>Evidence fingerprint</span><strong id="efp">unbound</strong></div>
<div class="metric"><span>Proposal fingerprint</span><strong id="pfp">unbound</strong></div>
<div class="metric"><span>Last receipt</span><strong id="receipt">unrecorded</strong></div>
<div class="truth">“Live” means current evidence, not live trading. Practice graduation can only prepare evidence for adult review. It cannot connect a wallet, sign, fund, mint, trade, or authorize real-money execution.</div>
</section></div><pre id="result">Ready.</pre>
<script>
const R=document.getElementById('result'),A=document.getElementById('approve');let id=null;
document.getElementById('observed-at').value=new Date().toISOString();
async function wallet(){const r=await fetch('/api/wallet'),d=await r.json();document.getElementById('cash').textContent='$'+Number(d.cash).toFixed(2);document.getElementById('equity').textContent='$'+Number(d.equity).toFixed(2);document.getElementById('pnl').textContent=(Number(d.pnl_total)>=0?'+':'')+'$'+Number(d.pnl_total).toFixed(2);const gr=await fetch('/api/graduation'),g=await gr.json();document.getElementById('graduation').textContent=g.classification;document.getElementById('practice-samples').textContent=g.metrics.execution_count+' / '+g.metrics.minimum_executions}
document.getElementById('bind').onclick=async()=>{id=null;A.disabled=true;const evidence={source_url:document.getElementById('source-url').value,symbol:document.getElementById('symbol').value,mint:document.getElementById('mint').value,price:Number(document.getElementById('price').value),observed_at:document.getElementById('observed-at').value};const r=await fetch('/api/proposals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({evidence,qty:Number(document.getElementById('qty').value),side:document.getElementById('side').value})}),d=await r.json();R.textContent=JSON.stringify(d,null,2);if(d.status==='pending'){id=d.proposal_id;A.disabled=false;document.getElementById('authority').textContent=d.evidence.authority;document.getElementById('efp').textContent=d.evidence.fingerprint.slice(0,14)+'…';document.getElementById('pfp').textContent=d.proposal_fingerprint.slice(0,14)+'…'}};
A.onclick=async()=>{if(!id)return;A.disabled=true;const r=await fetch('/api/proposals/'+encodeURIComponent(id)+'/approve',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}),d=await r.json();R.textContent=JSON.stringify(d,null,2);if(d.receipt&&d.receipt.receipt_fingerprint){document.getElementById('receipt').textContent=d.receipt.receipt_fingerprint.slice(0,14)+'…'}await wallet()};
wallet();
</script></main></body></html>"""


class PumpLiveBoxSession:
    _DEFAULT = object()

    def __init__(
        self,
        initial_cash=100.0,
        *,
        state_path=_DEFAULT,
        session_id=None,
        audit_path=None,
        minimum_practice_executions=20,
        minimum_practice_round_trips=3,
    ):
        initial_cash = float(initial_cash)
        self.broker = CryptoSandboxBroker(initial_cash=initial_cash)
        self.bridge = PumpFunPracticeShadowBridge()
        self.receipts = PumpSandboxReceiptBook(initial_cash, audit_path=audit_path)
        self.execution_receipts = []
        self.minimum_practice_executions = int(minimum_practice_executions)
        self.minimum_practice_round_trips = int(minimum_practice_round_trips)
        if state_path is self._DEFAULT:
            self.queue = ApprovalQueue(session_id=session_id)
        else:
            self.queue = ApprovalQueue(state_path=state_path, session_id=session_id)
        self._connected = False
        self._lock = threading.RLock()

    async def _connect(self):
        if not self._connected:
            if not await self.broker.connect():
                raise RuntimeError("sandbox connection failed")
            self._connected = True

    async def wallet(self):
        with self._lock:
            await self._connect()
            return await self.receipts.portfolio(self.broker)

    async def graduation(self):
        with self._lock:
            await self._connect()
            wallet = await self.receipts.portfolio(self.broker)
            return evaluate_pump_practice_graduation(
                self.execution_receipts,
                wallet,
                minimum_executions=self.minimum_practice_executions,
                minimum_round_trips=self.minimum_practice_round_trips,
            )

    async def propose(self, evidence, qty, side):
        with self._lock:
            await self._connect()
            observation = self.bridge.observe(evidence)
            mirror = self.bridge.mirror_to_practice(observation, self.broker)
            side = str(side).strip().lower()
            qty = float(qty)
            if side not in {"buy", "sell"}:
                raise ValueError("side must be buy or sell")
            if qty <= 0:
                raise ValueError("qty must be greater than zero")
            account = await self.broker.get_account_summary()
            cost = qty * observation.price
            reasons = []
            if side == "buy" and cost > float(account["cash"]):
                reasons.append("insufficient sandbox cash")
            if side == "sell" and qty > float(self.broker.positions.get(observation.symbol, 0.0)):
                reasons.append("insufficient sandbox asset balance")
            evaluation = {
                "allowed": not reasons,
                "reason": "; ".join(reasons) if reasons else "OK",
                "price": observation.price,
                "estimated_cost": cost,
                "pump_observation_fingerprint": observation.fingerprint,
                "pump_public_evidence_fingerprint": observation.public_evidence_fingerprint,
                "pump_mirror_fingerprint": mirror.mirror_fingerprint,
                "pump_mint": observation.mint,
                "evidence_authority": observation.authority,
                "evidence_read_only": observation.read_only,
                "authority_ceiling": "sandbox-simulation-only",
                "real_money": False,
                "live_execution": False,
            }
            order = Order(observation.symbol, qty, side, "crypto")
            if reasons:
                return {
                    "status": "blocked",
                    "evaluation": evaluation,
                    "evidence": asdict(observation),
                    "real_money": False,
                    "live_execution": False,
                }
            proposal_id = self.queue.add(order, evaluation)
            fingerprint = approval_fingerprint(order, evaluation)
            return {
                "status": "pending",
                "stage": "approval",
                "proposal_id": proposal_id,
                "proposal_fingerprint": fingerprint,
                "proposal_cookie": f"pump-live-box-proposal-v1:{fingerprint[:24]}",
                "evidence": asdict(observation),
                "mirror": mirror.to_dict(),
                "evaluation": evaluation,
                "authority": "none-until-explicit-sandbox-approval",
                "real_money": False,
                "live_execution": False,
            }

    async def approve(self, proposal_id):
        with self._lock:
            await self._connect()
            request = self.queue.get(str(proposal_id))
            if request is None:
                raise ValueError("proposal not found")
            if request.status is not ApprovalStatus.PENDING:
                return {
                    "status": "blocked",
                    "reason": f"proposal status is {request.status.value}, not pending",
                    "real_money": False,
                    "live_execution": False,
                }
            if request.evaluation.get("evidence_authority") != "none" or not request.evaluation.get("evidence_read_only"):
                raise RuntimeError("Pump evidence authority boundary changed")
            market = await self.broker.get_market_data(request.order.symbol)
            current_price = float(market["price"])
            bound_price = float(request.evaluation["price"])
            if current_price != bound_price:
                return {
                    "status": "blocked",
                    "reason": "sandbox market price changed since proposal; bind current evidence into a new proposal",
                    "proposal_id": request.proposal_id,
                    "bound_price": bound_price,
                    "current_price": current_price,
                    "stale_evidence": True,
                    "authority": "none",
                    "real_money": False,
                    "live_execution": False,
                }
            if not self.queue.approve(request.proposal_id, "explicit Pump Live Box sandbox approval"):
                raise RuntimeError("approval could not be recorded")
            if not self.queue.approval_is_intact(request.proposal_id):
                raise RuntimeError("approval fingerprint mismatch")
            approved = self.queue.get(request.proposal_id)
            proposal_fingerprint = approval_fingerprint(request.order, request.evaluation)
            if not self.queue.begin_execution(request.proposal_id):
                raise RuntimeError("execution could not begin")
            execution = await self.broker.submit_order(request.order)
            if execution.get("status") == "rejected":
                self.queue.mark_execution_rejected(
                    request.proposal_id,
                    str(execution.get("reason") or "rejected"),
                )
                return {
                    "status": "blocked",
                    "execution": execution,
                    "real_money": False,
                    "live_execution": False,
                }
            order_id = execution.get("order_id")
            if not order_id or not self.queue.mark_executed(request.proposal_id, order_id):
                raise RuntimeError("execution receipt could not be persisted")
            wallet = await self.receipts.portfolio(self.broker)
            receipt = await self.receipts.record_execution(
                request=request,
                proposal_fingerprint=proposal_fingerprint,
                approval_fingerprint=(approved.approved_fingerprint if approved else None),
                execution=execution,
                wallet=wallet,
            )
            self.execution_receipts.append(receipt)
            return {
                "status": "executed",
                "proposal_id": request.proposal_id,
                "proposal_fingerprint": proposal_fingerprint,
                "approval_fingerprint": approved.approved_fingerprint if approved else None,
                "pump_observation_fingerprint": request.evaluation["pump_observation_fingerprint"],
                "execution": execution,
                "receipt": receipt,
                "wallet": wallet,
                "authority": "sandbox-simulation-only",
                "real_money": False,
                "live_execution": False,
            }


class Handler(BaseHTTPRequestHandler):
    @property
    def session(self):
        return self.server.session

    def json(self, payload, status=200):
        body = json.dumps(payload, default=str, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}"
        value = json.loads(raw.decode())
        if not isinstance(value, dict):
            raise TypeError("body must be a JSON object")
        return value

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        if path == "/health":
            return self.json(
                {
                    "status": "ok",
                    "pump_network_access": "none",
                    "evidence_authority": "none",
                    "practice_graduation": "review-only",
                    "real_money": False,
                    "live_execution": False,
                }
            )
        if path == "/api/wallet":
            return self.json(asyncio.run(self.session.wallet()))
        if path == "/api/graduation":
            return self.json(asyncio.run(self.session.graduation()))
        return self.json({"status": "not_found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self.body()
            if path == "/api/proposals":
                result = asyncio.run(
                    self.session.propose(
                        payload.get("evidence", {}),
                        payload.get("qty", 10),
                        payload.get("side", "buy"),
                    )
                )
                return self.json(
                    result,
                    HTTPStatus.CREATED if result["status"] == "pending" else HTTPStatus.OK,
                )
            if path.startswith("/api/proposals/") and path.endswith("/approve"):
                proposal_id = (
                    path.removeprefix("/api/proposals/")
                    .removesuffix("/approve")
                    .strip("/")
                )
                return self.json(asyncio.run(self.session.approve(proposal_id)))
        except (ValueError, TypeError, RuntimeError, PermissionError, json.JSONDecodeError) as exc:
            return self.json(
                {
                    "status": "invalid",
                    "reason": str(exc),
                    "real_money": False,
                    "live_execution": False,
                },
                400,
            )
        return self.json({"status": "not_found"}, 404)

    def log_message(self, fmt, *args):
        pass


def serve(host="127.0.0.1", port=8768):
    server = ThreadingHTTPServer((host, port), Handler)
    server.session = PumpLiveBoxSession(
        float(os.getenv("SLEEPWEALTH_CRYPTO_SANDBOX_CASH", "100")),
        audit_path=os.getenv(
            "SLEEPWEALTH_PUMP_AUDIT_LOG",
            "/tmp/sleepwealth-pump-live-box-audit.jsonl",
        ),
        minimum_practice_executions=int(
            os.getenv("SLEEPWEALTH_PUMP_MIN_PRACTICE_EXECUTIONS", "20")
        ),
        minimum_practice_round_trips=int(
            os.getenv("SLEEPWEALTH_PUMP_MIN_PRACTICE_ROUND_TRIPS", "3")
        ),
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
