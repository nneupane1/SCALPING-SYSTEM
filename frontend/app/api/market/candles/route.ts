import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";

import type { CandlePoint } from "../../../../lib/types";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function resolveRepoRoot(): string {
  const candidates = [
    process.cwd(),
    path.resolve(process.cwd(), ".."),
    path.resolve(process.cwd(), "../.."),
  ];
  for (const candidate of candidates) {
    if (
      fs.existsSync(path.join(candidate, "data_storage")) &&
      fs.existsSync(path.join(candidate, "frontend"))
    ) {
      return candidate;
    }
  }
  return path.resolve(process.cwd(), "..");
}

function parseCsvLine(line: string): string[] {
  const fields: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"') {
      if (inQuotes && line[index + 1] === '"') {
        current += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (char === "," && !inQuotes) {
      fields.push(current);
      current = "";
      continue;
    }
    current += char;
  }

  fields.push(current);
  return fields;
}

function utcMillis(value: string): number {
  if (value.includes("T")) {
    if (/([+-]\d{2}:\d{2}|Z)$/.test(value)) {
      return new Date(value).getTime();
    }
    return new Date(`${value}Z`).getTime();
  }
  return new Date(`${value.replace(" ", "T")}Z`).getTime();
}

async function findLatestCsv(repoRoot: string, symbol: string, timeframe: string): Promise<string | null> {
  const timeframeDir = path.join(repoRoot, "data_storage", symbol, timeframe);
  if (!fs.existsSync(timeframeDir)) {
    return null;
  }
  const entries = await fs.promises.readdir(timeframeDir);
  const csvEntries = await Promise.all(
    entries
      .filter((entry) => entry.endsWith(".csv"))
      .map(async (entry) => {
        const fullPath = path.join(timeframeDir, entry);
        const stat = await fs.promises.stat(fullPath);
        return { fullPath, mtimeMs: stat.mtimeMs };
      }),
  );
  return csvEntries.sort((left, right) => right.mtimeMs - left.mtimeMs)[0]?.fullPath ?? null;
}

function sampleCandles(candles: CandlePoint[], maxRows: number): { candles: CandlePoint[]; sampleStride: number } {
  if (candles.length <= maxRows) {
    return { candles, sampleStride: 1 };
  }
  const stride = Math.ceil(candles.length / maxRows);
  const sampled = candles.filter((_, index) => index % stride === 0 || index === candles.length - 1);
  return { candles: sampled, sampleStride: stride };
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const symbol = (searchParams.get("symbol") ?? "BTCUSDT").toUpperCase();
  const timeframe = searchParams.get("timeframe") ?? "5m";
  const start = searchParams.get("start");
  const end = searchParams.get("end");
  const maxRows = Math.max(300, Number(searchParams.get("maxRows") ?? 2400));

  if (!start || !end) {
    return Response.json({ error: "start and end are required" }, { status: 400 });
  }

  const repoRoot = resolveRepoRoot();
  const filePath = await findLatestCsv(repoRoot, symbol, timeframe);
  if (!filePath) {
    return Response.json({ error: `No ${timeframe} data file found for ${symbol}` }, { status: 404 });
  }

  const startMillis = utcMillis(start);
  const endMillis = utcMillis(end);
  const stream = fs.createReadStream(filePath, { encoding: "utf8" });
  const reader = readline.createInterface({ input: stream, crlfDelay: Infinity });
  const candles: CandlePoint[] = [];
  let headerSkipped = false;

  for await (const line of reader) {
    if (!headerSkipped) {
      headerSkipped = true;
      continue;
    }
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    const [time, open, high, low, close, volume] = parseCsvLine(trimmed);
    const millis = utcMillis(time);
    if (millis < startMillis) {
      continue;
    }
    if (millis > endMillis) {
      break;
    }
    candles.push({
      time,
      open: Number(open),
      high: Number(high),
      low: Number(low),
      close: Number(close),
      volume: Number(volume ?? 0),
    });
  }

  const sampled = sampleCandles(candles, maxRows);
  return Response.json({
    candles: sampled.candles,
    truncated: sampled.sampleStride > 1,
    sampleStride: sampled.sampleStride,
    returnedRows: sampled.candles.length,
  });
}
