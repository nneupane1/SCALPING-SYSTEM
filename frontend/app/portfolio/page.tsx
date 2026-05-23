import { StatsPanel } from "../../components/StatsPanel";
import { TradeStream } from "../../components/TradeStream";
import { mockDashboardSnapshot } from "../../lib/mock-data";

export default function PortfolioPage() {
  const snapshot = mockDashboardSnapshot;

  return (
    <main className="shell stack">
      <section className="hero">
        <span className="pill">Portfolio</span>
        <h1>Outcomes belong in a distribution, not in isolated anecdotes.</h1>
        <p className="subtle">
          The portfolio view is where execution quality and repeatability become measurable.
        </p>
      </section>
      <section className="grid two">
        <StatsPanel portfolio={snapshot.portfolio} />
        <TradeStream items={snapshot.tradeFeed} />
      </section>
    </main>
  );
}

