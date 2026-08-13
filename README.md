# SleepWealth Agent

SleepWealth Agent is a governed **local trading simulator** for testing approval, risk,
audit, and race-engine behavior with a mock $5 ceiling.

It does **not** connect to a broker, accept broker credentials, submit external orders,
or authorize live trading. Alpaca and IBKR modules are disabled compatibility stubs.

## Safety contract

Every simulated order passes through:

1. rules/evaluator checks,
2. an approval queue,
3. risk preflight,
4. an approval fingerprint bound to the exact reviewed order and evidence,
5. a fresh mock quote and second evaluation immediately before simulated submission,
6. an append-only local audit event.

The exact order object is immutable. Replacing the order or changing its reviewed
evaluation after approval invalidates the fingerprint and blocks execution.

## Quick start

```bash
make setup
make validate
make test
make run-paper
```

`make run-live` intentionally exits non-zero.

## Repository policy

| Capability | Status |
|---|---|
| Local mock simulation | enabled |
| Race simulation | enabled |
| Broker credentials | rejected |
| Alpaca network adapter | disabled |
| IBKR network adapter | disabled |
| Live execution | disabled |
| Gate authorizing live execution | impossible by contract |

The governance gate can report **SIMULATION READY**. It always reports
`live_execution_permitted: false` and never grants live authority.

## Honest limits

This repository does not prove an investment edge or predict winners. The race engines
operate on simulated data and are research/game mechanics around the governance system.

## License

MIT
