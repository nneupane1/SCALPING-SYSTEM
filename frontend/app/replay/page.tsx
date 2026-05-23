import { ReasoningPanel } from "../../components/ReasoningPanel";
import { TradingChart } from "../../components/TradingChart";
import { mockDashboardSnapshot } from "../../lib/mock-data";

export default function ReplayPage() {
  const snapshot = { ...mockDashboardSnapshot, mode: "replay" as const };

  return (
    <main className="shell stack">
      <section className="hero">
        <span className="pill">Replay mode</span>
        <h1>One candle at a time, with the same logic path as live mode.</h1>
        <p className="subtle">
          Replay should not invent a different strategy. It should slow the same
          engine down enough that you can inspect every transition.
        </p>
      </section>
      <section className="grid two">
        <TradingChart
          candles={snapshot.candles}
          signal={snapshot.signal}
          position={snapshot.position}
        />
        <ReasoningPanel lines={snapshot.reasoning} />
      </section>
    </main>
  );
}

