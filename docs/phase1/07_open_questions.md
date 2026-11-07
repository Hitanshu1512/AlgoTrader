# 7. Open Questions for the Owner (needed to finalize V1)

1. **Broker:** Which broker(s) do you currently hold an account with? (Upstox, Zerodha, Angel One, Dhan, Fyers, other?) If none or several, are you fine with **Upstox** as the first adapter (recommended) or do you prefer **Zerodha** (₹500/month for data)?
2. **Asset classes and style:** Which of these for V1?
   - NSE/BSE equity **intraday** (MIS)
   - NSE/BSE equity **swing/delivery** (CNC)
   - Index/stock **F&O** (futures, options). Recommended to defer to V2.
   - Commodities (MCX). Recommended to defer.
3. **Capital and risk appetite:** Roughly how much capital for automated trading at first, and what maximum daily loss you'd accept (₹ or %)? This sets the initial risk-config defaults.
4. **Cloud budget:** Is ~₹1,500–2,000/month for staging and ~₹4,000–5,000/month for production acceptable? Any existing AWS/GCP/Azure account or credits?
5. **Static IP:** Have you already registered a static IP with your broker? If yes, where is it hosted? (The cloud server's IP must be the registered one.)
6. **Kill-switch default:** On emergency stop, should open positions be **flattened** or **kept with broker-side stop-losses** (`PROTECT_ONLY`, proposed default)?
7. **Notifications:** Is Telegram fine as the first channel?
8. **Usage:** Confirm this platform will only ever trade **your own** account (this keeps it inside the "self-built personal algo" category).
