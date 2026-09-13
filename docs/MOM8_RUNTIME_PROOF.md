# MOM8 runtime proof

The public MOM8 brand preview is served in CI from `public/mom8/` using a local static HTTP server and exercised with Chromium at desktop and mobile viewports.

Proof is bound to the exact pull-request head SHA through `SLEEPWEALTH_PROOF_SOURCE_SHA` and emits `artifacts/mom8-proof-manifest.json` plus desktop/mobile screenshots.

This proof establishes rendering, accessibility of the public identity surface, continuity markers, and the visible authority guardrail. It does not establish wallet, mint, launch, trade, spend, transfer, funding, or live-money authority.
