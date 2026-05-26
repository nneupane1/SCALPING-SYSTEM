import { loadRuntimeSnapshot } from "../../../../lib/runtime-server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const mode = searchParams.get("mode") === "live" ? "live" : "paper";
  const snapshot = await loadRuntimeSnapshot(mode);
  return Response.json(snapshot, {
    headers: {
      "Cache-Control": "no-store, max-age=0",
    },
  });
}
