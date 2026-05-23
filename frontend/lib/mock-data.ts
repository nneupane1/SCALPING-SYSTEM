import type { DashboardSnapshot } from "./types";

export const mockDashboardSnapshot: DashboardSnapshot = {
  mode: "paper",
  symbol: "BTCUSDT",
  timeframe: "5m",
  candles: [
    { time: "09:00", open: 66210, high: 66242, low: 66194, close: 66234 },
    { time: "09:05", open: 66234, high: 66286, low: 66222, close: 66278 },
    { time: "09:10", open: 66278, high: 66410, low: 66270, close: 66398 },
    { time: "09:15", open: 66398, high: 66405, low: 66332, close: 66344 },
    { time: "09:20", open: 66344, high: 66452, low: 66336, close: 66436 }
  ],
  signal: {
    side: "long",
    entryPrice: 66436,
    stopPrice: 66324,
    targetPrice: 66548,
    confidence: 0.82,
    reasons: [
      "Momentum candle expanded above body threshold",
      "Pullback stayed shallow and orderly",
      "Trigger candle closed through local structure"
    ]
  },
  position: {
    symbol: "BTCUSDT",
    side: "long",
    entryPrice: 66436,
    stopPrice: 66436,
    remainingQuantity: 0.64,
    firstPartialTaken: true
  },
  portfolio: {
    currentEquity: 20436,
    realizedPnl: 436,
    drawdown: -112,
    winRate: 0.58,
    tradeCount: 12,
    avgR: 0.71
  },
  tradeFeed: [
    {
      id: "trade-001",
      side: "buy",
      price: 66595,
      pnl: 0,
      timestamp: "10:00",
      note: "Breakout after orderly pullback"
    },
    {
      id: "trade-002",
      side: "sell",
      price: 66785,
      pnl: 96,
      timestamp: "10:09",
      note: "First partial at +1R"
    }
  ],
  reasoning: [
    { label: "Momentum", value: "Valid expansion", status: "pass" },
    { label: "Pullback", value: "Shallow and compressive", status: "pass" },
    { label: "Trigger", value: "Closed above pullback high", status: "pass" },
    { label: "Risk", value: "Stop at pullback low plus buffer", status: "pass" },
    { label: "Mode", value: "Paper execution only", status: "watch" }
  ],
  heatmap: [
    { label: "09:00", value: 0.3 },
    { label: "10:00", value: 0.8 },
    { label: "11:00", value: 0.5 },
    { label: "14:30", value: 1.0 },
    { label: "15:30", value: 0.7 },
    { label: "16:30", value: 0.4 }
  ]
};
