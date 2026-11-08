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
| 2026-11-07 | Sampled-month test (7 random months 2020–26, ₹30k accounts): **no shortlisted strategy is executable with ₹30,000 at 2025–26 contract sizes**; 0 signals could be margined in Jun 2025 and Jan 2026 | Research result |
| 2026-11-07 | Candidates for further testing (capital-adequate): 1) expiry-day hedged straddle (Nifty, Bank Nifty secondary), 2) expiry-day straddle (Nifty), 3) 9:20 short strangle (Nifty). Minimum capital ≈ ₹1.5 lakh (1) / ≈ ₹2.7 lakh (2, 3) per lot | Research result, owner to decide capital |
| 2026-11-07 | Correction: hedged-straddle margin is ≈ ₹0.9–1.3 lakh per lot, not ~₹47k (ELM was omitted). Recommended capital for 1 lot raised to ≈ ₹2 lakh | Correction |
| 2026-11-08 | Stage 2 (₹1 lakh, 7 new random months, seed 20261109): under the owner's risk rules (1% risk per trade, 2% daily loss, 10% drawdown pause) **S1 and S2 cannot place a single trade** (one lot's planned risk ₹1.5k–₹5.1k > ₹1k budget) and S3 loses ₹5,245. Mechanical 1-lot results: S1 +₹23,141, S2 (defined-risk) +₹16,274, S3 −₹1,805 | Research result |
| 2026-11-08 | **No real-money deployment with ₹1 lakh.** Primary candidate stays S1 (expiry-day hedged straddle), paper trading only, until capital can follow the 1% rule (≈ ₹3.9 lakh at 2025–26 lot sizes). Alternatives: S2 with wings; S3 for paper benchmarking only | Recommendation, owner to decide |
| 2026-11-08 | Correction: Bank Nifty expiry calendar had 6 non-existent Wednesday expiries (Sep 2023 – Feb 2024). Fixed; calendar now matches NSE actual expiries 100% (Apr 2020 – Apr 2026). All studies re-run; Bank Nifty figures moved ~1–3%, no conclusion changed | Correction |

