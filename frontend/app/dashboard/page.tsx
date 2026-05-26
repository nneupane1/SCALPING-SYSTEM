import { RuntimeOpsBoard } from "../../components/runtime/RuntimeOpsBoard";
import { loadRuntimeSnapshot } from "../../lib/runtime-server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default async function DashboardPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const resolved = (await searchParams) ?? {};
  const mode = resolved.mode === "live" ? "live" : "paper";
  const snapshot = await loadRuntimeSnapshot(mode);
  return <RuntimeOpsBoard initialSnapshot={snapshot} />;
}
