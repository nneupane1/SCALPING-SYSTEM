"use client";

import { startTransition, useDeferredValue, useEffect, useState } from "react";

import { ModeSwitchRail } from "../navigation/ModeSwitchRail";
import { TradingChart } from "../TradingChart";
import { PnlLedger } from "../trades/PnlLedger";
import type { RuntimeMode, RuntimeSnapshot } from "../../lib/runtime-types";

type RuntimeOpsBoardProps = {
  initialSnapshot: RuntimeSnapshot;
};

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

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function longDate(value: string | null | undefined): string {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "UTC",
  });
}

function statusLabel(status: RuntimeSnapshot["status"]): string {
  if (status === "running") return "Running";
  if (status === "completed") return "Completed";
  if (status === "paused") return "Paused";
  return "Idle";
}

export function RuntimeOpsBoard({ initialSnapshot }: RuntimeOpsBoardProps) {
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const deferredSnapshot = useDeferredValue(snapshot);

  useEffect(() => {
    if (!autoRefresh) {
      return;
    }

    let cancelled = false;
    const refresh = async () => {
      setLoading(true);
      try {
        const response = await fetch(`/api/runtime/snapshot?mode=${snapshot.mode}`, {
          cache: "no-store",
        });
        if (!response.ok) {
          throw new Error(`Runtime snapshot request failed with ${response.status}`);
        }
        const next = (await response.json()) as RuntimeSnapshot;
        if (!cancelled) {
          startTransition(() => {
            setSnapshot(next);
          });
          setError(null);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Runtime refresh failure");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    const timer = window.setInterval(refresh, 7000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [autoRefresh, snapshot.mode]);

  const active = deferredSnapshot;

  return (
    <main className="shell stack btShell">
      <ModeSwitchRail />

      <section className="btHero">
        <div className="btHeroCopy">
          <div className="btEyebrow">{active.modeProfile.label}</div>
          <h1>One operating board, different execution truth.</h1>
          <p>
            This view reads the active forward runtime artifacts for {active.mode}. Market data,
            validation posture, and execution semantics all shift with the mode, but the desk
            surface stays consistent.
          </p>
        </div>
        <div className="btHeroMeta">
          <div className="btHeroMetaLine">
            <span>Status</span>
            <strong>{statusLabel(active.status)}</strong>
          </div>
          <div className="btHeroMetaLine">
            <span>Checkpoint</span>
            <strong>{longDate(active.checkpointUpdatedAt)}</strong>
          </div>
          <div className="btHeroMetaLine">
            <span>Latest execution close</span>
            <strong>{longDate(active.latestExecutionClose)}</strong>
          </div>
          <div className="btToggleRow">
            <button
              type="button"
              className={`btToggle ${autoRefresh ? "is-on" : ""}`}
              onClick={() => setAutoRefresh((value) => !value)}
            >
              {autoRefresh ? "Auto refresh on" : "Auto refresh off"}
            </button>
            <span className="subtle">{loading ? "Syncing runtime..." : "Polling every 7s"}</span>
          </div>
        </div>
        <div className="btProgressDeck">
          <div className="btProgressCopy">
            <span>{active.symbol}</span>
            <strong>
              {active.executionTimeframe} execution | {active.baseTimeframe} canonical feed
            </strong>
          </div>
          <div className="btProgressBar">
            <div
              className="btProgressFill"
              style={{
                width: active.status === "running" ? "100%" : active.status === "paused" ? "55%" : "16%",
              }}
            />
          </div>
          <div className="btProgressCopy btProgressCopy-bottom">
            <span>{active.modeProfile.executionModel}</span>
            <strong>{money(active.currentEquity)}</strong>
          </div>
        </div>
      </section>

      <section className="btMetricDeck">
        <article className={`btMetric ${active.realizedPnl >= 0 ? "btMetric-up" : "btMetric-down"}`}>
          <span className="btMetricLabel">Current equity</span>
          <strong className="btMetricValue">{money(active.currentEquity)}</strong>
          <span className="btMetricDetail">Start {money(active.startingEquity)}</span>
        </article>
        <article className={`btMetric ${active.realizedPnl >= 0 ? "btMetric-up" : "btMetric-down"}`}>
          <span className="btMetricLabel">Realized pnl</span>
          <strong className="btMetricValue">{money(active.realizedPnl)}</strong>
          <span className="btMetricDetail">{active.closedTrades} closed trades</span>
        </article>
        <article className="btMetric btMetric-signal">
          <span className="btMetricLabel">Win rate</span>
          <strong className="btMetricValue">{percent(active.winRate)}</strong>
          <span className="btMetricDetail">Avg {number(active.avgR)}R</span>
        </article>
        <article className="btMetric btMetric-down">
          <span className="btMetricLabel">Max drawdown</span>
          <strong className="btMetricValue">{money(active.maxDrawdown)}</strong>
          <span className="btMetricDetail">{active.modeProfile.validationFocus}</span>
        </article>
        <article className="btMetric">
          <span className="btMetricLabel">Data priority</span>
          <strong className="btMetricValue">{active.mode === "live" ? "L1" : "L2"}</strong>
          <span className="btMetricDetail">{active.modeProfile.dataPriority}</span>
        </article>
      </section>

      {error ? <section className="btErrorBanner">{error}</section> : null}

      <section className="btGridMain">
        <TradingChart
          candles={active.candles}
          signal={null}
          position={active.activePosition}
          symbol={active.symbol}
          timeframe={active.executionTimeframe}
          equityPoints={active.equity}
          startingEquity={active.startingEquity}
        />

        <section className="btSideStack">
          <section className="btPanel btStatementPanel">
            <div className="btPanelHeader">
              <div>
                <h3>Mode semantics</h3>
                <p>Why this mode exists and what it should be trusted to validate.</p>
              </div>
            </div>
            <div className="btStatementGrid">
              <div className="btStatementCard">
                <span>Execution model</span>
                <strong>{active.modeProfile.executionModel}</strong>
              </div>
              <div className="btStatementCard">
                <span>Data priority</span>
                <strong>{active.modeProfile.dataPriority}</strong>
              </div>
              <div className="btStatementCard">
                <span>Validation focus</span>
                <strong>{active.modeProfile.validationFocus}</strong>
              </div>
              <div className="btStatementCard">
                <span>Active position</span>
                <strong>
                  {active.activePosition
                    ? `${active.activePosition.side.toUpperCase()} ${number(active.activePosition.remainingQuantity, 3)}`
                    : "Flat"}
                </strong>
              </div>
            </div>
          </section>

          <section className="btPanel">
            <div className="btPanelHeader">
              <div>
                <h3>Recent equity path</h3>
                <p>Latest forward checkpoints written by the active runtime.</p>
              </div>
            </div>
            <div className="btTable">
              {active.equity.slice(-12).reverse().map((point) => (
                <div className="btTableRow" key={point.time}>
                  <div className="btTableTitle">
                    <strong>{longDate(point.time)}</strong>
                    <span>{money(point.equity)}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </section>
      </section>

      <PnlLedger
        trades={active.recentTrades}
        title={`${active.modeProfile.label} PnL Ledger`}
        subtitle="Closed-trade audit stream from the active forward runtime."
      />
    </main>
  );
}
