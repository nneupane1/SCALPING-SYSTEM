import type { CandlePoint, PositionView, SignalView } from "../lib/types";

type TradingChartProps = {
  candles: CandlePoint[];
  signal: SignalView | null;
  position: PositionView | null;
};

export function TradingChart({ candles, signal, position }: TradingChartProps) {
  const min = Math.min(...candles.map((candle) => candle.low));
  const max = Math.max(...candles.map((candle) => candle.high));
  const spread = Math.max(max - min, 1);

  return (
    <section className="panel chart">
      <div className="panelHeader">
        <div>
          <h3>Structure View</h3>
          <div className="subtle">Closed-candle map of the active sequence.</div>
        </div>
        <div className="pill">{signal ? `Signal ${signal.side}` : "No Signal"}</div>
      </div>
      <div className="chartStage">
        <div className="chartBars">
          {candles.map((candle) => {
            const height = ((candle.close - min) / spread) * 100;
            const className = candle.close >= candle.open ? "chartBar" : "chartBar down";
            return (
              <div
                key={candle.time}
                className={className}
                style={{ height: `${Math.max(12, height)}%` }}
                title={`${candle.time} O:${candle.open} H:${candle.high} L:${candle.low} C:${candle.close}`}
              />
            );
          })}
        </div>
      </div>
      <div className="metricGrid">
        <div className="metricCard">
          <span className="metricLabel">Entry</span>
          <div className="metricValue">{signal ? signal.entryPrice.toFixed(0) : "-"}</div>
        </div>
        <div className="metricCard">
          <span className="metricLabel">Stop</span>
          <div className="metricValue">{signal ? signal.stopPrice.toFixed(0) : "-"}</div>
        </div>
        <div className="metricCard">
          <span className="metricLabel">Target</span>
          <div className="metricValue">{signal ? signal.targetPrice.toFixed(0) : "-"}</div>
        </div>
        <div className="metricCard">
          <span className="metricLabel">Runner</span>
          <div className="metricValue">
            {position ? `${position.remainingQuantity.toFixed(2)} left` : "Flat"}
          </div>
        </div>
      </div>
    </section>
  );
}

