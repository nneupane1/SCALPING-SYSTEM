import type { PositionView, SignalView } from "../lib/types";

type OrderPanelProps = {
  signal: SignalView | null;
  position: PositionView | null;
};

export function OrderPanel({ signal, position }: OrderPanelProps) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <h3>Execution State</h3>
          <div className="subtle">Entry, invalidation, and current trade permissions.</div>
        </div>
      </div>
      <div className="list">
        <div className="listRow">
          <div className="rowTitle">
            <strong>Signal</strong>
            <span className="pill">{signal ? signal.side : "flat"}</span>
          </div>
          <div className="subtle">
            {signal
              ? `Entry ${signal.entryPrice.toFixed(0)} | Stop ${signal.stopPrice.toFixed(0)}`
              : "No active setup"}
          </div>
        </div>
        <div className="listRow">
          <div className="rowTitle">
            <strong>Position</strong>
            <span>{position ? "Open" : "Closed"}</span>
          </div>
          <div className="subtle">
            {position
              ? `${position.symbol} ${position.side} with ${position.remainingQuantity.toFixed(2)} remaining`
              : "No active position"}
          </div>
        </div>
      </div>
    </section>
  );
}

