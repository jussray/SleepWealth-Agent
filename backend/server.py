import argparse
import asyncio
import hashlib
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
from market.providers import YahooPublicChartProvider
from portfolio.tracker import PortfolioTracker
from risk.gates import RiskGates
from rules import load_rules


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>Sleep Wealth · Paper Lab</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;--ink:#071426;--panel:rgba(9,22,49,.84);--line:rgba(255,255,255,.13);--violet:#856dff;--blue:#40c9ff;--sun:#ffd166;--coral:#ff7a59;--mint:#75efc0;--text:#f8fbff;--muted:#a9b9d2}
*{box-sizing:border-box}body{margin:0;min-height:100vh;color:var(--text);background:radial-gradient(circle at 18% 12%,rgba(133,109,255,.36),transparent 28%),radial-gradient(circle at 88% 18%,rgba(255,209,102,.22),transparent 26%),radial-gradient(circle at 76% 84%,rgba(64,201,255,.2),transparent 30%),linear-gradient(145deg,#06111f 0%,#0a1730 55%,#101633 100%);display:grid;place-items:center;padding:24px}
main{position:relative;overflow:hidden;width:min(940px,100%);background:var(--panel);border:1px solid var(--line);border-radius:30px;padding:30px;box-shadow:0 30px 100px rgba(1,7,18,.48);backdrop-filter:blur(20px)}
.orbit{position:absolute;right:-44px;top:-54px;width:190px;height:190px;border:1px solid rgba(255,255,255,.12);border-radius:50%;pointer-events:none}.orbit:after{content:"";position:absolute;left:26px;bottom:28px;width:18px;height:18px;border-radius:50%;background:var(--sun);box-shadow:0 0 34px rgba(255,209,102,.8)}.moon{position:absolute;left:58px;top:46px;font-size:4.6rem;color:#efeaff;filter:drop-shadow(0 0 22px rgba(133,109,255,.55))}
.topline{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.eyebrow,.badge,.chip{display:inline-flex;align-items:center;border-radius:999px}.eyebrow{padding:7px 10px;background:rgba(117,239,192,.12);color:var(--mint);font-size:.75rem;font-weight:800;letter-spacing:.08em}.badge{padding:8px 12px;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.09);color:#dce8ff;font-size:.78rem}
h1{margin:16px 0 6px;font-size:clamp(2.7rem,8vw,5.1rem);line-height:.9;letter-spacing:-.06em;background:linear-gradient(100deg,#fff 10%,#d7ccff 36%,#70d9ff 66%,#ffe29a 94%);-webkit-background-clip:text;background-clip:text;color:transparent}p{max-width:700px;color:var(--muted);line-height:1.55;margin:0}.steps{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 6px}.steps span{padding:7px 10px;border-radius:999px;background:rgba(255,255,255,.06);color:#d7e2f7;font-size:.78rem}.steps b{color:var(--sun)}
.markets{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:20px 0}.market{position:relative;min-height:132px;background:linear-gradient(155deg,rgba(255,255,255,.09),rgba(255,255,255,.035));border:1px solid var(--line);border-radius:20px;padding:17px;overflow:hidden}.market:before{content:"";position:absolute;inset:0 0 auto;height:4px;background:linear-gradient(90deg,var(--violet),var(--blue),var(--sun))}.market:nth-child(2):before{background:linear-gradient(90deg,var(--blue),var(--mint))}.market:nth-child(3):before{background:linear-gradient(90deg,var(--sun),var(--coral))}.market strong{display:block;font-size:1.25rem;letter-spacing:-.02em}.market .price{font-size:1.8rem;font-weight:800;margin-top:12px}.market small{display:block;color:var(--muted);margin-top:8px;line-height:1.35}.chip{padding:5px 8px;background:rgba(117,239,192,.12);color:var(--mint);font-size:.68rem;font-weight:800;letter-spacing:.05em;margin-top:9px}
form{display:grid;grid-template-columns:1.1fr .9fr .9fr 1.1fr;gap:12px;margin-top:20px;padding-top:20px;border-top:1px solid rgba(255,255,255,.08)}label{display:grid;gap:7px;color:#dbe6f8;font-size:.84rem}input,select,button{font:inherit;border-radius:15px;border:1px solid rgba(255,255,255,.14);background:rgba(2,10,24,.56);color:white;padding:12px 14px;outline:none}input:focus,select:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(64,201,255,.12)}button{cursor:pointer;background:linear-gradient(105deg,var(--violet),#6b8cff 50%,var(--blue));border:0;font-weight:850;color:white;box-shadow:0 12px 35px rgba(80,110,255,.28)}button:hover{transform:translateY(-1px)}button:disabled{opacity:.6;cursor:wait;transform:none}
.truth{margin-top:16px;padding:12px 14px;border-radius:14px;background:rgba(255,209,102,.08);border:1px solid rgba(255,209,102,.14);font-size:.82rem;color:#f6deb0}.truth b{color:var(--sun)}pre{margin:16px 0 0;min-height:160px;max-height:360px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:rgba(1,7,18,.72);border:1px solid rgba(255,255,255,.1);border-radius:18px;padding:16px;color:#dce8ff;font-size:.78rem}
@media(max-width:760px){main{padding:23px;border-radius:24px}.markets{grid-template-columns:1fr}.market{min-height:auto}form{grid-template-columns:1fr 1fr}.orbit{opacity:.55}}
@media(max-width:520px){body{padding:12px}main{padding:20px;border-radius:20px}form{grid-template-columns:1fr}.badge{font-size:.7rem}h1{font-size:3.5rem}.orbit{right:-88px}}
</style></head>
<body><main><div class="orbit" aria-hidden="true"><span class="moon">☾</span></div><div class="topline"><span class="eyebrow">🌙 PAPER LAB</span><span class="badge">REAL DATA WATCH · PAPER EXECUTION · $0 REAL MONEY</span></div><h1>Sleep Wealth</h1><p>Watch what moved. Test what could happen. Keep real money asleep while the paper system learns to tell the truth.</p><div class="steps"><span><b>1</b> Observe</span><span><b>2</b> Evaluate</span><span><b>3</b> Simulate</span><span><b>4</b> Receipt</span></div><section id="markets" class="markets" aria-label="Approved market universe"><div class="market"><strong>Loading markets…</strong><small>read-only observation</small></div></section><form id="dry-run-form"><label>Symbol<input id="symbol" value="AAPL" maxlength="12" /></label><label>Quantity<input id="qty" value="0.01" inputmode="decimal" /></label><label>Side<select id="side"><option value="buy">Buy</option><option value="sell">Sell</option></select></label><label>Execution<input value="paper / mock" disabled /></label><button id="run-test" type="submit">Observe + run paper test</button></form><div class="truth"><b>Truth lock:</b> observations, fingerprints, and cookies are state markers only. They never grant execution authority. Live execution stays disabled.</div><pre id="result" aria-live="polite">Ready for a paper test.</pre></main>
<script>
const f=document.getElementById('dry-run-form'),b=document.getElementById('run-test'),r=document.getElementById('result'),m=document.getElementById('markets');
function marketCard(o){if(o.classification==='BLOCKED')return `<div class="market" data-symbol="${o.symbol}"><strong>${o.symbol}</strong><div class="price">blocked</div><small>${o.reason||'observation unavailable'}</small></div>`;const fp=(o.fingerprint||'').slice(0,10);const label=o.source_classification==='synthetic-fixture'?'SIMULATED FEED':'REAL READ-ONLY DATA';return `<div class="market" data-symbol="${o.symbol}"><strong>${o.symbol}</strong><div class="price">$${Number(o.price).toFixed(2)}</div><small>${o.source} · ${o.freshness} · ${o.age_seconds}s old</small><span class="chip">${label} · fp ${fp}</span></div>`}
async function loadMarkets(){try{const x=await fetch('/api/markets');const data=await x.json();m.innerHTML=(data.markets||[]).map(marketCard).join('')||'<div class="market"><strong>No approved markets</strong><small>blocked</small></div>'}catch(error){m.innerHTML=`<div class="market"><strong>Market view unavailable</strong><small>${String(error)}</small></div>`}}
loadMarkets();
f.addEventListener('submit',async e=>{e.preventDefault();b.disabled=true;r.textContent='Observing market + running governed paper cycle…';try{const x=await fetch('/api/dry-run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({symbol:document.getElementById('symbol').value,qty:Number(document.getElementById('qty').value),side:document.getElementById('side').value})});r.textContent=JSON.stringify(await x.json(),null,2);await loadMarkets()}catch(error){r.textContent=JSON.stringify({status:'error',error:String(error)},null,2)}finally{b.disabled=false}})
</script></body></html>"""


def _serialize_account(account) -> dict:
    return {"cash": round(account.balance.cash, 2), "equity": round(account.balance.equity, 2), "positions": account.positions}


def _marker(kind: str, payload: dict) -> dict:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()
    return {"fingerprint": fingerprint, "cookie": f"sw-{kind}-v1:{fingerprint[:32]}"}


def _continuity_receipt(observation, order: dict, evaluation: dict, execution: dict | None = None) -> dict:
    decision = _marker(
        "decision",
        {
            "market_fingerprint": observation.fingerprint,
            "order": order,
            "evaluation": evaluation,
        },
    )
    receipt = {
        "input_market_fingerprint": observation.fingerprint,
        "input_market_cookie": observation.continuity_cookie,
        "decision_fingerprint": decision["fingerprint"],
        "decision_cookie": decision["cookie"],
        "authority": "none",
        "truth": "fingerprints and cookies are non-secret state markers only; they never grant execution authority",
    }
    if execution is not None:
        outcome = _marker(
            "outcome",
            {
                "decision_fingerprint": decision["fingerprint"],
                "execution": execution,
            },
        )
        receipt["outcome_fingerprint"] = outcome["fingerprint"]
        receipt["outcome_cookie"] = outcome["cookie"]
    return receipt


async def _default_market_provider():
    source = os.getenv("SLEEPWEALTH_MARKET_SOURCE", "yahoo-public").strip().lower()
    if source in {"yahoo", "yahoo-public", "public"}:
        return YahooPublicChartProvider()
    if source in {"mock", "fixture", "synthetic"}:
        provider = get_broker("mock", paper_only=True)
        if not provider.is_paper_only():
            raise RuntimeError("market safety invariant failed: mock provider is not paper-only")
        if not await provider.connect():
            raise RuntimeError("mock market provider connection failed")
        return provider
    raise ValueError(f"unsupported read-only market source: {source}")


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

    provider = market_provider or await _default_market_provider()
    markets, failures = [], []
    for symbol in rules.get("approved_symbols", []):
        try:
            observation = await observe_market(provider, symbol)
            markets.append(observation.to_dict())
        except (RuntimeError, ValueError) as exc:
            failures.append(symbol)
            markets.append({"symbol": symbol, "classification": "BLOCKED", "read_only": True, "authority": "none", "reason": str(exc)})

    return {
        "status": "ok" if not failures else "partial",
        "mode": "paper",
        "market_observation": "read-only",
        "market_source": getattr(provider, "source_name", provider.__class__.__name__),
        "approved_symbols": list(rules.get("approved_symbols", [])),
        "markets": markets,
        "failed_symbols": failures,
        "live_execution": False,
        "truth": "watching markets and continuity markers do not grant execution authority",
    }


async def run_paper_dry_run(symbol="AAPL", qty=0.01, side="buy", audit_log_path=None, market_provider=None) -> dict:
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

    provider = market_provider or await _default_market_provider()
    observation = await observe_market(provider, symbol)
    if hasattr(broker, "set_market_price"):
        broker.set_market_price(symbol, observation.price)

    portfolio = PortfolioTracker(broker, min_cash_floor=rules["floor_cash"])
    account_before = await portfolio.refresh()
    evaluator, queue = ProposalEvaluator(rules), ApprovalQueue()
    audit = AuditLogger(audit_log_path or os.getenv("SLEEPWEALTH_AUDIT_LOG", "audit.log"))
    gates = RiskGates(broker, portfolio, max_daily_loss=rules.get("max_daily_loss", 100.0))
    executor = ExecutionManager(broker, queue, audit, gates)
    order = Order(symbol=symbol, qty=qty, side=side)
    evaluation = evaluator.evaluate(order, account_before, price=observation.price)
    order_receipt = {"symbol":symbol,"qty":qty,"side":side}
    continuity = _continuity_receipt(observation, order_receipt, evaluation)
    base = {"mode":"paper","broker":"mock","live_execution":False,"market_observation":observation.to_dict(),"approved_symbols":list(rules.get("approved_symbols", [])),"order":order_receipt,"evaluation":evaluation,"account_before":_serialize_account(account_before),"continuity":continuity}

    if not evaluation["allowed"]:
        await audit.log({"event":"proposal_rejected_by_evaluator","reason":evaluation["reason"],"order":base["order"],"market_observation":observation.to_dict(),"continuity":continuity})
        return {**base,"status":"blocked","stage":"evaluator","reason":evaluation["reason"]}

    proposal_id = await executor.propose_order(order, evaluation)
    if not queue.approve(proposal_id, "explicit paper dry-run request"):
        return {**base,"status":"blocked","stage":"approval","proposal_id":proposal_id,"reason":"paper approval could not be recorded"}
    execution = await executor.execute_approved(proposal_id)
    account_after, events = await portfolio.refresh(), await audit.read(limit=5)
    continuity = _continuity_receipt(observation, order_receipt, evaluation, execution)
    if "error" in execution:
        return {**base,"continuity":continuity,"status":"blocked","stage":"execution","proposal_id":proposal_id,"reason":execution["error"],"account_after":_serialize_account(account_after),"audit_events":[e.get("event") for e in events]}
    return {**base,"continuity":continuity,"status":"executed","stage":"complete","proposal_id":proposal_id,"execution":execution,"account_after":_serialize_account(account_after),"audit_events":[e.get("event") for e in events],"truth":"read-only market observation; paper simulation only; no real money moved"}


class SleepWealthHandler(BaseHTTPRequestHandler):
    server_version = "SleepWealthPaper/0.4"

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
            return self._send_json({"status":"ok","mode":"paper","broker":"mock","market_source":os.getenv("SLEEPWEALTH_MARKET_SOURCE","yahoo-public"),"market_observation":"read-only","live_execution":False})
        if path == "/api/markets":
            try:
                return self._send_json(asyncio.run(observe_approved_markets()))
            except (RuntimeError, ValueError) as exc:
                return self._send_json({"status":"error","reason":str(exc),"live_execution":False}, HTTPStatus.BAD_GATEWAY)
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
            result = asyncio.run(run_paper_dry_run(payload.get("symbol","AAPL"), payload.get("qty",0.01), payload.get("side","buy")))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            return self._send_json({"status":"invalid","reason":str(exc)}, HTTPStatus.BAD_REQUEST)
        except ValueError as exc:
            return self._send_json({"status":"blocked","reason":str(exc),"mode":"paper","broker":"mock","live_execution":False}, HTTPStatus.BAD_GATEWAY)
        except RuntimeError as exc:
            return self._send_json({"status":"error","reason":str(exc),"mode":"paper","broker":"mock","live_execution":False}, HTTPStatus.BAD_GATEWAY)
        self._send_json(result)

    def log_message(self, fmt, *args):
        print(f"[sleepwealth-backend] {self.address_string()} - {fmt % args}")


def serve(host="127.0.0.1", port=8765):
    Path(os.getenv("SLEEPWEALTH_AUDIT_LOG", "audit.log")).parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), SleepWealthHandler)
    print(f"Sleep Wealth paper backend listening on http://{host}:{port}")
    print(f"Market observation: {os.getenv('SLEEPWEALTH_MARKET_SOURCE','yahoo-public')} / read-only | live execution: disabled | broker: mock")
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
