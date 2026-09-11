# Project Sovereignty Contract

This project must preserve its core product meaning and critical operating capability if an external provider, API, SDK, model, connector, runtime, or vendor disappears or materially changes.

- Project-owned contracts define canonical inputs, outputs, errors, authority, state, evidence, and completion semantics.
- External providers are adapters, not project identity.
- Critical dependencies are `REPLACEABLE`, `DEGRADED_FALLBACK`, `HARD_DEPENDENCY`, or `UNKNOWN`.
- Critical capability needs an alternate adapter, local/open implementation, deterministic fallback, export/manual recovery path, or honest safe degraded mode unless a documented hard dependency is explicitly accepted.
- Critical data keeps project-owned semantics and a migration/export path.
- Provider swaps must not broaden authority, replay stale approvals, duplicate mutations, or weaken evidence requirements.
- Provider outcomes map into project-owned receipts; provider acceptance is not outcome proof.
- When operated through Founder Control Room, this remains a sovereign subsystem, not a separate founder OS.

Mandatory audit question: **If every named provider disappeared now, what stops, what survives, what is the recovery path, and what evidence proves it?**

Use: Reality → ULTRATHINK → Redteam I → Lindy → L99 → OODA → smallest reversible implementation → focused proof → Redteam II/provider-loss attack → rollback → next gate.
