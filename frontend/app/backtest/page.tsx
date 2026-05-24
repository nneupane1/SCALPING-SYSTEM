import { BacktestCinema } from "../../components/backtest/BacktestCinema";
import { loadBacktestSnapshot } from "../../lib/backtest-server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function BacktestPage() {
  const snapshot = await loadBacktestSnapshot();
  return <BacktestCinema initialSnapshot={snapshot} />;
}
