import asyncio
import json

import typer

from backend.server import run_paper_dry_run
from broker.factory import get_broker
from engine.capital_ladder import CapitalLadder, FlipCycle
from engine.validator import RulesValidator
from market import CRYPTO_LANE, STOCK_LANE, normalize_lane
from rules import load_rules

app = typer.Typer(help="Governed paper-trading simulator. Live execution is disabled.")


async def _run(mode, broker, lane, symbol, qty, side, auto_approve):
    if mode != "paper":
        typer.echo("[BLOCKED] Sleep Wealth is paper/simulation-only; live execution is disabled.")
        raise typer.Exit(1)
    if broker != "mock":
        typer.echo("[BLOCKED] CLI execution is hard-bound to the mock broker.")
        raise typer.Exit(1)

    lane = normalize_lane(lane)
    rules = load_rules()
    ok, errors = RulesValidator().validate(rules)
    if not ok:
        typer.echo("[RULES] invalid:")
        for err in errors:
            typer.echo(f"  - {err}")
        raise typer.Exit(1)

    if not auto_approve:
        typer.echo("[HOLD] use --auto-approve only for this paper-only simulator cycle")
        return

    if not symbol:
        symbol = "BTC-USD" if lane == CRYPTO_LANE else "AAPL"

    typer.echo(
        f"[LANE] {lane} | paper_only=true | broker=mock | "
        f"live_execution=false"
    )
    result = await run_paper_dry_run(
        symbol=symbol,
        qty=qty,
        side=side,
        lane=lane,
    )
    typer.echo(
        f"[MARKET] {result['market_observation']['symbol']} "
        f"observed=${result['market_observation']['price']:.2f} "
        f"lane={result['market_observation']['lane']} "
        f"source={result['market_observation']['source']}"
    )
    typer.echo(
        f"[EVAL] allowed={result['evaluation']['allowed']} "
        f"risk={result['evaluation']['risk_score']}% | "
        f"{result['evaluation']['reason']}"
    )

    if result["status"] != "executed":
        typer.echo(f"[BLOCKED] {result.get('reason', result['status'])}")
        raise typer.Exit(1)

    execution = result["execution"]
    typer.echo(
        f"[EXECUTED] order_id={execution['order_id']} "
        f"status={execution['status']} classification={execution['fill_classification']}"
    )
    typer.echo(
        f"[CONTINUITY] lane_cookie={result['continuity']['lane_cookie']} "
        f"outcome_cookie={result['continuity']['outcome_cookie']}"
    )
    typer.echo("[TRUTH] paper simulation only; no real money moved")


@app.command()
def run(
    mode: str = typer.Option("paper", help="paper only; live execution is disabled"),
    broker: str = typer.Option("mock", help="mock only"),
    lane: str = typer.Option(STOCK_LANE, help="stock-market | crypto"),
    symbol: str = typer.Option("", help="defaults to AAPL for stocks or BTC-USD for crypto"),
    qty: float = typer.Option(0.01),
    side: str = typer.Option("buy", help="buy | sell"),
    auto_approve: bool = typer.Option(
        False,
        "--auto-approve",
        help="record explicit approval for one paper-only simulator cycle",
    ),
):
    """Run one paper OODA cycle inside exactly one market lane."""
    asyncio.run(_run(mode, broker, lane, symbol, qty, side, auto_approve))


@app.command()
def status(broker: str = typer.Option("mock", help="mock only")):
    """Show the isolated mock account used for paper simulation."""

    async def _status():
        if broker != "mock":
            typer.echo("[BLOCKED] status is hard-bound to the mock broker")
            raise typer.Exit(1)
        instance = get_broker("mock", paper_only=True)
        if not await instance.connect():
            typer.echo("connection failed")
            raise typer.Exit(1)
        account = await instance.get_account_summary()
        typer.echo(f"cash:   ${account.get('cash', 0):.2f}")
        typer.echo(f"equity: ${account.get('equity', 0):.2f}")
        typer.echo("live_execution: false")

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
