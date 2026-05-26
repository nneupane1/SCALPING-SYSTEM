"use client";

import type { BacktestTrade } from "../../lib/backtest-types";

type PnlLedgerProps = {
  trades: BacktestTrade[];
  title?: string;
  subtitle?: string;
};

function shortTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
}

function money(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(value);
}

function number(value: number, digits = 2): string {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

export function PnlLedger({
  trades,
  title = "PnL Ledger",
  subtitle = "Closed-trade details with context, quality, and realized outcome.",
}: PnlLedgerProps) {
  return (
    <section className="btPanel">
      <div className="btPanelHeader">
        <div>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
      </div>

      {trades.length === 0 ? (
        <div className="btEmptyState">No closed trades recorded yet.</div>
      ) : (
        <div className="ledgerWrap">
          <div className="ledgerTable">
            <div className="ledgerHead">
              <span>Closed</span>
              <span>Symbol</span>
              <span>Side</span>
              <span>Entry</span>
              <span>Exit</span>
              <span>PnL</span>
              <span>R</span>
              <span>Session</span>
              <span>State</span>
              <span>Quality</span>
              <span>Bars</span>
            </div>
            {trades.map((trade) => (
              <div
                className="ledgerRow"
                key={`${trade.symbol}-${trade.closedAt}-${trade.entryPrice}-${trade.exitPrice}`}
              >
                <span>{shortTime(trade.closedAt)}</span>
                <span>{trade.symbol}</span>
                <span>{trade.side.toUpperCase()}</span>
                <span>{number(trade.entryPrice)}</span>
                <span>{number(trade.exitPrice)}</span>
                <strong className={trade.realizedPnl >= 0 ? "valueUp" : "valueDown"}>
                  {money(trade.realizedPnl)}
                </strong>
                <strong className={trade.realizedR >= 0 ? "valueUp" : "valueDown"}>
                  {number(trade.realizedR)}R
                </strong>
                <span>{trade.sessionName || "--"}</span>
                <span>{trade.marketState || "--"}</span>
                <span>{trade.setupQualityLabel || "--"}</span>
                <span>{trade.barsHeld}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
