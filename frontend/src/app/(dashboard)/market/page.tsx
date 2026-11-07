import { PageTitle, UpcomingPhase } from "@/components/ui";

export default function MarketWatchPage() {
  return (
    <>
      <PageTitle title="Market Watch" subtitle="Indices and watchlist" />
      <UpcomingPhase phase={3} items={["Nifty 50, Bank Nifty and Sensex with live prices", "Watchlist with LTP, % change and volume", "Streaming over WebSocket from the Upstox market-data feed"]} />
    </>
  );
}
