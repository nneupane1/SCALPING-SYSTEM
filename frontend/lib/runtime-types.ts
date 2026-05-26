import type { PositionView, CandlePoint } from "./types";
import type { BacktestEquityPoint, BacktestTrade } from "./backtest-types";

export type RuntimeMode = "paper" | "live";
export type RuntimeStatus = "idle" | "running" | "paused" | "completed";

export type RuntimeModeProfile = {
  label: string;
  dataPriority: string;
  executionModel: string;
  validationFocus: string;
};

export type RuntimeSnapshot = {
  asOf: string;
  mode: RuntimeMode;
  status: RuntimeStatus;
  symbol: string;
  executionTimeframe: string;
  baseTimeframe: string;
  checkpointUpdatedAt: string | null;
  latestExecutionClose: string | null;
  startingEquity: number;
  currentEquity: number;
  realizedPnl: number;
  closedTrades: number;
  winRate: number;
  avgR: number;
  maxDrawdown: number;
  candles: CandlePoint[];
  equity: BacktestEquityPoint[];
  recentTrades: BacktestTrade[];
  activePosition: PositionView | null;
  modeProfile: RuntimeModeProfile;
};
