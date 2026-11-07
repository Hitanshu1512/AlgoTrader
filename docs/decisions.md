# Decision Log

| Date | Decision | Source |
|---|---|---|
| 2026-11-07 | **Broker: Upstox** (first and only adapter in V1) | Owner |
| 2026-11-07 | **Asset classes: NSE/BSE equity intraday (MIS) and swing/delivery (CNC).** F&O and commodities deferred | Owner |
| 2026-11-07 | **Cloud budget approved**: ~₹1,500–2,000/month staging, ~₹4,000–5,000/month production (AWS Mumbai) | Owner |
| 2026-11-07 | Phase 1 architecture approved; Phase 2 started | Owner |
| 2026-11-07 | Defaults assumed until the owner says otherwise: kill-switch policy `PROTECT_ONLY`; Telegram as first notification channel; single-owner account only | Proposed defaults |
| 2026-11-07 | Still open (needed before Phase 4/8): starting capital and max daily loss; whether a static IP is already registered with Upstox | Owner to answer |
| 2026-11-07 | Phase 2 creates only identity/audit tables; later tables arrive with the phase that uses them (incremental migrations, not one big schema) | Implementation |
| 2026-11-07 | Python dependency management with `uv` (lockfile `backend/uv.lock`) | Implementation |
| 2026-11-07 | Owner requested index F&O strategy research (Nifty 50, Bank Nifty). **F&O moves into V1 scope**; equity intraday/swing remain supported by the platform | Owner |
| 2026-11-07 | **First strategy for paper trading: Nifty 50 expiry-day hedged short straddle** (11:00 entry, 50% per-leg stop, ~Δ0.01 wings, exit 15:15). Chosen from 10 screened / 5 stress-tested strategies; see `docs/research/fno_strategy_backtest.md` | Research result, owner to approve |
| 2026-11-07 | Live money for this strategy only after: real intraday decay measured, ≥12 paper-traded expiries within go/no-go limits, Phase 8 checklist | Safety rule |
