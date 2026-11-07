import { PageTitle, UpcomingPhase } from "@/components/ui";

export default function StrategyCenterPage() {
  return (
    <>
      <PageTitle title="Strategy Center" subtitle="Configure and monitor strategies" />
      <UpcomingPhase phase={4} items={["MA crossover, RSI, MACD, VWAP intraday and Breakout strategies", "Per-strategy parameters, instruments, timeframes and limits", "Active signals with reasoning; backtest results (Phase 5)"]} />
    </>
  );
}
