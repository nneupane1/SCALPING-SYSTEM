import { BacktestCinema } from "../../components/backtest/BacktestCinema";
import { loadBacktestSnapshot } from "../../lib/backtest-server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type BacktestPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function BacktestPage({ searchParams }: BacktestPageProps) {
  const resolvedSearchParams = (await searchParams) ?? {};
  const symbolParam = resolvedSearchParams.symbol;
  const symbol = Array.isArray(symbolParam) ? symbolParam[0] : symbolParam;
  const snapshot = await loadBacktestSnapshot(symbol);
  return <BacktestCinema initialSnapshot={snapshot} />;
}
