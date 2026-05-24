import { loadBacktestSnapshot } from "../../../../lib/backtest-server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  const snapshot = await loadBacktestSnapshot();
  return Response.json(snapshot, {
    headers: {
      "Cache-Control": "no-store, max-age=0",
    },
  });
}
