import type { PortfolioView } from "../lib/types";

type StatsPanelProps = {
  portfolio: PortfolioView;
};

export function StatsPanel({ portfolio }: StatsPanelProps) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <h3>Session Metrics</h3>
          <div className="subtle">The system should be judged by distribution, not one trade.</div>
        </div>
      </div>
      <div className="metricGrid">
        <div className="metricCard">
          <span className="metricLabel">Equity</span>
          <div className="metricValue">€{portfolio.currentEquity.toFixed(0)}</div>
        </div>
        <div className="metricCard">
          <span className="metricLabel">Realized</span>
          <div className={`metricValue ${portfolio.realizedPnl >= 0 ? "valueUp" : "valueDown"}`}>
            €{portfolio.realizedPnl.toFixed(0)}
          </div>
        </div>
        <div className="metricCard">
          <span className="metricLabel">Win Rate</span>
          <div className="metricValue">{(portfolio.winRate * 100).toFixed(1)}%</div>
        </div>
        <div className="metricCard">
          <span className="metricLabel">Average R</span>
          <div className="metricValue">{portfolio.avgR.toFixed(2)}R</div>
        </div>
        <div className="metricCard">
          <span className="metricLabel">Trades</span>
          <div className="metricValue">{portfolio.tradeCount}</div>
        </div>
        <div className="metricCard">
          <span className="metricLabel">Drawdown</span>
          <div className={`metricValue ${portfolio.drawdown >= 0 ? "valueUp" : "valueDown"}`}>
            €{portfolio.drawdown.toFixed(0)}
          </div>
        </div>
      </div>
    </section>
  );
}

