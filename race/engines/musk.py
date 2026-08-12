"""MuskEngine.

Style: first principles, concentrate, move before the evidence is complete,
fail loudly, mutate. Rides conviction through noise but cuts hard at the line.

Governed, not ungoverned: same Redteam contract as Gates, threshold 75 instead
of 30. It is allowed to be wrong faster, not allowed to be reckless.
"""

from typing import List

from race.engines.base import EngineState, MarketSnapshot, RaceEngine
from race.modes import Decision, FutureYou, Mode, ModeNote

DEFAULT_RISK_THRESHOLD = 75.0
DEFAULT_MAX_DRAWDOWN = 25.0


class MuskEngine(RaceEngine):
    def __init__(self, approved_symbols: List[str],
                 risk_threshold: float = DEFAULT_RISK_THRESHOLD,
                 max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN):
        super().__init__("Musk", risk_threshold, max_drawdown_pct, approved_symbols)
        self.conviction_size = 0.90   # % of stake committed on entry
        self.cut_line = -6.0          # % unrealized loss that forces an exit
        self.stolen_patterns: List[str] = []

    # ---- decision ----------------------------------------------------

    def decide(self, snapshot: MarketSnapshot, state: EngineState) -> Decision:
        modes: List[ModeNote] = []

        # OODA: observe
        candidates = [
            (sym, snapshot.ticks[sym])
            for sym in self.approved_symbols
            if sym in snapshot.ticks
        ]
        if not candidates:
            return self.record(self.hold(
                "no market data on approved symbols",
                FutureYou(
                    enables="nothing; a blind race is a coin flip",
                    breaks="the whole premise if the feed stays dark",
                    durable=False,
                ),
                [ModeNote(Mode.OODA, "observe stage returned empty; cannot orient")],
            ))

        # Exit check first — fail fast is the whole style
        for sym, qty in list(state.positions.items()):
            if qty <= 0:
                continue
            pnl = state.unrealized_pct(sym, snapshot)
            if pnl <= self.cut_line:
                modes.append(ModeNote(
                    Mode.CONFESS,
                    f"{sym} is {pnl:.1f}% against me. The thesis was wrong. "
                    "Taking the loss now rather than defending it.",
                ))
                modes.append(ModeNote(
                    Mode.OODA,
                    "re-orient: exit, free the stake, look for the next asymmetry",
                ))
                return self.record(Decision(
                    engine=self.name,
                    action="sell",
                    symbol=sym,
                    qty=qty,
                    confidence=85.0,
                    risk_score=10.0,
                    reasoning=f"cut {sym} at {pnl:.1f}%, below cut line {self.cut_line}%",
                    futureyou=FutureYou(
                        enables="a habit of killing losers early, which is what "
                                "keeps a $5 stake alive long enough to compound",
                        breaks="upside if this was noise and it snaps back",
                        durable=True,
                    ),
                    modes=modes,
                ))

        # ULTRATHINK: score every path, not just the obvious one
        scored = []
        for sym, tick in candidates:
            vol = snapshot.volatility(sym)
            trend = snapshot.trend(sym)
            momentum = tick.change_pct
            # Musk weights recent momentum and volatility. Movement is opportunity.
            score = (momentum * 3.0) + (trend * 1.5) + (vol * 1.0)
            scored.append((score, sym, tick, vol, trend, momentum))
        scored.sort(reverse=True, key=lambda r: r[0])

        modes.append(ModeNote(
            Mode.ULTRATHINK,
            f"explored {len(scored)} paths: "
            + ", ".join(f"{s[1]} {s[0]:+.1f}" for s in scored[:4])
            + ". Unknown: whether this window is signal or chop.",
        ))

        best_score, sym, tick, vol, trend, momentum = scored[0]

        if state.positions.get(sym, 0) > 0:
            pnl = state.unrealized_pct(sym, snapshot)
            modes.append(ModeNote(
                Mode.OODA,
                f"already in {sym} at {pnl:+.1f}%; act stage is 'let it run'",
            ))
            return self.record(self.hold(
                f"riding {sym}, thesis intact ({pnl:+.1f}%)",
                FutureYou(
                    enables="conviction holds that let winners actually pay for losers",
                    breaks="capital flexibility; stake is committed while it rides",
                    durable=True,
                ),
                modes,
            ))

        if best_score <= 0:
            modes.append(ModeNote(
                Mode.TRUTHMODE,
                "no candidate has positive momentum. Forcing a trade here would be "
                "activity disguised as edge.",
            ))
            return self.record(self.hold(
                "nothing moving; refusing to manufacture a setup",
                FutureYou(
                    enables="discipline about not trading chop, which Gates already has",
                    breaks="the aggressive identity if it becomes the default",
                    durable=True,
                ),
                modes,
            ))

        if state.cash < 0.25:
            return self.record(self.hold(
                f"stake spent (${state.cash:.2f} left)",
                FutureYou(
                    enables="nothing further this race",
                    breaks="ability to react if a better setup appears",
                    durable=False,
                ),
                modes,
            ))

        if self.stolen_patterns:
            modes.append(ModeNote(
                Mode.STEAL,
                "applying from opponent: " + "; ".join(self.stolen_patterns[-2:]),
            ))

        commit = state.cash * self.conviction_size
        qty = commit / tick.price
        risk = min(100.0, (vol * 6.0) + (self.conviction_size * 40.0))

        modes.append(ModeNote(
            Mode.OODA,
            f"decide: {sym} momentum {momentum:+.2f}%, vol {vol:.2f}%. "
            f"Act now, verify later.",
        ))
        modes.append(ModeNote(
            Mode.REDTEAM,
            f"self-attack: concentration is {self.conviction_size:.0%} of stake in one "
            f"name. If {sym} gaps against me the race is effectively over. "
            f"Accepted at risk {risk:.0f} (threshold {self.risk_threshold:.0f}).",
        ))

        return self.record(Decision(
            engine=self.name,
            action="buy",
            symbol=sym,
            qty=qty,
            confidence=min(95.0, 55.0 + abs(momentum) * 8),
            risk_score=risk,
            reasoning=(
                f"concentrate {self.conviction_size:.0%} of stake into {sym}: "
                f"strongest path of {len(scored)} at score {best_score:+.1f}"
            ),
            futureyou=FutureYou(
                enables=(
                    "an engine that can actually move the needle on $5 — small "
                    "stakes need concentration or nothing compounds"
                ),
                breaks=(
                    "survivability if concentration becomes automatic; three races "
                    "of this into a bad tape and the stake never recovers"
                ),
                durable=risk <= self.risk_threshold,
            ),
            modes=modes,
        ))

    # ---- learning ----------------------------------------------------

    def learn_from_moves(self, opponent_decisions: List[Decision]) -> List[str]:
        """Read Gates' moves. Outcomes are noise; process is signal."""
        patches: List[str] = []

        executed = [d for d in opponent_decisions if d.executed]
        vetoed = [d for d in opponent_decisions if d.vetoed_by]
        holds = [d for d in opponent_decisions if d.action == "hold"]

        if holds and len(holds) / max(len(opponent_decisions), 1) > 0.5:
            patches.append(
                "Gates held more than half its turns. Patience is a move I keep "
                "treating as an absence of one. Raising my bar for entry."
            )
            self.cut_line = max(self.cut_line, -5.0)

        if vetoed:
            reasons = {d.veto_reason for d in vetoed if d.veto_reason}
            patches.append(
                f"Gates' own Redteam stopped it {len(vetoed)}x: "
                f"{'; '.join(list(reasons)[:2])}. Those are failure modes I run into "
                "at speed rather than getting stopped before."
            )

        if executed:
            avg_size = sum(d.qty for d in executed) / len(executed)
            patches.append(
                f"Gates sized at {avg_size:.4f} avg — smaller and repeatable. "
                "Testing a lower conviction size so one bad entry can't end a race."
            )
            self.conviction_size = max(0.60, self.conviction_size - 0.10)

        non_durable = [d for d in opponent_decisions if not d.futureyou.durable]
        if not non_durable:
            patches.append(
                "/futureyou: every Gates move was marked durable. Mine weren't. "
                "That gap is the actual score, not this race's P&L."
            )

        self.stolen_patterns.extend(patches)
        self.lessons.extend(patches)
        return patches
