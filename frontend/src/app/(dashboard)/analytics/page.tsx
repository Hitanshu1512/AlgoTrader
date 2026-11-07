import { PageTitle, UpcomingPhase } from "@/components/ui";

export default function TradeHistoryAnalyticsPage() {
  return (
    <>
      <PageTitle title="Trade History & Analytics" subtitle="Performance over time" />
      <UpcomingPhase phase={6} items={["Complete trade history", "Win rate, profit factor, max drawdown, average win/loss", "Strategy-wise and daily/weekly/monthly returns"]} />
    </>
  );
}
