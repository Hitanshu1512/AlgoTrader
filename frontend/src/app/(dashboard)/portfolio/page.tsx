import { PageTitle, UpcomingPhase } from "@/components/ui";

export default function PortfolioPage() {
  return (
    <>
      <PageTitle title="Portfolio" subtitle="Holdings and open positions" />
      <UpcomingPhase phase={3} items={["Holdings (delivery) with average price and P&L", "Intraday and swing positions with stop-loss and target", "Reconciled against your Upstox account"]} />
    </>
  );
}
