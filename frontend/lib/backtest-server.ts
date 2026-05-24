import "server-only";

import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";

import type {
  BacktestCandle,
  BacktestEquityPoint,
  BacktestSnapshot,
  BacktestStatus,
  BacktestSummaryView,
  BacktestTrade,
  BreakdownStat,
  GapWindow,
} from "./backtest-types";

type CsvRow = Record<string, string>;

type CheckpointRow = {
  closed_trades?: number;
  completed?: boolean;
  end_date?: string;
  equity?: number;
  execution_timeframe?: string;
  next_index?: number;
  resume_signature?: Record<string, unknown>;
  start_date?: string;
  symbol?: string;
  updated_at?: string;
};

type FileCacheEntry<T> = {
  mtimeMs: number;
  value: T;
};

const repoRootCache: { root?: string } = {};
const csvCache = new Map<string, FileCacheEntry<CsvRow[]>>();
const countCache = new Map<string, FileCacheEntry<number>>();

function resolveRepoRoot(): string {
  if (repoRootCache.root) {
    return repoRootCache.root;
  }

  const candidates = [
    process.cwd(),
    path.resolve(process.cwd(), ".."),
    path.resolve(process.cwd(), "../.."),
  ];
  for (const candidate of candidates) {
    if (
      fs.existsSync(path.join(candidate, "backtest")) &&
      fs.existsSync(path.join(candidate, "data_storage"))
    ) {
      repoRootCache.root = candidate;
      return candidate;
    }
  }

  repoRootCache.root = process.cwd();
  return repoRootCache.root;
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

async function getFileStat(filePath: string): Promise<fs.Stats | null> {
  try {
    return await fs.promises.stat(filePath);
  } catch {
    return null;
  }
}

async function readCsvRows(filePath: string): Promise<CsvRow[]> {
  const stat = await getFileStat(filePath);
  if (!stat) {
    return [];
  }

  const cached = csvCache.get(filePath);
  if (cached && cached.mtimeMs === stat.mtimeMs) {
    return cached.value;
  }

  const content = await fs.promises.readFile(filePath, "utf8");
  const lines = content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  if (lines.length === 0) {
    csvCache.set(filePath, { mtimeMs: stat.mtimeMs, value: [] });
    return [];
  }

  const header = parseCsvLine(lines[0]);
  const rows = lines.slice(1).map((line) => {
    const values = parseCsvLine(line);
    const row: CsvRow = {};
    for (let index = 0; index < header.length; index += 1) {
      row[header[index]] = values[index] ?? "";
    }
    return row;
  });

  csvCache.set(filePath, { mtimeMs: stat.mtimeMs, value: rows });
  return rows;
}

async function countDataRows(filePath: string): Promise<number> {
  const stat = await getFileStat(filePath);
  if (!stat) {
    return 0;
  }

  const cached = countCache.get(filePath);
  if (cached && cached.mtimeMs === stat.mtimeMs) {
    return cached.value;
  }

  const stream = fs.createReadStream(filePath, { encoding: "utf8" });
  const reader = readline.createInterface({ input: stream, crlfDelay: Infinity });
  let count = -1;
  for await (const _line of reader) {
    count += 1;
  }
  const safeCount = Math.max(0, count);
  countCache.set(filePath, { mtimeMs: stat.mtimeMs, value: safeCount });
  return safeCount;
}

function asNumber(value: string | number | undefined, fallback = 0): number {
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function asNullableNumber(value: string | undefined): number | null {
  if (!value) {
    return null;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function asBoolean(value: string | boolean | undefined): boolean {
  if (typeof value === "boolean") {
    return value;
  }
  return String(value).toLowerCase() === "true";
}

function utcMillis(value: string | null | undefined): number {
  if (!value) {
    return Number.NaN;
  }
  if (value.includes("T")) {
    if (/([+-]\d{2}:\d{2}|Z)$/.test(value)) {
      return new Date(value).getTime();
    }
    return new Date(`${value}Z`).getTime();
  }
  return new Date(`${value.replace(" ", "T")}Z`).getTime();
}

function toHistoryPathLabel(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  return value.trim().replace(" ", "T").replaceAll(":", ".");
}

async function readLatestCheckpoint(repoRoot: string): Promise<CheckpointRow | null> {
  const checkpointDir = path.join(repoRoot, "backtest", "output", "_checkpoints");
  const stat = await getFileStat(checkpointDir);
  if (!stat || !stat.isDirectory()) {
    return null;
  }

  const entries = await fs.promises.readdir(checkpointDir);
  const jsonFiles = await Promise.all(
    entries
      .filter((entry) => entry.endsWith(".json"))
      .map(async (entry) => {
        const fullPath = path.join(checkpointDir, entry);
        const fileStat = await fs.promises.stat(fullPath);
        return { fullPath, mtimeMs: fileStat.mtimeMs };
      }),
  );
  const latest = jsonFiles.sort((left, right) => right.mtimeMs - left.mtimeMs)[0];
  if (!latest) {
    return null;
  }

  const payload = await fs.promises.readFile(latest.fullPath, "utf8");
  return JSON.parse(payload) as CheckpointRow;
}

async function findPriceFile(
  repoRoot: string,
  symbol: string,
  executionTimeframe: string,
  startDate: string | null | undefined,
  endDate: string | null | undefined,
): Promise<string | null> {
  const timeframeDir = path.join(repoRoot, "data_storage", symbol, executionTimeframe);
  const dirStat = await getFileStat(timeframeDir);
  if (!dirStat || !dirStat.isDirectory()) {
    return null;
  }

  const expectedLabel = [
    `${symbol}_${executionTimeframe}_`,
    toHistoryPathLabel(startDate),
    "_to_",
    toHistoryPathLabel(endDate),
    ".csv",
  ].join("");
  const expectedPath = path.join(timeframeDir, expectedLabel);
  if (fs.existsSync(expectedPath)) {
    return expectedPath;
  }

  const entries = await fs.promises.readdir(timeframeDir);
  const candidates = await Promise.all(
    entries
      .filter((entry) => entry.endsWith(".csv"))
      .map(async (entry) => {
        const fullPath = path.join(timeframeDir, entry);
        const fileStat = await fs.promises.stat(fullPath);
        return { fullPath, mtimeMs: fileStat.mtimeMs };
      }),
  );
  return candidates.sort((left, right) => right.mtimeMs - left.mtimeMs)[0]?.fullPath ?? null;
}

async function readPriceWindow(
  filePath: string | null,
  simulatedTime: string | null,
  windowSize = 240,
): Promise<BacktestCandle[]> {
  if (!filePath) {
    return [];
  }

  const cutoff = simulatedTime ? new Date(simulatedTime).getTime() : Number.POSITIVE_INFINITY;
  const stream = fs.createReadStream(filePath, { encoding: "utf8" });
  const reader = readline.createInterface({ input: stream, crlfDelay: Infinity });
  const window: BacktestCandle[] = [];
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
    if (Number.isFinite(cutoff) && millis > cutoff) {
      break;
    }
    window.push({
      time,
      open: asNumber(open),
      high: asNumber(high),
      low: asNumber(low),
      close: asNumber(close),
      volume: asNumber(volume),
    });
    if (window.length > windowSize) {
      window.shift();
    }
  }

  return window;
}

function parseEquityRows(rows: CsvRow[], limit = 320): BacktestEquityPoint[] {
  return rows.slice(-limit).map((row) => ({
    time: row.timestamp,
    equity: asNumber(row.equity),
  }));
}

function parseTradeRows(rows: CsvRow[]): BacktestTrade[] {
  return rows.map((row) => ({
    symbol: row.symbol,
    timeframe: row.timeframe,
    side: row.side === "short" ? "short" : "long",
    openedAt: row.opened_at,
    closedAt: row.closed_at,
    entryPrice: asNumber(row.entry_price),
    exitPrice: asNumber(row.exit_price),
    initialQuantity: asNumber(row.initial_quantity),
    realizedPnl: asNumber(row.realized_pnl),
    realizedR: asNumber(row.realized_r),
    reason: row.reason,
    notes: row.notes,
    tags:
      row.tags
        ?.split("|")
        .map((tag) => tag.trim())
        .filter(Boolean) ?? [],
    marketState: row.market_state,
    contextAlignment: row.context_alignment,
    sessionName: row.session_name,
    sessionPhase: row.session_phase,
    setupQualityLabel: row.setup_quality_label,
    setupQualityScore: asNumber(row.setup_quality_score),
    dayFeedbackReason: row.day_feedback_reason,
    dayTradeCount: asNumber(row.day_trade_count),
    barsHeld: asNumber(row.bars_held),
    bestRMultiple: asNumber(row.best_r_multiple),
    worstRMultiple: asNumber(row.worst_r_multiple),
    firstTargetHitAfterBars: asNullableNumber(row.first_target_hit_after_bars),
    followThroughState: row.follow_through_state,
  }));
}

function parseGapRows(rows: CsvRow[]): GapWindow[] {
  return rows.map((row) => ({
    gapId: asNumber(row.gap_id),
    previousBaseTimestamp: row.previous_base_timestamp,
    nextBaseTimestamp: row.next_base_timestamp,
    missingStart: row.missing_start,
    missingEnd: row.missing_end,
    missingMinutes: asNumber(row.missing_minutes),
    previousExecutionIndex: asNullableNumber(row.previous_execution_index),
    previousExecutionClose: row.previous_execution_close || null,
    nextExecutionIndex: asNullableNumber(row.next_execution_index),
    nextExecutionOpen: row.next_execution_open || null,
    nextExecutionClose: row.next_execution_close || null,
    missingExecutionBars: asNumber(row.missing_execution_bars),
    blockedEntryStartIndex: asNullableNumber(row.blocked_entry_start_index),
    blockedEntryEndIndex: asNullableNumber(row.blocked_entry_end_index),
    forceFlatBeforeGap: asBoolean(row.force_flat_before_gap),
    postGapCooldownBars: asNumber(row.post_gap_cooldown_bars),
  }));
}

function buildBreakdown(
  trades: BacktestTrade[],
  pickLabel: (trade: BacktestTrade) => string,
  limit = 6,
): BreakdownStat[] {
  const buckets = new Map<string, { trades: number; wins: number; totalR: number }>();
  for (const trade of trades) {
    const label = pickLabel(trade) || "unknown";
    const bucket = buckets.get(label) ?? { trades: 0, wins: 0, totalR: 0 };
    bucket.trades += 1;
    bucket.totalR += trade.realizedR;
    if (trade.realizedR > 0) {
      bucket.wins += 1;
    }
    buckets.set(label, bucket);
  }

  return [...buckets.entries()]
    .map(([label, bucket]) => ({
      label,
      trades: bucket.trades,
      winRate: bucket.trades ? bucket.wins / bucket.trades : 0,
      avgR: bucket.trades ? bucket.totalR / bucket.trades : 0,
      totalR: bucket.totalR,
    }))
    .sort((left, right) => right.totalR - left.totalR)
    .slice(0, limit);
}

function computeMaxDrawdown(equityRows: BacktestEquityPoint[]): number {
  let peak = Number.NEGATIVE_INFINITY;
  let maxDrawdown = 0;
  for (const point of equityRows) {
    if (point.equity > peak) {
      peak = point.equity;
    }
    maxDrawdown = Math.min(maxDrawdown, point.equity - peak);
  }
  return maxDrawdown;
}

function deriveStatus(checkpoint: CheckpointRow | null): BacktestStatus {
  if (!checkpoint) {
    return "idle";
  }
  if (checkpoint.completed) {
    return "completed";
  }
  if (!checkpoint.updated_at) {
    return "paused";
  }
  const ageMs = Date.now() - new Date(checkpoint.updated_at).getTime();
  return ageMs <= 120_000 ? "running" : "paused";
}

function buildSummary(
  checkpoint: CheckpointRow | null,
  trades: BacktestTrade[],
  equityRows: BacktestEquityPoint[],
  gapWindows: GapWindow[],
): BacktestSummaryView {
  const startingEquity =
    asNumber(checkpoint?.resume_signature?.starting_equity as number | undefined, 25_000);
  const currentEquity =
    equityRows.at(-1)?.equity ?? asNumber(checkpoint?.equity, startingEquity);
  const realizedPnl = currentEquity - startingEquity;
  const winCount = trades.filter((trade) => trade.realizedR > 0).length;
  const totalR = trades.reduce((sum, trade) => sum + trade.realizedR, 0);
  const bestTradeR =
    trades.length > 0 ? Math.max(...trades.map((trade) => trade.realizedR)) : 0;
  const worstTradeR =
    trades.length > 0 ? Math.min(...trades.map((trade) => trade.realizedR)) : 0;

  return {
    symbol: checkpoint?.symbol ?? "BTCUSDT",
    executionTimeframe: checkpoint?.execution_timeframe ?? "5m",
    startDate: checkpoint?.start_date ?? null,
    endDate: checkpoint?.end_date ?? null,
    startingEquity,
    currentEquity,
    realizedPnl,
    closedTrades: trades.length,
    winRate: trades.length ? winCount / trades.length : 0,
    avgR: trades.length ? totalR / trades.length : 0,
    bestTradeR,
    worstTradeR,
    maxDrawdown: computeMaxDrawdown(equityRows),
    gapWindows: gapWindows.length,
    sessionBreakdown: buildBreakdown(trades, (trade) => trade.sessionName || "no session"),
    qualityBreakdown: buildBreakdown(
      trades,
      (trade) => trade.setupQualityLabel || "unlabeled quality",
    ),
    stateBreakdown: buildBreakdown(trades, (trade) => trade.marketState || "unknown state"),
  };
}

function filterWindowTrades(
  trades: BacktestTrade[],
  windowStart: number,
  windowEnd: number,
): BacktestTrade[] {
  return trades.filter((trade) => {
    const openedAt = utcMillis(trade.openedAt);
    const closedAt = utcMillis(trade.closedAt);
    return closedAt >= windowStart && openedAt <= windowEnd;
  });
}

function filterWindowGaps(
  gapWindows: GapWindow[],
  windowStart: number,
  windowEnd: number,
): GapWindow[] {
  return gapWindows.filter((gap) => {
    const gapStart = utcMillis(gap.missingStart);
    const gapEnd = utcMillis(gap.missingEnd);
    return gapEnd >= windowStart && gapStart <= windowEnd;
  });
}

export async function loadBacktestSnapshot(): Promise<BacktestSnapshot> {
  const repoRoot = resolveRepoRoot();
  const checkpoint = await readLatestCheckpoint(repoRoot);

  const equityPath = path.join(repoRoot, "backtest", "output", "equity.csv");
  const tradesPath = path.join(repoRoot, "backtest", "output", "trades.csv");
  const gapPath = path.join(repoRoot, "backtest", "output", "gap_windows.csv");

  const [equityRowsRaw, tradeRowsRaw, gapRowsRaw] = await Promise.all([
    readCsvRows(equityPath),
    readCsvRows(tradesPath),
    readCsvRows(gapPath),
  ]);

  const equityRows = parseEquityRows(equityRowsRaw);
  const trades = parseTradeRows(tradeRowsRaw);
  const gapWindows = parseGapRows(gapRowsRaw);
  const summary = buildSummary(checkpoint, trades, equityRows, gapWindows);

  const symbol = summary.symbol;
  const executionTimeframe = summary.executionTimeframe;
  const simulatedTime = equityRows.at(-1)?.time ?? null;
  const priceFile = await findPriceFile(
    repoRoot,
    symbol,
    executionTimeframe,
    summary.startDate,
    summary.endDate,
  );
  const [candles, totalRows] = await Promise.all([
    readPriceWindow(priceFile, simulatedTime),
    priceFile ? countDataRows(priceFile) : Promise.resolve(0),
  ]);

  const windowStart = candles.length ? utcMillis(candles[0].time) : 0;
  const windowEnd = candles.length ? utcMillis(candles.at(-1)!.time) : 0;
  const windowTrades = candles.length ? filterWindowTrades(trades, windowStart, windowEnd) : [];
  const windowGapWindows = candles.length ? filterWindowGaps(gapWindows, windowStart, windowEnd) : [];

  const anomalies: string[] = [];
  if (!priceFile) {
    anomalies.push("No resampled execution file found for the active backtest range.");
  }
  if (gapWindows.length > 0) {
    anomalies.push(
      `${gapWindows.length} historical outage windows are being guarded by the gap-aware backtest.`,
    );
  }
  if (trades.length === 0) {
    anomalies.push("No closed trades recorded yet in the current output set.");
  }

  return {
    asOf: new Date().toISOString(),
    progress: {
      nextIndex: asNumber(checkpoint?.next_index),
      totalRows,
      progressPct: totalRows ? asNumber(checkpoint?.next_index) / totalRows : 0,
      simulatedTime,
      checkpointUpdatedAt: checkpoint?.updated_at ?? null,
      status: deriveStatus(checkpoint),
    },
    summary,
    candles,
    equity: equityRows,
    recentTrades: trades.slice(-18).reverse(),
    windowTrades,
    gapWindows,
    windowGapWindows,
    latestTrade: trades.at(-1) ?? null,
    anomalies,
  };
}
