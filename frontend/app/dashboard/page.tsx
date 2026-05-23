import { Heatmap } from "../../components/Heatmap";
import { OrderPanel } from "../../components/OrderPanel";
import { ReasoningPanel } from "../../components/ReasoningPanel";
import { StatsPanel } from "../../components/StatsPanel";
import { TradeStream } from "../../components/TradeStream";
import { TradingChart } from "../../components/TradingChart";
import { mockDashboardSnapshot } from "../../lib/mock-data";

export default function DashboardPage() {
  const snapshot = mockDashboardSnapshot;

  return (
    <main className="shell stack">
      <section className="hero">
        <span className="pill">
          {snapshot.mode} mode | {snapshot.symbol} | {snapshot.timeframe}
        </span>
        <h1>Momentum, pullback, and resumption on one screen.</h1>
        <p className="subtle">
          The chart shows the sequence. The side panels explain why the system
          entered, where it is wrong, and what the distribution is doing today.
        </p>
      </section>
      <section className="grid three">
        <TradingChart
          candles={snapshot.candles}
          signal={snapshot.signal}
          position={snapshot.position}
        />
        <StatsPanel portfolio={snapshot.portfolio} />
        <OrderPanel signal={snapshot.signal} position={snapshot.position} />
      </section>
      <section className="grid two">
        <ReasoningPanel lines={snapshot.reasoning} />
        <TradeStream items={snapshot.tradeFeed} />
      </section>
      <section className="grid two">
        <Heatmap cells={snapshot.heatmap} />
        <section className="panel">
          <div className="panelHeader">
            <div>
              <h3>Operator Note</h3>
              <div className="subtle">Targets are business goals, not guaranteed outputs.</div>
            </div>
          </div>
          <div className="list">
            <div className="listRow">
              <strong>Trade Frequency</strong>
              <div className="subtle">Targeting 10 to 15 trades daily requires strict filtering, not overtrading.</div>
            </div>
            <div className="listRow">
              <strong>Profit Objective</strong>
              <div className="subtle">
                €300 to €500 daily is a planning target. The code should optimize process quality and
                auditability, not promise fixed income from a noisy market.
              </div>
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}

