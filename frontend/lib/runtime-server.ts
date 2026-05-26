import "server-only";

import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";

import type { BacktestEquityPoint, BacktestTrade } from "./backtest-types";
import type { PositionView, CandlePoint } from "./types";
import type { RuntimeMode, RuntimeSnapshot, RuntimeStatus } from "./runtime-types";

type CsvRow = Record<string, string>;
type RuntimeCheckpoint = {
  completed?: boolean;
  execution_timeframe?: string;
  latest_execution_close?: string;
  mode?: string;
  portfolio?: {
    active_position?: Record<string, unknown> | null;
    closed_trades?: Record<string, unknown>[];
    current_equity?: number;
    loss_count?: number;
    peak_equity?: number;
    realized_pnl?: number;
    win_count?: number;
  };
  resume_signature?: {
    base_timeframe?: string;
    execution_timeframe?: string;
    mode?: string;
    starting_equity?: number;
    symbol?: string;
  };
  symbol?: string;
  updated_at?: string;
};

type RuntimeBaseRow = CandlePoint & { volume: number; timeMs: number };

function resolveRepoRoot(): string {
  const candidates = [
    process.cwd(),
    path.resolve(process.cwd(), ".."),
    path.resolve(process.cwd(), "../.."),
  ];
  for (const candidate of candidates) {
    if (
      fs.existsSync(path.join(candidate, "frontend")) &&
      fs.existsSync(path.join(candidate, "paper")) &&
      fs.existsSync(path.join(candidate, "live"))
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

function asNumber(value: string | number | undefined, fallback = 0): number {
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

async function readCsvRows(filePath: string): Promise<CsvRow[]> {
  if (!fs.existsSync(filePath)) {
    return [];
  }
  const content = await fs.promises.readFile(filePath, "utf8");
  const lines = content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  if (lines.length === 0) {
    return [];
  }
  const header = parseCsvLine(lines[0]);
  return lines.slice(1).map((line) => {
    const values = parseCsvLine(line);
    const row: CsvRow = {};
    for (let index = 0; index < header.length; index += 1) {
      row[header[index]] = values[index] ?? "";
    }
    return row;
  });
}

async function readLatestCheckpoint(repoRoot: string, mode: RuntimeMode): Promise<RuntimeCheckpoint | null> {
  const checkpointDir = path.join(repoRoot, mode, "output", "_checkpoints");
  if (!fs.existsSync(checkpointDir)) {
    return null;
  }

  const entries = await fs.promises.readdir(checkpointDir);
  const candidates = await Promise.all(
    entries
      .filter((entry) => entry.endsWith(".json"))
      .map(async (entry) => {
        const fullPath = path.join(checkpointDir, entry);
        const stat = await fs.promises.stat(fullPath);
        return { fullPath, mtimeMs: stat.mtimeMs };
      }),
  );
  const latest = candidates.sort((left, right) => right.mtimeMs - left.mtimeMs)[0];
  if (!latest) {
    return null;
  }
  return JSON.parse(await fs.promises.readFile(latest.fullPath, "utf8")) as RuntimeCheckpoint;
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
    tags: row.tags?.split("|").filter(Boolean) ?? [],
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
    firstTargetHitAfterBars: row.first_target_hit_after_bars ? asNumber(row.first_target_hit_after_bars) : null,
    followThroughState: row.follow_through_state,
  }));
}

function parseEquityRows(rows: CsvRow[], limit = 400): BacktestEquityPoint[] {
  return rows.slice(-limit).map((row) => ({
    time: row.timestamp,
    equity: asNumber(row.equity),
  }));
}

async function readRecentRuntimeBaseRows(
  repoRoot: string,
  symbol: string,
  baseTimeframe: string,
  limit = 1800,
): Promise<RuntimeBaseRow[]> {
  const filePath = path.join(
    repoRoot,
    "data_storage",
    symbol,
    baseTimeframe,
    `${symbol}_${baseTimeframe}_live_runtime.csv`,
  );
  if (!fs.existsSync(filePath)) {
    return [];
  }
  const stream = fs.createReadStream(filePath, { encoding: "utf8" });
  const reader = readline.createInterface({ input: stream, crlfDelay: Infinity });
  const rows: RuntimeBaseRow[] = [];
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
    rows.push({
      time,
      open: asNumber(open),
      high: asNumber(high),
      low: asNumber(low),
      close: asNumber(close),
      volume: asNumber(volume),
      timeMs: utcMillis(time),
    });
    if (rows.length > limit) {
      rows.shift();
    }
  }
  return rows;
}

function timeframeToMinutes(timeframe: string): number {
  if (!timeframe.endsWith("m")) {
    return 1;
  }
  const value = Number(timeframe.slice(0, -1));
  return Number.isFinite(value) && value > 0 ? value : 1;
}

function resampleRuntimeCandles(rows: RuntimeBaseRow[], timeframe: string): CandlePoint[] {
  const intervalMinutes = timeframeToMinutes(timeframe);
  if (intervalMinutes <= 1) {
    return rows.map((row) => ({
      time: row.time.includes("T") ? row.time : `${row.time.replace(" ", "T")}Z`,
      open: row.open,
      high: row.high,
      low: row.low,
      close: row.close,
      volume: row.volume,
    }));
  }

  const intervalMs = intervalMinutes * 60 * 1000;
  const buckets: CandlePoint[] = [];
  let active:
    | {
        bucketStartMs: number;
        open: number;
        high: number;
        low: number;
        close: number;
        volume: number;
        count: number;
      }
    | null = null;

  for (const row of rows) {
    const bucketStartMs = Math.floor(row.timeMs / intervalMs) * intervalMs;
    if (!active || active.bucketStartMs !== bucketStartMs) {
      if (active && active.count === intervalMinutes) {
        buckets.push({
          time: new Date(active.bucketStartMs + intervalMs).toISOString(),
          open: active.open,
          high: active.high,
          low: active.low,
          close: active.close,
          volume: active.volume,
        });
      }
      active = {
        bucketStartMs,
        open: row.open,
        high: row.high,
        low: row.low,
        close: row.close,
        volume: row.volume,
        count: 1,
      };
      continue;
    }
    active.high = Math.max(active.high, row.high);
    active.low = Math.min(active.low, row.low);
    active.close = row.close;
    active.volume += row.volume;
    active.count += 1;
  }

  if (active && active.count === intervalMinutes) {
      buckets.push({
        time: new Date(active.bucketStartMs + intervalMs).toISOString(),
        open: active.open,
        high: active.high,
        low: active.low,
        close: active.close,
        volume: active.volume,
      });
  }

  return buckets;
}

function deriveStatus(checkpoint: RuntimeCheckpoint | null): RuntimeStatus {
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

function computeMaxDrawdown(equityRows: BacktestEquityPoint[], startingEquity: number): number {
  let peak = startingEquity;
  let maxDrawdown = 0;
  for (const point of equityRows) {
    peak = Math.max(peak, point.equity);
    maxDrawdown = Math.min(maxDrawdown, point.equity - peak);
  }
  return maxDrawdown;
}

function modeProfile(mode: RuntimeMode) {
  if (mode === "live") {
    return {
      label: "Live Forward",
      dataPriority: "Realtime websocket + user stream reconciliation",
      executionModel: "Exchange-aware routing and broker state",
      validationFocus: "Actual runtime integrity and execution quality",
    };
  }
  return {
    label: "Paper Forward",
    dataPriority: "Realtime market feed with simulated fills",
    executionModel: "Strategy and risk path without broker risk",
    validationFocus: "Forward behavior and operator discipline",
  };
}

function parseActivePosition(payload: Record<string, unknown> | null | undefined): PositionView | null {
  if (!payload) {
    return null;
  }
  return {
    symbol: String(payload.symbol ?? "BTCUSDT"),
    side: String(payload.side ?? "long") === "short" ? "short" : "long",
    entryPrice: Number(payload.entry_price ?? 0),
    stopPrice: Number(payload.stop_price ?? 0),
    remainingQuantity: Number(payload.remaining_quantity ?? 0),
    firstPartialTaken: Boolean(payload.first_partial_taken ?? false),
  };
}

export async function loadRuntimeSnapshot(mode: RuntimeMode): Promise<RuntimeSnapshot> {
  const repoRoot = resolveRepoRoot();
  const checkpoint = await readLatestCheckpoint(repoRoot, mode);
  const symbol = String(checkpoint?.symbol ?? checkpoint?.resume_signature?.symbol ?? "BTCUSDT");
  const executionTimeframe = String(
    checkpoint?.execution_timeframe ?? checkpoint?.resume_signature?.execution_timeframe ?? "5m",
  );
  const baseTimeframe = String(checkpoint?.resume_signature?.base_timeframe ?? "1m");
  const outputDir = path.join(repoRoot, mode, "output");

  const [tradeRowsRaw, equityRowsRaw, baseRows] = await Promise.all([
    readCsvRows(path.join(outputDir, "trades.csv")),
    readCsvRows(path.join(outputDir, "equity.csv")),
    readRecentRuntimeBaseRows(repoRoot, symbol, baseTimeframe),
  ]);

  const allTrades = parseTradeRows(tradeRowsRaw);
  const recentTrades = allTrades.slice(-50).reverse();
  const equity = parseEquityRows(equityRowsRaw);
  const startingEquity = asNumber(checkpoint?.resume_signature?.starting_equity, 25_000);
  const currentEquity =
    equity.at(-1)?.equity ?? asNumber(checkpoint?.portfolio?.current_equity, startingEquity);
  const realizedPnl =
    currentEquity - startingEquity ||
    asNumber(checkpoint?.portfolio?.realized_pnl, 0);
  const candles = resampleRuntimeCandles(baseRows, executionTimeframe);
  const closedTrades = allTrades.length;
  const wins = allTrades.filter((trade) => trade.realizedR > 0).length;
  const totalR = allTrades.reduce((sum, trade) => sum + trade.realizedR, 0);

  return {
    asOf: new Date().toISOString(),
    mode,
    status: deriveStatus(checkpoint),
    symbol,
    executionTimeframe,
    baseTimeframe,
    checkpointUpdatedAt: checkpoint?.updated_at ?? null,
    latestExecutionClose: checkpoint?.latest_execution_close ?? null,
    startingEquity,
    currentEquity,
    realizedPnl,
    closedTrades,
    winRate: closedTrades ? wins / closedTrades : 0,
    avgR: closedTrades ? totalR / closedTrades : 0,
    maxDrawdown: computeMaxDrawdown(equity, startingEquity),
    candles,
    equity,
    recentTrades,
    activePosition: parseActivePosition(checkpoint?.portfolio?.active_position),
    modeProfile: modeProfile(mode),
  };
}
