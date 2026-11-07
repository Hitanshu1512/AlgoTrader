import { PageTitle, UpcomingPhase } from "@/components/ui";

export default function RiskManagementPage() {
  return (
    <>
      <PageTitle title="Risk Management" subtitle="Limits, exposure and emergency controls" />
      <UpcomingPhase phase={4} items={["Daily/weekly loss limits, per-trade risk, max positions", "Current exposure by instrument and sector", "Kill switch and trading-mode control (Manual by default)"]} />
    </>
  );
}
