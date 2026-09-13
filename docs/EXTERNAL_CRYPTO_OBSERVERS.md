# External Crypto Observers

Sleep Wealth may ingest limited external crypto evidence for paper simulation, but external sources never become brokers, wallets, swap engines, or execution authorities.

## Capability ceiling

### Pump.fun

- Mode: manual public evidence only.
- Network automation: none.
- Automated crawling/scraping: disabled.
- Accepted evidence: public `https://pump.fun/...` source URL plus non-secret descriptive fields such as symbol, mint, name, market cap, and observed timestamp.
- Rejected fields include wallet, private key, secret, quote, shift, order, deposit, settlement, and address-like execution fields.
- Output is a read-only observation receipt with a continuity fingerprint/cookie and `authority: none`.

### SideShift

- Mode: public supported-coin catalog only.
- Network ceiling: `GET /api/v2/coins` only.
- No account secret is accepted or used.
- No quote, fixed shift, variable shift, deposit, settlement, wallet connection, or order creation capability exists.
- Output is a read-only catalog receipt with a continuity fingerprint/cookie and `authority: none`.

## Invariants

1. `read_only` is always `true`.
2. `authority` is always `none`.
3. `real_money` is always `false`.
4. `wallet_connection` is always `false`.
5. `trading_enabled` is always `false`.
6. External observations may inform a paper-only decision, but they cannot create or renew approval or execution authority.
7. Sleep Wealth execution remains confined to governed simulation brokers.
8. Any future change that introduces credentials, wallet access, swap/quote creation, deposit instructions, settlement addresses, or live execution requires a separate safety review and is outside this observer contract.

## Proof

`tests/test_external_crypto_sources.py` independently verifies the Pump.fun and SideShift boundaries. CI runs that test file as its own gate so a failure in one external-source contract cannot be hidden inside a broader green test result.
