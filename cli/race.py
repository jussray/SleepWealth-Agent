"""Race CLI.

    python -m cli.race run --duration 1h
    python -m cli.race series --races 3 --duration 30m
    python -m cli.race gate --audit audit.log
    python -m cli.race modes
"""

import argparse
import asyncio

from audit.logger import AuditLogger
from gate.live_gate import LiveGate
from race.debrief import CuratorDebrief
from race.engines.gates import GatesEngine
from race.engines.musk import MuskEngine
from race.harness import DURATIONS, RaceHarness
from race.ledger import StakeLedger
from race.modes import Mode
from rules import load_rules


def build(rules: dict, audit_path: str):
    symbols = rules.get("approved_symbols", ["AAPL", "MSFT", "VTI"])
    engines = [MuskEngine(symbols), GatesEngine(symbols)]
    ledger = StakeLedger(base_stake=rules.get("floor_cash", 5.0))
    audit = AuditLogger(audit_path)
    return RaceHarness(engines, ledger, audit)


async def cmd_run(args):
    rules = load_rules()
    harness = build(rules, args.audit)
    result = await harness.run_race(duration=args.duration, seed=args.seed)
    patches = harness.cross_learn(result)
    debrief = CuratorDebrief(result, harness.transcripts[result.race_id], patches)
    print("\n" + debrief.render())


async def cmd_series(args):
    rules = load_rules()
    harness = build(rules, args.audit)
    for n in range(args.races):
        seed = None if args.seed is None else args.seed + n
        result = await harness.run_race(
            duration=args.duration,
            seed=seed,
            verbose=not args.quiet,
        )
        patches = harness.cross_learn(result, verbose=not args.quiet)
        if args.quiet:
            print(result.render())
        if n == args.races - 1:
            debrief = CuratorDebrief(result, harness.transcripts[result.race_id], patches)
            print("\n" + debrief.render())
    print("\n" + harness.ledger.render())


async def cmd_gate(args):
    rules = load_rules()
    gate = LiveGate(audit_path=args.audit)
    result = gate.evaluate(broker=None, rules=rules, config={})
    print(result.render())
    print(f"\naudit chain hash: {gate.chain_hash()[:32]}…")


def cmd_modes(_args):
    print("MODE STACK — every decision carries these tags\n")
    for mode in Mode:
        print(f"  {mode.value:<12} {mode.__doc__ or ''}")
    print("\n  /futureyou is enforced at construction: a Decision without a")
    print("  forward-look raises TypeError. No forward-look, no move.")


def main():
    parser = argparse.ArgumentParser(
        prog="race",
        description="SleepWealth local simulation race harness",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_parser = sub.add_parser("run", help="run one simulated race")
    run_parser.add_argument("--duration", default="1h", choices=sorted(DURATIONS))
    run_parser.add_argument("--seed", type=int, default=None)
    run_parser.add_argument("--audit", default="audit.log")
    run_parser.set_defaults(fn=cmd_run, is_async=True)

    series = sub.add_parser("series", help="run several simulated races with cross-learning")
    series.add_argument("--races", type=int, default=3)
    series.add_argument("--duration", default="30m", choices=sorted(DURATIONS))
    series.add_argument("--seed", type=int, default=None)
    series.add_argument("--audit", default="audit.log")
    series.add_argument("--quiet", action="store_true")
    series.set_defaults(fn=cmd_series, is_async=True)

    gate_parser = sub.add_parser("gate", help="evaluate the simulation governance gate")
    gate_parser.add_argument("--audit", default="audit.log")
    gate_parser.set_defaults(fn=cmd_gate, is_async=True)

    modes = sub.add_parser("modes", help="show the mode stack")
    modes.set_defaults(fn=cmd_modes, is_async=False)

    args = parser.parse_args()
    if getattr(args, "is_async", False):
        asyncio.run(args.fn(args))
    else:
        args.fn(args)


if __name__ == "__main__":
    main()
