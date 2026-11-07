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
