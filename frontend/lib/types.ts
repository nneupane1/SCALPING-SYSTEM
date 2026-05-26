export type CandlePoint = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
};

export type SignalView = {
  side: "long" | "short";
  entryPrice: number;
  stopPrice: number;
  targetPrice: number;
  confidence: number;
  reasons: string[];
};

export type PositionView = {
  symbol: string;
  side: "long" | "short";
  entryPrice: number;
  stopPrice: number;
  remainingQuantity: number;
  firstPartialTaken: boolean;
};

export type PortfolioView = {
  currentEquity: number;
  realizedPnl: number;
  drawdown: number;
  winRate: number;
  tradeCount: number;
  avgR: number;
};

export type TradeFeedItem = {
  id: string;
  side: "buy" | "sell";
  price: number;
  pnl: number;
  timestamp: string;
  note: string;
};

export type ReasoningLine = {
  label: string;
  value: string;
  status: "pass" | "watch" | "block";
};

export type HeatmapCell = {
  label: string;
  value: number;
};

export type DashboardSnapshot = {
  mode: "paper" | "live" | "replay";
  symbol: string;
  timeframe: string;
  candles: CandlePoint[];
  signal: SignalView | null;
  position: PositionView | null;
  portfolio: PortfolioView;
  tradeFeed: TradeFeedItem[];
  reasoning: ReasoningLine[];
  heatmap: HeatmapCell[];
};
