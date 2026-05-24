export type BacktestStatus = "idle" | "running" | "paused" | "completed";

export type BacktestProgress = {
  nextIndex: number;
  totalRows: number;
  progressPct: number;
  simulatedTime: string | null;
  checkpointUpdatedAt: string | null;
  status: BacktestStatus;
};

export type BacktestCandle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type BacktestEquityPoint = {
  time: string;
  equity: number;
};

export type BacktestTrade = {
  symbol: string;
  timeframe: string;
  side: "long" | "short";
  openedAt: string;
  closedAt: string;
  entryPrice: number;
  exitPrice: number;
  initialQuantity: number;
  realizedPnl: number;
  realizedR: number;
  reason: string;
  notes: string;
  tags: string[];
  marketState: string;
  contextAlignment: string;
  sessionName: string;
  sessionPhase: string;
  setupQualityLabel: string;
  setupQualityScore: number;
  dayFeedbackReason: string;
  dayTradeCount: number;
  barsHeld: number;
  bestRMultiple: number;
  worstRMultiple: number;
  firstTargetHitAfterBars: number | null;
  followThroughState: string;
};

export type GapWindow = {
  gapId: number;
  previousBaseTimestamp: string;
  nextBaseTimestamp: string;
  missingStart: string;
  missingEnd: string;
  missingMinutes: number;
  previousExecutionIndex: number | null;
  previousExecutionClose: string | null;
  nextExecutionIndex: number | null;
  nextExecutionOpen: string | null;
  nextExecutionClose: string | null;
  missingExecutionBars: number;
  blockedEntryStartIndex: number | null;
  blockedEntryEndIndex: number | null;
  forceFlatBeforeGap: boolean;
  postGapCooldownBars: number;
};

export type BreakdownStat = {
  label: string;
  trades: number;
  winRate: number;
  avgR: number;
  totalR: number;
};

export type BacktestSummaryView = {
  symbol: string;
  executionTimeframe: string;
  startDate: string | null;
  endDate: string | null;
  startingEquity: number;
  currentEquity: number;
  realizedPnl: number;
  closedTrades: number;
  winRate: number;
  avgR: number;
  bestTradeR: number;
  worstTradeR: number;
  maxDrawdown: number;
  gapWindows: number;
  sessionBreakdown: BreakdownStat[];
  qualityBreakdown: BreakdownStat[];
  stateBreakdown: BreakdownStat[];
};

export type BacktestSnapshot = {
  asOf: string;
  progress: BacktestProgress;
  summary: BacktestSummaryView;
  candles: BacktestCandle[];
  equity: BacktestEquityPoint[];
  recentTrades: BacktestTrade[];
  windowTrades: BacktestTrade[];
  gapWindows: GapWindow[];
  windowGapWindows: GapWindow[];
  latestTrade: BacktestTrade | null;
  anomalies: string[];
};
