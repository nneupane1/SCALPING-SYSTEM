import type { CandlePoint, DashboardSnapshot } from "./types";

function buildMockCandles(): CandlePoint[] {
  const start = new Date("2026-05-23T07:00:00Z");
  const moves = [
    18, 22, 34, -16, 28, 14, -11, 19, 26, -8, 35, -24, -18, 12, 17, 29,
    -14, -7, 24, 16, -10, 31, 21, -12, -19, 15, 27, -9, 13, 18, -6, 22,
    33, -15, -8, 26, 18, -11, 14, 28, -13, 19, 17, -5, 24, 21, -9, 15,
  ];

  const candles: CandlePoint[] = [];
  let lastClose = 66_210;

  for (let index = 0; index < moves.length; index += 1) {
    const time = new Date(start.getTime() + index * 5 * 60 * 1_000).toISOString();
    const open = lastClose;
    const drift = moves[index];
    const close = open + drift;
    const wickUp = 10 + (index % 5) * 4;
    const wickDown = 8 + ((index + 2) % 4) * 5;
    const high = Math.max(open, close) + wickUp;
    const low = Math.min(open, close) - wickDown;
    const volume = 120 + Math.abs(drift) * 6 + (index % 7) * 18;
    candles.push({ time, open, high, low, close, volume });
    lastClose = close;
  }

  return candles;
}

const candles = buildMockCandles();
const latest = candles[candles.length - 1];

export const mockDashboardSnapshot: DashboardSnapshot = {
  mode: "paper",
  symbol: "BTCUSDT",
  timeframe: "5m",
  candles,
  signal: {
    side: "long",
    entryPrice: latest.close,
    stopPrice: latest.close - 112,
    targetPrice: latest.close + 128,
    confidence: 0.82,
    reasons: [
      "Momentum candle expanded above body threshold",
      "Pullback stayed shallow and orderly",
      "Trigger candle closed through local structure",
    ],
  },
  position: {
    symbol: "BTCUSDT",
    side: "long",
    entryPrice: latest.close,
    stopPrice: latest.close - 4,
    remainingQuantity: 0.64,
    firstPartialTaken: true,
  },
  portfolio: {
    currentEquity: 25_436,
    realizedPnl: 436,
    drawdown: -112,
    winRate: 0.58,
    tradeCount: 12,
    avgR: 0.71,
  },
  tradeFeed: [
    {
      id: "trade-001",
      side: "buy",
      price: latest.close + 44,
      pnl: 0,
      timestamp: "2026-05-23T10:00:00Z",
      note: "Breakout after orderly pullback",
    },
    {
      id: "trade-002",
      side: "sell",
      price: latest.close + 123,
      pnl: 96,
      timestamp: "2026-05-23T10:09:00Z",
      note: "First partial at +1R",
    },
  ],
  reasoning: [
    { label: "Momentum", value: "Valid expansion", status: "pass" },
    { label: "Pullback", value: "Shallow and compressive", status: "pass" },
    { label: "Trigger", value: "Closed above pullback high", status: "pass" },
    { label: "Risk", value: "Stop at pullback low plus buffer", status: "pass" },
    { label: "Mode", value: "Paper execution only", status: "watch" },
  ],
  heatmap: [
    { label: "09:00", value: 0.3 },
    { label: "10:00", value: 0.8 },
    { label: "11:00", value: 0.5 },
    { label: "14:30", value: 1.0 },
    { label: "15:30", value: 0.7 },
    { label: "16:30", value: 0.4 },
  ],
};
