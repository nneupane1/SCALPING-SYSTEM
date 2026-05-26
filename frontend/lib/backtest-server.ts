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
  SymbolPerformanceStat,
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
  symbols?: string[];
  updated_at?: string;
};

type FileCacheEntry<T> = {
  mtimeMs: number;
  value: T;
};

const repoRootCache: { root?: string } = {};
const csvCache = new Map<string, FileCacheEntry<CsvRow[]>>();
const countCache = new Map<string, FileCacheEntry<number>>();
const RECOMMENDED_UNIVERSE = [
  "BTCUSDT",
  "ETHUSDT",
  "BNBUSDT",
  "SOLUSDT",
  "LINKUSDT",
  "XRPUSDT",
  "AAVEUSDT",
  "TRXUSDT",
] as const;

function factorBucketForSymbol(symbol: string): string {
  const normalized = symbol.toUpperCase();
  if (normalized === "BTCUSDT") return "core_beta";
  if (normalized === "ETHUSDT") return "smart_contract_core";
  if (normalized === "BNBUSDT") return "exchange_chain";
  if (normalized === "SOLUSDT") return "high_beta_l1";
  if (normalized === "AVAXUSDT") return "overlap_l1";
  if (normalized === "LINKUSDT") return "oracle_infra";
  if (normalized === "XRPUSDT") return "payments";
  if (normalized === "TRXUSDT") return "payments_alt";
  if (normalized === "AAVEUSDT") return "defi_lending";
  if (normalized === "UNIUSDT") return "dex_defi";
  if (normalized === "PAXGUSDT") return "metal_proxy";
  return "general_crypto";
}

function classifySymbolPerformance(
  trades: number,
  winRate: number,
  avgR: number,
  totalR: number,
): {
  recommendation: "keep" | "watch" | "prune";
  rationale: string;
} {
  if (trades < 12) {
    return {
      recommendation: "watch",
      rationale: "Sample is still too small to trust. Keep observing before pruning.",
    };
  }
  if (totalR >= 1.0 && avgR > 0 && winRate >= 0.38) {
    return {
      recommendation: "keep",
      rationale: "Positive expectancy with enough sample. Keep it in the ranked universe.",
    };
  }
  if (totalR <= -1.0 && avgR <= 0 && winRate < 0.45) {
    return {
      recommendation: "prune",
      rationale: "Negative contribution with enough sample. Demote it unless recent evidence reverses.",
    };
  }
  return {
    recommendation: "watch",
    rationale: "Mixed evidence. Keep it under review and let recent-regime data decide.",
  };
}

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

function parseScopeSymbols(checkpoint: CheckpointRow | null): string[] {
  if (!checkpoint) {
    return ["BTCUSDT"];
  }
  const explicit = Array.isArray(checkpoint.symbols)
    ? checkpoint.symbols
    : Array.isArray(checkpoint.resume_signature?.symbols)
      ? (checkpoint.resume_signature?.symbols as string[])
      : [];
  const normalizedExplicit = explicit
    .map((value) => String(value).trim().toUpperCase())
    .filter(Boolean);
  if (normalizedExplicit.length > 0) {
    return [...new Set(normalizedExplicit)];
  }
  const scope = String(checkpoint.symbol ?? "BTCUSDT");
  const split = scope.includes("__") ? scope.split("__") : [scope];
  const normalized = split
    .map((value) => value.trim().toUpperCase())
    .filter(Boolean);
  return normalized.length > 0 ? [...new Set(normalized)] : ["BTCUSDT"];
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
  windowSize = 480,
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
    symbol: row.symbol || "BTCUSDT",
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

function buildSymbolBreakdown(trades: BacktestTrade[]): SymbolPerformanceStat[] {
  const buckets = new Map<
    string,
    { trades: number; wins: number; totalR: number; realizedPnl: number; latestTradeAt: string | null }
  >();
  for (const trade of trades) {
    const bucket = buckets.get(trade.symbol) ?? {
      trades: 0,
      wins: 0,
      totalR: 0,
      realizedPnl: 0,
      latestTradeAt: null,
    };
    bucket.trades += 1;
    bucket.totalR += trade.realizedR;
    bucket.realizedPnl += trade.realizedPnl;
    if (trade.realizedR > 0) {
      bucket.wins += 1;
    }
    if (!bucket.latestTradeAt || utcMillis(trade.closedAt) > utcMillis(bucket.latestTradeAt)) {
      bucket.latestTradeAt = trade.closedAt;
    }
    buckets.set(trade.symbol, bucket);
  }

  return [...buckets.entries()]
    .map(([symbol, bucket]) => {
      const winRate = bucket.trades ? bucket.wins / bucket.trades : 0;
      const avgR = bucket.trades ? bucket.totalR / bucket.trades : 0;
      const evidence = classifySymbolPerformance(bucket.trades, winRate, avgR, bucket.totalR);
      return {
        symbol,
        trades: bucket.trades,
        winRate,
        avgR,
        totalR: bucket.totalR,
        realizedPnl: bucket.realizedPnl,
        latestTradeAt: bucket.latestTradeAt,
        factorBucket: factorBucketForSymbol(symbol),
        recommendation: evidence.recommendation,
        rationale: evidence.rationale,
      };
    })
    .sort((left, right) => {
      if (right.totalR !== left.totalR) {
        return right.totalR - left.totalR;
      }
      return left.symbol.localeCompare(right.symbol);
    });
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
  symbols: string[],
  activeSymbol: string,
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
  const symbolBreakdown = buildSymbolBreakdown(trades);
  const symbolScope = checkpoint?.symbol ?? symbols.join("__");
  const resumeSignature = checkpoint?.resume_signature ?? {};
  const clockTimeframe =
    typeof resumeSignature.clock_timeframe === "string"
      ? resumeSignature.clock_timeframe
      : checkpoint?.execution_timeframe ?? "5m";
  const triggerTimeframe =
    typeof resumeSignature.trigger_timeframe === "string"
      ? resumeSignature.trigger_timeframe
      : checkpoint?.execution_timeframe ?? "5m";

  return {
    symbol: symbolScope,
    symbolScope,
    symbols,
    activeSymbol,
    executionTimeframe: checkpoint?.execution_timeframe ?? "5m",
    clockTimeframe,
    triggerTimeframe,
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
    watchlistSize: symbols.length,
    symbolBreakdown,
    sessionBreakdown: buildBreakdown(trades, (trade) => trade.sessionName || "no session"),
    qualityBreakdown: buildBreakdown(
      trades,
      (trade) => trade.setupQualityLabel || "unlabeled quality",
    ),
    stateBreakdown: buildBreakdown(trades, (trade) => trade.marketState || "unknown state"),
    recommendedUniverse: [...RECOMMENDED_UNIVERSE],
    selectionPolicy: "scan many, rank by evidence, trade few under shared portfolio risk",
  };
}

function filterWindowTrades(
  trades: BacktestTrade[],
  symbol: string,
  windowStart: number,
  windowEnd: number,
): BacktestTrade[] {
  return trades.filter((trade) => {
    if (trade.symbol !== symbol) {
      return false;
    }
    const openedAt = utcMillis(trade.openedAt);
    const closedAt = utcMillis(trade.closedAt);
    return closedAt >= windowStart && openedAt <= windowEnd;
  });
}

function filterWindowGaps(
  gapWindows: GapWindow[],
  symbol: string,
  windowStart: number,
  windowEnd: number,
): GapWindow[] {
  return gapWindows.filter((gap) => {
    if (gap.symbol !== symbol) {
      return false;
    }
    const gapStart = utcMillis(gap.missingStart);
    const gapEnd = utcMillis(gap.missingEnd);
    return gapEnd >= windowStart && gapStart <= windowEnd;
  });
}

export async function loadBacktestSnapshot(selectedSymbol?: string | null): Promise<BacktestSnapshot> {
  const repoRoot = resolveRepoRoot();
  const checkpoint = await readLatestCheckpoint(repoRoot);
  const symbols = parseScopeSymbols(checkpoint);
  const requestedSymbol = selectedSymbol?.trim().toUpperCase() ?? "";
  const activeSymbol = symbols.includes(requestedSymbol)
    ? requestedSymbol
    : symbols[0] ?? "BTCUSDT";

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
  const summary = buildSummary(checkpoint, trades, equityRows, gapWindows, symbols, activeSymbol);

  const executionTimeframe = summary.executionTimeframe;
  const clockTimeframe = summary.clockTimeframe;
  const simulatedTime = equityRows.at(-1)?.time ?? null;
  const symbolFiles = await Promise.all(
    symbols.map(async (symbol) => ({
      symbol,
      executionFilePath: await findPriceFile(
        repoRoot,
        symbol,
        executionTimeframe,
        summary.startDate,
        summary.endDate,
      ),
      clockFilePath:
        clockTimeframe === executionTimeframe
          ? await findPriceFile(
              repoRoot,
              symbol,
              executionTimeframe,
              summary.startDate,
              summary.endDate,
            )
          : await findPriceFile(
              repoRoot,
              symbol,
              clockTimeframe,
              summary.startDate,
              summary.endDate,
            ),
    })),
  );
  const activePriceFile =
    symbolFiles.find((entry) => entry.symbol === activeSymbol)?.executionFilePath ?? null;
  const clockCounts = await Promise.all(
    symbolFiles.map(async ({ symbol, clockFilePath }) => ({
      symbol,
      rows: clockFilePath ? await countDataRows(clockFilePath) : 0,
    })),
  );
  const executionCounts = await Promise.all(
    symbolFiles.map(async ({ symbol, executionFilePath }) => ({
      symbol,
      rows: executionFilePath ? await countDataRows(executionFilePath) : 0,
    })),
  );
  const totalClockRows = clockCounts.reduce((sum, entry) => sum + entry.rows, 0);
  const focusExecutionRows =
    executionCounts.find((entry) => entry.symbol === activeSymbol)?.rows ?? 0;
  const candles = await readPriceWindow(activePriceFile, simulatedTime);
  const windowStart = candles.length ? utcMillis(candles[0].time) : 0;
  const windowEnd = candles.length ? utcMillis(candles.at(-1)!.time) : 0;
  const windowTrades = candles.length ? filterWindowTrades(trades, activeSymbol, windowStart, windowEnd) : [];
  const windowGapWindows = candles.length ? filterWindowGaps(gapWindows, activeSymbol, windowStart, windowEnd) : [];
  const recentTrades = trades.slice(-80).reverse();

  const anomalies: string[] = [];
  if (!activePriceFile) {
    anomalies.push(
      `No resampled execution file found for ${activeSymbol} in the active backtest range.`,
    );
  }
  const missingClockFiles = symbolFiles
    .filter((entry) => !entry.clockFilePath)
    .map((entry) => `${entry.symbol}:${clockTimeframe}`);
  if (missingClockFiles.length > 0) {
    anomalies.push(
      `Clock-timeframe history is missing for ${missingClockFiles.join(", ")}. Progress telemetry may be incomplete.`,
    );
  }
  if (symbols.length > 1) {
    anomalies.push(
      `Watchlist backtest active across ${symbols.length} symbols. Portfolio equity is aggregate; chart focus is ${activeSymbol}.`,
    );
  }
  if (clockTimeframe !== executionTimeframe) {
    anomalies.push(
      `Progress now tracks ${clockTimeframe} clock candles while chart structure stays on ${executionTimeframe}. Trigger validation happens on ${summary.triggerTimeframe}.`,
    );
  }
  if (gapWindows.length > 0) {
    anomalies.push(
      `${gapWindows.length} historical outage windows are being guarded by the gap-aware backtest.`,
    );
  }
  if (trades.length === 0) {
    anomalies.push("No closed trades recorded yet in the current output set.");
  }
  const missingRecommended = RECOMMENDED_UNIVERSE.filter((symbol) => !symbols.includes(symbol));
  if (missingRecommended.length > 0) {
    anomalies.push(
      `Current scope does not include the full diversified research universe. Missing: ${missingRecommended.join(", ")}.`,
    );
  }

  return {
    asOf: new Date().toISOString(),
    progress: {
      nextIndex: asNumber(checkpoint?.next_index),
      totalClockRows,
      focusExecutionRows,
      progressPct: totalClockRows ? asNumber(checkpoint?.next_index) / totalClockRows : 0,
      simulatedTime,
      checkpointUpdatedAt: checkpoint?.updated_at ?? null,
      status: deriveStatus(checkpoint),
    },
    summary,
    candles,
    equity: equityRows,
    recentTrades,
    windowTrades,
    gapWindows,
    windowGapWindows,
    latestTrade: trades.at(-1) ?? null,
    anomalies,
  };
}
