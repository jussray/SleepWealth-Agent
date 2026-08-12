"""GatesEngine.

Style: evidence first, size small, repeat forever. Prefers the boring instrument
with the longest clean run. Holds when the read isn't clear, and treats holding
as a move rather than a failure to act.

Same Redteam contract as Musk, threshold 30. It will refuse trades Musk takes
happily, and that refusal is the strategy, not timidity.
"""

from typing import List

from race.engines.base import EngineState, MarketSnapshot, RaceEngine
from race.modes import Decision, FutureYou, Mode, ModeNote

DEFAULT_RISK_THRESHOLD = 30.0
DEFAULT_MAX_DRAWDOWN = 8.0


class GatesEngine(RaceEngine):
    def __init__(self, approved_symbols: List[str],
                 risk_threshold: float = DEFAULT_RISK_THRESHOLD,
                 max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN):
        super().__init__("Gates", risk_threshold, max_drawdown_pct, approved_symbols)
        self.position_size = 0.35     # % of remaining stake per entry
        self.min_conviction = 60.0    # will not act below this
        self.take_profit = 4.0        # % gain that banks the position
        self.stop = -3.0              # % loss that closes it
        self.borrowed_patterns: List[str] = []

    # ---- decision ----------------------------------------------------

    def decide(self, snapshot: MarketSnapshot, state: EngineState) -> Decision:
        modes: List[ModeNote] = []

        candidates = [
            (sym, snapshot.ticks[sym])
            for sym in self.approved_symbols
            if sym in snapshot.ticks
        ]
        if not candidates:
            return self.record(self.hold(
                "no market data; will not act on an empty read",
                FutureYou(
                    enables="the habit of requiring data before capital",
                    breaks="nothing — this is the cheapest correct move available",
                    durable=True,
                ),
                [ModeNote(Mode.OODA, "observe returned nothing; loop stops here")],
            ))

        # Manage what's open before opening anything new.
        for sym, qty in list(state.positions.items()):
            if qty <= 0:
                continue
            pnl = state.unrealized_pct(sym, snapshot)

            if pnl >= self.take_profit:
                modes.append(ModeNote(
                    Mode.LINDY,
                    f"{sym} hit +{pnl:.1f}%. Banking a small win repeatedly beats "
                    "waiting for a large one occasionally.",
                ))
                return self.record(Decision(
                    engine=self.name, action="sell", symbol=sym, qty=qty,
                    confidence=80.0, risk_score=8.0,
                    reasoning=f"take profit on {sym} at {pnl:+.1f}%",
                    futureyou=FutureYou(
                        enables="a realized-gain rhythm that funds the vault every race",
                        breaks="the tail if this one was going to run much further",
                        durable=True,
                    ),
                    modes=modes,
                ))

            if pnl <= self.stop:
                modes.append(ModeNote(
                    Mode.REDTEAM,
                    f"{sym} through stop at {pnl:.1f}%. Position closes on the rule, "
                    "not on my opinion of the rule.",
                ))
                return self.record(Decision(
                    engine=self.name, action="sell", symbol=sym, qty=qty,
                    confidence=90.0, risk_score=5.0,
                    reasoning=f"stop out {sym} at {pnl:+.1f}%",
                    futureyou=FutureYou(
                        enables="a stake that is still here in three races",
                        breaks="recovery if this reverses immediately after I'm out",
                        durable=True,
                    ),
                    modes=modes,
                ))

        # LINDY: rank by durability, not excitement.
        scored = []
        for sym, tick in candidates:
            vol = snapshot.volatility(sym)
            trend = snapshot.trend(sym)
            # Reward steady positive drift. Penalise noise hard.
            score = (trend * 2.0) - (vol * 2.5)
            scored.append((score, sym, tick, vol, trend))
        scored.sort(reverse=True, key=lambda r: r[0])

        modes.append(ModeNote(
            Mode.LINDY,
            "ranked by drift-minus-noise: "
            + ", ".join(f"{s[1]} {s[0]:+.1f}" for s in scored[:4]),
        ))

        best_score, sym, tick, vol, trend = scored[0]

        if state.positions.get(sym, 0) > 0:
            pnl = state.unrealized_pct(sym, snapshot)
            return self.record(self.hold(
                f"holding {sym} at {pnl:+.1f}%, inside stop and target",
                FutureYou(
                    enables="letting a rule finish before second-guessing it",
                    breaks="nothing; the exit conditions are already defined",
                    durable=True,
                ),
                modes + [ModeNote(Mode.OODA, "no new information; no new action")],
            ))

        conviction = 50.0 + (best_score * 4.0)

        if self.borrowed_patterns:
            modes.append(ModeNote(
                Mode.STEAL,
                "borrowed from opponent: " + "; ".join(self.borrowed_patterns[-2:]),
            ))

        if conviction < self.min_conviction:
            modes.append(ModeNote(
                Mode.TRUTHMODE,
                f"conviction {conviction:.0f} < floor {self.min_conviction:.0f}. "
                "The honest read is that I don't have an edge here.",
            ))
            modes.append(ModeNote(
                Mode.CONFESS,
                "Musk will likely trade this window and may well win it. That "
                "doesn't make trading it correct for me.",
            ))
            return self.record(self.hold(
                f"no qualifying setup (best {sym} at conviction {conviction:.0f})",
                FutureYou(
                    enables="a stake preserved for a window that actually qualifies",
                    breaks="this race, if the whole window was the opportunity",
                    durable=True,
                ),
                modes,
            ))

        if state.cash < 0.25:
            return self.record(self.hold(
                f"stake committed (${state.cash:.2f} free)",
                FutureYou(
                    enables="nothing new; existing rules manage the open position",
                    breaks="flexibility until something closes",
                    durable=True,
                ),
                modes,
            ))

        commit = state.cash * self.position_size
        qty = commit / tick.price
        risk = min(100.0, (vol * 5.0) + (self.position_size * 30.0))

        modes.append(ModeNote(
            Mode.REDTEAM,
            f"self-attack: {sym} vol {vol:.2f}%, sized {self.position_size:.0%} of free "
            f"stake so a full stop costs ~{abs(self.stop) * self.position_size:.1f}% of "
            f"the race. Risk {risk:.0f} vs threshold {self.risk_threshold:.0f}.",
        ))
        modes.append(ModeNote(
            Mode.OODA,
            f"decide: enter {sym} small, let the stop and target do the rest",
        ))

        return self.record(Decision(
            engine=self.name,
            action="buy",
            symbol=sym,
            qty=qty,
            confidence=min(90.0, conviction),
            risk_score=risk,
            reasoning=(
                f"enter {sym} at {self.position_size:.0%} of free stake; "
                f"drift {trend:+.2f}% against vol {vol:.2f}%"
            ),
            futureyou=FutureYou(
                enables=(
                    "a repeatable entry that looks identical in race 1 and race 30 — "
                    "the only kind that can be audited and improved"
                ),
                breaks=(
                    "any chance of a spectacular single race; this ceiling is real "
                    "and chosen"
                ),
                durable=True,
            ),
            modes=modes,
        ))

    # ---- learning ----------------------------------------------------

    def learn_from_moves(self, opponent_decisions: List[Decision]) -> List[str]:
        """Read Musk's moves. Copy the process, not the outcome."""
        patches: List[str] = []

        executed = [d for d in opponent_decisions if d.executed]
        vetoed = [d for d in opponent_decisions if d.vetoed_by]

        if executed:
            avg_conf = sum(d.confidence for d in executed) / len(executed)
            avg_risk = sum(d.risk_score for d in executed) / len(executed)
            patches.append(
                f"Musk executed {len(executed)}x at avg conviction {avg_conf:.0f} / "
                f"risk {avg_risk:.0f}. It acts on reads I'd have discarded. Some of "
                "those reads were structurally fine — my floor may be filtering "
                "signal, not just noise."
            )
            if avg_conf > self.min_conviction:
                self.min_conviction = max(52.0, self.min_conviction - 3.0)

        aggressive = [d for d in executed if d.qty > 0]
        if aggressive:
            patches.append(
                "Musk concentrates. On a $5 stake, my 35% sizing may be too small "
                "to escape fee and spread drag. Testing a modest increase."
            )
            self.position_size = min(0.50, self.position_size + 0.05)

        if vetoed:
            patches.append(
                f"Musk's Redteam caught {len(vetoed)} of its own moves. Even at "
                "threshold 75 the governance fired. The difference between us is "
                "tolerance, not discipline — worth remembering before I call it luck."
            )

        cuts = [d for d in opponent_decisions if d.action == "sell"]
        if cuts:
            patches.append(
                f"Musk exited {len(cuts)}x, fast. My stop is -3% and fires late "
                "when moves are sharp. Watching whether earlier exits beat tighter ones."
            )

        self.borrowed_patterns.extend(patches)
        self.lessons.extend(patches)
        return patches
