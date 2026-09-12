import argparse
import asyncio
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from approvals.queue import ApprovalQueue
from audit.logger import AuditLogger
from broker.base import Order
from broker.factory import get_broker
from engine.evaluator import ProposalEvaluator
from engine.validator import RulesValidator
from execution.executor import ExecutionManager
from market.observation import observe_market
from portfolio.tracker import PortfolioTracker
from risk.gates import RiskGates
from rules import load_rules


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>Sleep Wealth · Paper Test</title>
<style>:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif}body{margin:0;background:#0d0b16;color:#f6f3ff;min-height:100vh;display:grid;place-items:center}main{width:min(860px,calc(100% - 32px));background:#171125;border:1px solid #3a2d58;border-radius:24px;padding:28px;box-sizing:border-box;box-shadow:0 24px 80px rgba(0,0,0,.35)}h1{margin:0 0 8px;font-size:clamp(2rem,6vw,3.8rem);letter-spacing:-.05em}.badge{display:inline-flex;gap:8px;align-items:center;border-radius:999px;padding:8px 12px;background:#231b36;color:#cdbdf5;font-size:.85rem}p{color:#bdb3cf;line-height:1.55}.markets{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:18px 0}.market{background:#100c1a;border:1px solid #35294d;border-radius:16px;padding:14px}.market strong{display:block;font-size:1.05rem}.market span{display:block;color:#a99eba;margin-top:5px;font-size:.82rem}form{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:22px}label{display:grid;gap:7px;color:#ddd5ea;font-size:.9rem}input,select,button{font:inherit;border-radius:14px;border:1px solid #44365f;background:#100c1a;color:white;padding:12px 14px}button{grid-column:1/-1;cursor:pointer;background:#7b5cff;border-color:#8c73ff;font-weight:700}button:disabled{opacity:.6;cursor:wait}pre{margin:18px 0 0;min-height:170px;white-space:pre-wrap;overflow-wrap:anywhere;background:#0b0912;border:1px solid #2e2442;border-radius:16px;padding:16px;color:#d8d0e7}.truth{margin-top:16px;font-size:.85rem;color:#9f93b4}@media(max-width:560px){main{padding:20px;border-radius:18px}.markets{grid-template-columns:1fr}form{grid-template-columns:1fr}button{grid-column:1}}</style></head>
<body><main><span class="badge">PAPER ONLY · READ-ONLY MARKET OBSERVATION · $0 REAL MONEY</span><h1>Sleep Wealth</h1><p>Watch the approved market universe, evaluate one proposal against observed data, then run only the governed mock execution path.</p><section id="markets" class="markets" aria-label="Approved market universe"><div class="market"><strong>Loading markets…</strong><span>read-only</span></div></section><form id="dry-run-form"><label>Symbol<input id="symbol" value="AAPL" maxlength="12" /></label><label>Quantity<input id="qty" value="0.04" inputmode="decimal" /></label><label>Side<select id="side"><option value="buy">Buy</option><option value="sell">Sell</option></select></label><label>Execution<input value="paper / mock" disabled /></label><button id="run-test" type="submit">Observe + run paper test</button></form><div class="truth">Market observation is read-only. The approved universe comes from rules.json. Live execution stays disabled.</div><pre id="result" aria-live="polite">Ready for a paper test.</pre></main>
<script>
const f=document.getElementById('dry-run-form'),b=document.getElementById('run-test'),r=document.getElementById('result'),m=document.getElementById('markets');
async function loadMarkets(){try{const x=await fetch('/api/markets');const data=await x.json();m.innerHTML=(data.markets||[]).map(o=>`<div class="market" data-symbol="${o.symbol}"><strong>${o.symbol} · $${Number(o.price).toFixed(2)}</strong><span>${o.source} · ${o.classification} · read-only</span></div>`).join('')||'<div class="market"><strong>No approved markets</strong><span>blocked</span></div>'}catch(error){m.innerHTML=`<div class="market"><strong>Market view unavailable</strong><span>${String(error)}</span></div>`}}
loadMarkets();
f.addEventListener('submit',async e=>{e.preventDefault();b.disabled=true;r.textContent='Observing market + running governed paper cycle…';try{const x=await fetch('/api/dry-run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({symbol:document.getElementById('symbol').value,qty:Number(document.getElementById('qty').value),side:document.getElementById('side').value})});r.textContent=JSON.stringify(await x.json(),null,2)}catch(error){r.textContent=JSON.stringify({status:'error',error:String(error)},null,2)}finally{b.disabled=false}})
</script></body></html>"""


def _serialize_account(account) -> dict:
    return {"cash": round(account.balance.cash, 2), "equity": round(account.balance.equity, 2), "positions": account.positions}


async def observe_approved_markets(market_provider=None) -> dict:
    """Observe only the symbol universe authorized by rules.json. No execution authority is created."""
    rules = load_rules()
    valid, errors = RulesValidator().validate(rules)
    if not valid:
        return {
            "status": "blocked",
            "stage": "rules",
            "reason": "; ".join(errors),
            "markets": [],
            "live_execution": False,
        }

    provider = market_provider
    source = "injected-read-only-provider"
    if provider is None:
        provider = get_broker("mock", paper_only=True)
        if not provider.is_paper_only():
            raise RuntimeError("market safety invariant failed: provider is not paper-only")
        if not await provider.connect():
            raise RuntimeError("mock market provider connection failed")
        source = "mock-market-observation"

    markets = []
    for symbol in rules.get("approved_symbols", []):
        observation = await observe_market(provider, symbol, source=source)
        markets.append(observation.to_dict())

    return {
        "status": "ok",
        "mode": "paper",
        "market_observation": "read-only",
        "approved_symbols": list(rules.get("approved_symbols", [])),
        "markets": markets,
        "live_execution": False,
        "truth": "watching markets does not grant execution authority",
    }


async def run_paper_dry_run(symbol="AAPL", qty=0.04, side="buy", audit_log_path=None, market_provider=None) -> dict:
    """Observe a quote, then execute one isolated paper cycle through the mock broker only."""
    symbol, side = str(symbol).strip().upper(), str(side).strip().lower()
    if not symbol:
        raise ValueError("symbol is required")
    if side not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")
    try:
        qty = float(qty)
    except (TypeError, ValueError) as exc:
        raise ValueError("qty must be a number") from exc
    if qty <= 0:
        raise ValueError("qty must be greater than zero")

    rules = load_rules()
    valid, errors = RulesValidator().validate(rules)
    if not valid:
        return {"status":"blocked","stage":"rules","reason":"; ".join(errors),"mode":"paper","broker":"mock","live_execution":False}

    broker = get_broker("mock", paper_only=True)
    if not broker.is_paper_only():
        raise RuntimeError("backend safety invariant failed: broker is not paper-only")
    if not await broker.connect():
        raise RuntimeError("mock broker connection failed")

    provider = market_provider or broker
    source = "injected-read-only-provider" if market_provider is not None else "mock-market-observation"
    observation = await observe_market(provider, symbol, source=source)

    portfolio = PortfolioTracker(broker, min_cash_floor=rules["floor_cash"])
    account_before = await portfolio.refresh()
    evaluator, queue = ProposalEvaluator(rules), ApprovalQueue()
    audit = AuditLogger(audit_log_path or os.getenv("SLEEPWEALTH_AUDIT_LOG", "audit.log"))
    gates = RiskGates(broker, portfolio, max_daily_loss=rules.get("max_daily_loss", 100.0))
    executor = ExecutionManager(broker, queue, audit, gates)
    order = Order(symbol=symbol, qty=qty, side=side)
    evaluation = evaluator.evaluate(order, account_before, price=observation.price)
    base = {"mode":"paper","broker":"mock","live_execution":False,"market_observation":observation.to_dict(),"approved_symbols":list(rules.get("approved_symbols", [])),"order":{"symbol":symbol,"qty":qty,"side":side},"evaluation":evaluation,"account_before":_serialize_account(account_before)}

    if not evaluation["allowed"]:
        await audit.log({"event":"proposal_rejected_by_evaluator","reason":evaluation["reason"],"order":base["order"],"market_observation":observation.to_dict()})
        return {**base,"status":"blocked","stage":"evaluator","reason":evaluation["reason"]}

    proposal_id = await executor.propose_order(order, evaluation)
    if not queue.approve(proposal_id, "explicit paper dry-run request"):
        return {**base,"status":"blocked","stage":"approval","proposal_id":proposal_id,"reason":"paper approval could not be recorded"}
    execution = await executor.execute_approved(proposal_id)
    account_after, events = await portfolio.refresh(), await audit.read(limit=5)
    if "error" in execution:
        return {**base,"status":"blocked","stage":"execution","proposal_id":proposal_id,"reason":execution["error"],"account_after":_serialize_account(account_after),"audit_events":[e.get("event") for e in events]}
    return {**base,"status":"executed","stage":"complete","proposal_id":proposal_id,"execution":execution,"account_after":_serialize_account(account_after),"audit_events":[e.get("event") for e in events],"truth":"read-only market observation; paper simulation only; no real money moved"}


class SleepWealthHandler(BaseHTTPRequestHandler):
    server_version = "SleepWealthPaper/0.3"

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, default=str, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=HTTPStatus.OK):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self._send_html(DASHBOARD_HTML)
        if path == "/health":
            return self._send_json({"status":"ok","mode":"paper","broker":"mock","market_observation":"read-only","live_execution":False})
        if path == "/api/markets":
            try:
                return self._send_json(asyncio.run(observe_approved_markets()))
            except (RuntimeError, ValueError) as exc:
                return self._send_json({"status":"error","reason":str(exc),"live_execution":False}, HTTPStatus.INTERNAL_SERVER_ERROR)
        self._send_json({"status":"not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if urlparse(self.path).path != "/api/dry-run":
            return self._send_json({"status":"not_found"}, HTTPStatus.NOT_FOUND)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode())
            if not isinstance(payload, dict):
                raise TypeError("request body must be a JSON object")
            result = asyncio.run(run_paper_dry_run(payload.get("symbol","AAPL"), payload.get("qty",0.04), payload.get("side","buy")))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return self._send_json({"status":"invalid","reason":str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            return self._send_json({"status":"error","reason":str(exc),"mode":"paper","broker":"mock","live_execution":False}, HTTPStatus.INTERNAL_SERVER_ERROR)
        self._send_json(result)

    def log_message(self, fmt, *args):
        print(f"[sleepwealth-backend] {self.address_string()} - {fmt % args}")


def serve(host="127.0.0.1", port=8765):
    Path(os.getenv("SLEEPWEALTH_AUDIT_LOG", "audit.log")).parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), SleepWealthHandler)
    print(f"Sleep Wealth paper backend listening on http://{host}:{port}")
    print("Market observation: approved universe / read-only | live execution: disabled | broker: mock")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="Sleep Wealth paper-only HTTP backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
