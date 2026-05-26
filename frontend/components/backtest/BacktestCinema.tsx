"use client";

import {
  startTransition,
  useDeferredValue,
  useEffect,
  useState,
  type CSSProperties,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { TradingChart } from "../TradingChart";
import { ResearchCommandDeck } from "../research/ResearchCommandDeck";
import { ModeSwitchRail } from "../navigation/ModeSwitchRail";
import { PnlLedger } from "../trades/PnlLedger";
import type {
  BacktestSnapshot,
  BacktestStatus,
  BreakdownStat,
} from "../../lib/backtest-types";

type BacktestCinemaProps = {
  initialSnapshot: BacktestSnapshot;
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

function compact(value: number): string {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function utcMillis(value: string | null | undefined): number {
  if (!value) {
    return Number.NaN;
  }
  if (value.includes("T")) {
    if (/([+-]\d{2}:\d{2}|Z)$/.test(value)) {
      return new Date(value).getTime();
    }
    return new Date(`${value}Z`).getTime();
  }
  return new Date(`${value.replace(" ", "T")}Z`).getTime();
}

function shortTime(value: string | null | undefined): string {
  if (!value) {
    return "--";
  }
  const date = new Date(utcMillis(value));
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("en-GB", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
}

function longDate(value: string | null | undefined): string {
  if (!value) {
    return "--";
  }
  const date = new Date(utcMillis(value));
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

function statusLabel(status: BacktestStatus): string {
  if (status === "running") return "Live Run";
  if (status === "completed") return "Complete";
  if (status === "paused") return "Paused";
  return "Idle";
}

function StatusBadge({ status }: { status: BacktestStatus }) {
  return (
    <span className={`btBadge btBadge-${status}`}>
      <span className="btBadgeDot" />
      {statusLabel(status)}
    </span>
  );
}

function SymbolLaneCard({
  symbol,
  trades,
  winRate,
  totalR,
  realizedPnl,
  latestTradeAt,
  active,
  onClick,
}: {
  symbol: string;
  trades: number;
  winRate: number;
  totalR: number;
  realizedPnl: number;
  latestTradeAt: string | null;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`btSymbolCard ${active ? "is-active" : ""}`}
      onClick={onClick}
    >
      <div className="btSymbolTop">
        <strong>{symbol}</strong>
        <span>{trades} trades</span>
      </div>
      <div className="btSymbolStats">
        <span>{percent(winRate)} win</span>
        <span className={totalR >= 0 ? "valueUp" : "valueDown"}>{number(totalR)}R</span>
        <span className={realizedPnl >= 0 ? "valueUp" : "valueDown"}>{money(realizedPnl)}</span>
      </div>
      <div className="btSymbolFoot">
        <span>{latestTradeAt ? shortTime(latestTradeAt) : "No close yet"}</span>
        {active ? <strong>Chart focus</strong> : <strong>Inspect</strong>}
      </div>
    </button>
  );
}

function MetricTile({
  label,
  value,
  tone = "neutral",
  detail,
}: {
  label: string;
  value: string;
  tone?: "neutral" | "up" | "down" | "signal";
  detail?: string;
}) {
  return (
    <article className={`btMetric btMetric-${tone}`}>
      <span className="btMetricLabel">{label}</span>
      <strong className="btMetricValue">{value}</strong>
      {detail ? <span className="btMetricDetail">{detail}</span> : null}
    </article>
  );
}

function BreakdownPanel({
  title,
  items,
}: {
  title: string;
  items: BreakdownStat[];
}) {
  return (
    <section className="btPanel">
      <div className="btPanelHeader">
        <div>
          <h3>{title}</h3>
          <p>Where the edge is expressing itself right now.</p>
        </div>
      </div>
      <div className="btBreakdownList">
        {items.length === 0 ? (
          <div className="btEmptyState">No closed-trade distribution yet.</div>
        ) : (
          items.map((item) => {
            const fill = `${Math.min(100, Math.max(8, Math.abs(item.totalR) * 14))}%`;
            const tone = item.totalR >= 0 ? "up" : "down";
            return (
              <div className="btBreakdownRow" key={`${title}-${item.label}`}>
                <div className="btBreakdownMeta">
                  <strong>{item.label}</strong>
                  <span>
                    {item.trades} trades | {percent(item.winRate)} win | avg {number(item.avgR)}R
                  </span>
                </div>
                <div className="btBreakdownBar">
                  <div
                    className={`btBreakdownFill btBreakdownFill-${tone}`}
                    style={{ width: fill } as CSSProperties}
                  />
                </div>
                <div className={`btBreakdownValue ${tone === "up" ? "valueUp" : "valueDown"}`}>
                  {number(item.totalR)}R
                </div>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}

export function BacktestCinema({ initialSnapshot }: BacktestCinemaProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeSymbol, setActiveSymbol] = useState(initialSnapshot.summary.activeSymbol);
  const deferredSnapshot = useDeferredValue(snapshot);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      setLoading(true);
      try {
        const response = await fetch(
          `/api/backtest/snapshot?symbol=${encodeURIComponent(activeSymbol)}`,
          { cache: "no-store" },
        );
        if (!response.ok) {
          throw new Error(`Snapshot request failed with ${response.status}`);
        }
        const next = (await response.json()) as BacktestSnapshot;
        if (!cancelled) {
          startTransition(() => {
            setSnapshot(next);
          });
          if (next.summary.activeSymbol !== activeSymbol) {
            setActiveSymbol(next.summary.activeSymbol);
          }
          setError(null);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Unknown refresh failure");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void refresh();
    if (!autoRefresh) {
      return () => {
        cancelled = true;
      };
    }

    const timer = window.setInterval(refresh, 8000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeSymbol, autoRefresh]);

  const active = deferredSnapshot;
  const symbolCards = active.summary.symbols.map((symbol) => {
    const stat = active.summary.symbolBreakdown.find((item) => item.symbol === symbol);
    return {
      symbol,
      trades: stat?.trades ?? 0,
      winRate: stat?.winRate ?? 0,
      totalR: stat?.totalR ?? 0,
      realizedPnl: stat?.realizedPnl ?? 0,
      latestTradeAt: stat?.latestTradeAt ?? null,
    };
  });
  const focusedGapWindows = active.gapWindows.filter((gap) => gap.symbol === active.summary.activeSymbol);
  const progressPct = Math.max(0, Math.min(1, active.progress.progressPct));
  const progressStyle = { width: `${progressPct * 100}%` } as CSSProperties;

  const handleSymbolSelect = (symbol: string) => {
    setActiveSymbol(symbol);
    const nextParams = new URLSearchParams(searchParams.toString());
    nextParams.set("symbol", symbol);
    router.replace(`/backtest?${nextParams.toString()}`, { scroll: false });
  };

  return (
    <main className="shell stack btShell">
      <ModeSwitchRail />
      <section className="btHero">
        <div className="btHeroCopy">
          <div className="btEyebrow">Backtest command center</div>
          <h1>Replay the strategy like a market machine, not a spreadsheet.</h1>
          <p>
            This view reads the live-growing backtest artifacts directly from disk, so the
            interface advances while the historical engine is still processing.
          </p>
        </div>
        <div className="btHeroMeta">
          <StatusBadge status={active.progress.status} />
          <div className="btHeroMetaLine">
            <span>Updated</span>
            <strong>{longDate(active.progress.checkpointUpdatedAt)}</strong>
          </div>
          <div className="btHeroMetaLine">
            <span>Simulated time</span>
            <strong>{longDate(active.progress.simulatedTime)}</strong>
          </div>
          <div className="btToggleRow">
            <button
              type="button"
              className={`btToggle ${autoRefresh ? "is-on" : ""}`}
              onClick={() => setAutoRefresh((value) => !value)}
            >
              {autoRefresh ? "Auto refresh on" : "Auto refresh off"}
            </button>
            <span className="subtle">{loading ? "Syncing snapshot..." : "Polling every 8s"}</span>
          </div>
        </div>
        <div className="btProgressDeck">
          <div className="btProgressCopy">
            <span>{active.summary.symbolScope}</span>
            <strong>
              {active.summary.executionTimeframe} execution | {compact(active.progress.nextIndex)} /{" "}
              {compact(active.progress.totalRows)} portfolio steps
            </strong>
          </div>
          <div className="btProgressBar">
            <div className="btProgressFill" style={progressStyle} />
          </div>
          <div className="btProgressCopy btProgressCopy-bottom">
            <span>{percent(progressPct)} complete | chart focus {active.summary.activeSymbol}</span>
            <strong>{money(active.summary.currentEquity)}</strong>
          </div>
        </div>
      </section>

      <section className="btMetricDeck">
        <MetricTile
          label="Current equity"
          value={money(active.summary.currentEquity)}
          tone={active.summary.realizedPnl >= 0 ? "up" : "down"}
          detail={`Start ${money(active.summary.startingEquity)}`}
        />
        <MetricTile
          label="Realized pnl"
          value={money(active.summary.realizedPnl)}
          tone={active.summary.realizedPnl >= 0 ? "up" : "down"}
          detail={`${active.summary.closedTrades} closed trades`}
        />
        <MetricTile
          label="Win rate"
          value={percent(active.summary.winRate)}
          tone="signal"
          detail={`Avg ${number(active.summary.avgR)}R`}
        />
        <MetricTile
          label="Max drawdown"
          value={money(active.summary.maxDrawdown)}
          tone="down"
          detail={`${active.summary.gapWindows} gap windows guarded | ${active.summary.watchlistSize} symbols`}
        />
        <MetricTile
          label="Best / worst"
          value={`${number(active.summary.bestTradeR)}R / ${number(active.summary.worstTradeR)}R`}
          tone="neutral"
          detail="Closed-trade distribution"
        />
      </section>

      <section className="btPanel btSymbolNavigator">
        <div className="btPanelHeader">
          <div>
            <h3>Watchlist lane</h3>
            <p>
              The portfolio runs one aggregate backtest while the chart drills into one
              symbol at a time. Use these cards to pivot the tape without losing the
              account-level context.
            </p>
          </div>
        </div>
        <div className="btSymbolGrid">
          {symbolCards.map((item) => (
            <SymbolLaneCard
              key={item.symbol}
              symbol={item.symbol}
              trades={item.trades}
              winRate={item.winRate}
              totalR={item.totalR}
              realizedPnl={item.realizedPnl}
              latestTradeAt={item.latestTradeAt}
              active={item.symbol === active.summary.activeSymbol}
              onClick={() => handleSymbolSelect(item.symbol)}
            />
          ))}
        </div>
      </section>

      <ResearchCommandDeck
        symbolScope={active.summary.symbolScope}
        symbols={active.summary.symbols}
        activeSymbol={active.summary.activeSymbol}
        executionTimeframe={active.summary.executionTimeframe}
        defaultStartDate={active.summary.startDate}
        defaultEndDate={active.summary.endDate}
      />

      {error ? <section className="btErrorBanner">{error}</section> : null}

      <section className="btGridMain">
        <TradingChart
          candles={active.candles}
          signal={null}
          position={null}
          symbol={active.summary.activeSymbol}
          timeframe={active.summary.executionTimeframe}
          equityPoints={active.equity}
          startingEquity={active.summary.startingEquity}
          trades={active.windowTrades}
          gaps={active.windowGapWindows}
          panelTitle="Backtest Cinema"
          panelSubtitle="Historical candles, trade markers, gap fences, volume, and equity now run through the same zoomable engine as replay and forward modes."
          activityLabel={`${statusLabel(active.progress.status)} | ${active.windowTrades.length} trades | ${active.windowGapWindows.length} gaps`}
        />
        <section className="btSideStack">
          <section className="btPanel btStatementPanel">
            <div className="btPanelHeader">
              <div>
                <h3>Run posture</h3>
                <p>What the historical engine is expressing at this exact moment.</p>
              </div>
            </div>
            <div className="btStatementGrid">
              <div className="btStatementCard">
                <span>Range</span>
                <strong>
                  {active.summary.startDate ?? "--"} to {active.summary.endDate ?? "--"}
                </strong>
              </div>
              <div className="btStatementCard">
                <span>Portfolio scope</span>
                <strong>{active.summary.symbolScope}</strong>
              </div>
              <div className="btStatementCard">
                <span>Chart focus</span>
                <strong>{active.summary.activeSymbol}</strong>
              </div>
              <div className="btStatementCard">
                <span>Latest trade</span>
                <strong>
                  {active.latestTrade
                    ? `${active.latestTrade.side.toUpperCase()} | ${number(active.latestTrade.realizedR)}R`
                    : "Awaiting first close"}
                </strong>
              </div>
              <div className="btStatementCard">
                <span>Anomalies</span>
                <strong>{active.anomalies.length}</strong>
              </div>
            </div>
            <div className="btAnomalyList">
              {active.anomalies.map((anomaly) => (
                <div className="btAnomalyRow" key={anomaly}>
                  {anomaly}
                </div>
              ))}
            </div>
          </section>
          <section className="btPanel">
            <div className="btPanelHeader">
              <div>
                <h3>Window telemetry</h3>
                <p>The active chart window is now aligned with the shared chart engine.</p>
              </div>
            </div>
            <div className="btStatementGrid">
              <div className="btStatementCard">
                <span>Candles loaded</span>
                <strong>{compact(active.candles.length)}</strong>
              </div>
              <div className="btStatementCard">
                <span>Focus tape rows</span>
                <strong>{compact(active.progress.chartRows)}</strong>
              </div>
              <div className="btStatementCard">
                <span>Equity points</span>
                <strong>{compact(active.equity.length)}</strong>
              </div>
              <div className="btStatementCard">
                <span>Trade markers</span>
                <strong>{active.windowTrades.length}</strong>
              </div>
              <div className="btStatementCard">
                <span>Gap shadows</span>
                <strong>{active.windowGapWindows.length}</strong>
              </div>
            </div>
            <div className="btAnomalyList">
              <div className="btAnomalyRow">
                Drag directly on the chart to pan. Use the mouse wheel to zoom. Price, volume,
                equity, trade markers, and outage fences now stay in one synchronized surface.
              </div>
            </div>
          </section>
        </section>
      </section>

      <section className="btGridSecondary">
        <BreakdownPanel title="Session heat" items={active.summary.sessionBreakdown} />
        <BreakdownPanel title="Quality tiers" items={active.summary.qualityBreakdown} />
        <BreakdownPanel title="Market states" items={active.summary.stateBreakdown} />
      </section>

      <section className="btGridSecondary">
        <PnlLedger
          trades={active.recentTrades}
          title="Backtest PnL Ledger"
          subtitle="Real-time closed-trade audit while the historical engine is still running."
        />

        <section className="btPanel">
          <div className="btPanelHeader">
            <div>
              <h3>Gap guard ledger</h3>
              <p>Historical outages the engine now fences off instead of pretending continuity.</p>
            </div>
          </div>
          {focusedGapWindows.length === 0 ? (
            <div className="btEmptyState">
              No outage windows currently mapped onto {active.summary.activeSymbol}.
            </div>
          ) : (
            <div className="btTable">
              {focusedGapWindows.slice(-10).reverse().map((gap) => (
                <div className="btTableRow" key={`gap-${gap.gapId}`}>
                  <div className="btTableTitle">
                    <strong>{gap.symbol} gap #{gap.gapId}</strong>
                    <span>{gap.missingMinutes} missing minutes</span>
                  </div>
                  <div className="btTradeMeta">
                    <span>{shortTime(gap.missingStart)}</span>
                    <span>{shortTime(gap.missingEnd)}</span>
                    <span>{gap.missingExecutionBars} execution bars affected</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </section>
    </main>
  );
}
