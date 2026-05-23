import type { TradeFeedItem } from "../lib/types";

type TradeStreamProps = {
  items: TradeFeedItem[];
};

export function TradeStream({ items }: TradeStreamProps) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div>
          <h3>Trade Stream</h3>
          <div className="subtle">Every action should map back to a specific structural event.</div>
        </div>
      </div>
      <div className="list">
        {items.map((item) => (
          <div key={item.id} className="listRow">
            <div className="rowTitle">
              <strong>{item.side.toUpperCase()} BTC</strong>
              <span className={item.pnl >= 0 ? "valueUp" : "valueDown"}>
                {item.pnl >= 0 ? "+" : ""}€{item.pnl.toFixed(0)}
              </span>
            </div>
            <div className="subtle">
              {item.timestamp} at {item.price.toFixed(0)}
            </div>
            <div>{item.note}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

