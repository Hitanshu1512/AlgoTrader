"use client";

import { PageTitle, Panel, Stat, UpcomingPhase } from "@/components/ui";
import { useLive } from "@/lib/live";

export default function OverviewPage() {
  const { status } = useLive();
  return (
    <>
      <PageTitle title="Overview" subtitle="Account summary and today's activity" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Account value" value="—" hint="Needs broker connection (Phase 3)" />
        <Stat label="Available balance" value="—" hint="Needs broker connection (Phase 3)" />
        <Stat label="Today's P&L" value="—" hint="Phase 3–4" />
        <Stat label="Trading environment" value={status ? status.trading_env.toUpperCase() : "…"} hint="Live trading stays off until Phase 8" />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel title="Positions & orders">
          <UpcomingPhase phase={3} items={["Active positions with unrealized P&L", "Open orders", "Invested capital, realized/unrealized P&L"]} />
        </Panel>
        <Panel title="Risk utilisation">
          <UpcomingPhase phase={4} items={["Daily loss limit utilisation", "Open-position count vs limit", "Trading mode (Manual by default) and kill switch"]} />
        </Panel>
      </div>
    </>
  );
}
