import asyncio
import json

import typer

from approvals.queue import ApprovalQueue
from audit.logger import AuditLogger
from broker.base import Order
from broker.factory import get_broker
from engine.capital_ladder import CapitalLadder, FlipCycle
from engine.evaluator import ProposalEvaluator
from engine.validator import RulesValidator
from execution.executor import ExecutionManager
from market.observation import observe_market
from portfolio.tracker import PortfolioTracker
from risk.gates import RiskGates
from rules import load_rules

app = typer.Typer(help="Governed paper-trading simulator. Live execution is disabled.")


async def _run(mode, broker, symbol, qty, side, auto_approve):
    if mode != "paper":
        typer.echo("[BLOCKED] SleepWealth is paper/simulation-only; live execution is disabled.")
        raise typer.Exit(1)
    paper_only = True

    rules = load_rules()
    ok, errors = RulesValidator().validate(rules)
    if not ok:
        typer.echo("[RULES] invalid:")
        for err in errors:
            typer.echo(f"  - {err}")
        raise typer.Exit(1)
    typer.echo(
        f"[RULES] v{rules['version']} valid | floor=${rules['floor_cash']} "
        f"ceiling=${rules['ceiling']['current']}"
    )

    try:
        broker_instance = get_broker(broker, paper_only=paper_only)
    except ValueError as exc:
        typer.echo(f"[ERROR] {exc}")
        raise typer.Exit(1)

    if not await broker_instance.connect():
        typer.echo("[ERROR] broker connection failed")
        raise typer.Exit(1)

    portfolio = PortfolioTracker(broker_instance, min_cash_floor=rules["floor_cash"])
    account = await portfolio.refresh()
    typer.echo(f"[ACCOUNT] cash=${account.balance.cash:.2f} equity=${account.balance.equity:.2f}")

    observation = await observe_market(
        broker_instance,
        symbol,
        source=f"{broker}-market-observation",
    )
    typer.echo(
        f"[MARKET] {observation.symbol} observed=${observation.price:.2f} "
        f"source={observation.source} read_only={observation.read_only}"
    )

    evaluator = ProposalEvaluator(rules)
    queue = ApprovalQueue()
    audit = AuditLogger()
    gates = RiskGates(
        broker_instance,
        portfolio,
        max_daily_loss=rules.get("max_daily_loss", 100.0),
    )
    executor = ExecutionManager(broker_instance, queue, audit, gates)

    order = Order(symbol=symbol, qty=qty, side=side)
    evaluation = evaluator.evaluate(order, account, price=observation.price)
    typer.echo(
        f"[EVAL] allowed={evaluation['allowed']} "
        f"risk={evaluation['risk_score']}% | {evaluation['reason']}"
    )

    if not evaluation["allowed"]:
        await audit.log(
            {
                "event": "proposal_rejected_by_evaluator",
                "reason": evaluation["reason"],
                "market_observation": observation.to_dict(),
            }
        )
        typer.echo("[REJECTED] evaluator blocked this order")
        raise typer.Exit(1)

    proposal_id = await executor.propose_order(order, evaluation)
    typer.echo(f"[PROPOSAL] {proposal_id} pending approval")

    if not auto_approve:
        typer.echo("[HOLD] run with --auto-approve, or approve manually in your own loop")
        return

    queue.approve(proposal_id, "auto-approved (paper demo)")
    result = await executor.execute_approved(proposal_id)

    if "error" in result:
        typer.echo(f"[BLOCKED] {result['error']}")
        raise typer.Exit(1)

    typer.echo(f"[EXECUTED] order_id={result['order_id']} status={result['status']}")

    events = await audit.read(limit=5)
    typer.echo(f"\n[AUDIT] last {len(events)} events:")
    for ev in events:
        typer.echo(f"  {ev['event']} :: {ev.get('reason') or ev.get('order_id') or ''}")


@app.command()
def run(
    mode: str = typer.Option("paper", help="paper only; live execution is disabled"),
    broker: str = typer.Option("mock", help="mock | alpaca"),
    symbol: str = typer.Option("AAPL"),
    qty: float = typer.Option(1),
    side: str = typer.Option("buy", help="buy | sell"),
    auto_approve: bool = typer.Option(
        False,
        "--auto-approve",
        help="skip human approval (paper only)",
    ),
):
    """Run one full OODA cycle: observe -> evaluate -> propose -> approve -> execute -> audit."""
    if mode != "paper":
        typer.echo("[BLOCKED] SleepWealth is paper/simulation-only; live execution is disabled.")
        raise typer.Exit(1)
    asyncio.run(_run(mode, broker, symbol, qty, side, auto_approve))


@app.command()
def status(broker: str = typer.Option("mock")):
    """Show account cash and equity."""

    async def _status():
        b = get_broker(broker, paper_only=True)
        if not await b.connect():
            typer.echo("connection failed")
            raise typer.Exit(1)
        acct = await b.get_account_summary()
        typer.echo(f"cash:   ${acct.get('cash', 0):.2f}")
        typer.echo(f"equity: ${acct.get('equity', 0):.2f}")

    asyncio.run(_status())


@app.command()
def ladder(
    buy_cost: float = typer.Option(..., min=0.0, help="simulated acquisition cost"),
    sale_proceeds: float = typer.Option(..., min=0.0, help="simulated sale proceeds"),
    fees: float = typer.Option(0.0, min=0.0, help="fees paid for the simulated cycle"),
    other_costs: float = typer.Option(
        0.0,
        min=0.0,
        help="shipping or other simulated cycle costs",
    ),
    days_held: int = typer.Option(0, min=0, help="days capital was tied up"),
    prior_qualified_wins: int = typer.Option(
        0,
        min=0,
        help="already verified consecutive qualifying paper cycles",
    ),
):
    """Score one paper flip and report whether the capital ladder earned a review."""
    rules = load_rules()
    ok, errors = RulesValidator().validate(rules)
    if not ok:
        for err in errors:
            typer.echo(f"  - {err}")
        raise typer.Exit(1)

    policy = CapitalLadder(rules)
    result = policy.assess(
        FlipCycle(
            buy_cost=buy_cost,
            sale_proceeds=sale_proceeds,
            fees=fees,
            other_costs=other_costs,
            days_held=days_held,
        ),
        prior_qualified_wins=prior_qualified_wins,
    )
    typer.echo(json.dumps(result, indent=2, sort_keys=True))


@app.command()
def validate():
    """Validate rules.json against the schema contract."""
    ok, errors = RulesValidator().validate(load_rules())
    if ok:
        typer.echo("rules.json OK")
    else:
        for err in errors:
            typer.echo(f"  - {err}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
