"use client";

import {
  startTransition,
  useDeferredValue,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import type {
  BacktestCandle,
  BacktestEquityPoint,
  BacktestSnapshot,
  BacktestStatus,
  BacktestTrade,
  BreakdownStat,
  GapWindow,
} from "../../lib/backtest-types";

type BacktestCinemaProps = {
  initialSnapshot: BacktestSnapshot;
};

type PriceCanvasProps = {
  candles: BacktestCandle[];
  trades: BacktestTrade[];
  gaps: GapWindow[];
  status: BacktestStatus;
};

type EquityCanvasProps = {
  points: BacktestEquityPoint[];
  startingEquity: number;
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

function PriceCanvas({ candles, trades, gaps, status }: PriceCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || candles.length === 0) {
      return;
    }

    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(rect.width * dpr));
    const height = Math.max(1, Math.floor(rect.height * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, rect.width, rect.height);

    const padding = { top: 28, right: 72, bottom: 38, left: 18 };
    const innerWidth = rect.width - padding.left - padding.right;
    const innerHeight = rect.height - padding.top - padding.bottom;
    const minPrice = Math.min(...candles.map((candle) => candle.low));
    const maxPrice = Math.max(...candles.map((candle) => candle.high));
    const priceSpan = Math.max(1, maxPrice - minPrice);
    const step = innerWidth / Math.max(1, candles.length);
    const bodyWidth = Math.max(2, step * 0.58);

    const priceY = (value: number) =>
      padding.top + ((maxPrice - value) / priceSpan) * innerHeight;

    const xForIndex = (index: number) => padding.left + index * step + step / 2;

    const background = ctx.createLinearGradient(0, 0, 0, rect.height);
    background.addColorStop(0, "rgba(255, 181, 72, 0.11)");
    background.addColorStop(0.38, "rgba(17, 29, 44, 0.12)");
    background.addColorStop(1, "rgba(8, 14, 23, 0.96)");
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, rect.width, rect.height);

    ctx.strokeStyle = "rgba(113, 145, 178, 0.15)";
    ctx.lineWidth = 1;
    for (let row = 0; row <= 4; row += 1) {
      const y = padding.top + (innerHeight / 4) * row;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(rect.width - padding.right + 12, y);
      ctx.stroke();
    }
    for (let column = 0; column <= 6; column += 1) {
      const x = padding.left + (innerWidth / 6) * column;
      ctx.beginPath();
      ctx.moveTo(x, padding.top);
      ctx.lineTo(x, rect.height - padding.bottom);
      ctx.stroke();
    }

    for (const gap of gaps) {
      const startIndex = candles.findIndex(
        (candle) => utcMillis(candle.time) >= utcMillis(gap.previousExecutionClose ?? gap.missingStart),
      );
      const endIndex = candles.findIndex(
        (candle) => utcMillis(candle.time) >= utcMillis(gap.nextExecutionClose ?? gap.missingEnd),
      );
      if (startIndex === -1) {
        continue;
      }
      const shadeStart = xForIndex(startIndex) - step / 2;
      const shadeEnd = xForIndex(endIndex === -1 ? candles.length - 1 : endIndex) + step / 2;
      const shade = ctx.createLinearGradient(shadeStart, 0, shadeEnd, rect.height);
      shade.addColorStop(0, "rgba(248, 113, 113, 0.06)");
      shade.addColorStop(0.5, "rgba(248, 113, 113, 0.17)");
      shade.addColorStop(1, "rgba(248, 113, 113, 0.06)");
      ctx.fillStyle = shade;
      ctx.fillRect(shadeStart, padding.top, Math.max(8, shadeEnd - shadeStart), innerHeight);
    }

    for (let index = 0; index < candles.length; index += 1) {
      const candle = candles[index];
      const x = xForIndex(index);
      const openY = priceY(candle.open);
      const closeY = priceY(candle.close);
      const highY = priceY(candle.high);
      const lowY = priceY(candle.low);
      const up = candle.close >= candle.open;

      ctx.strokeStyle = up ? "rgba(44, 208, 165, 0.95)" : "rgba(247, 122, 111, 0.95)";
      ctx.lineWidth = 1.15;
      ctx.beginPath();
      ctx.moveTo(x, highY);
      ctx.lineTo(x, lowY);
      ctx.stroke();

      const bodyTop = Math.min(openY, closeY);
      const bodyHeight = Math.max(2, Math.abs(closeY - openY));
      const bodyGradient = ctx.createLinearGradient(0, bodyTop, 0, bodyTop + bodyHeight);
      if (up) {
        bodyGradient.addColorStop(0, "rgba(117, 251, 191, 0.96)");
        bodyGradient.addColorStop(1, "rgba(28, 166, 136, 0.65)");
      } else {
        bodyGradient.addColorStop(0, "rgba(255, 178, 120, 0.96)");
        bodyGradient.addColorStop(1, "rgba(244, 92, 92, 0.65)");
      }
      ctx.fillStyle = bodyGradient;
      ctx.fillRect(x - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);
    }

    for (const trade of trades) {
      const candleIndex = candles.findIndex(
        (candle) => utcMillis(candle.time) >= utcMillis(trade.openedAt),
      );
      if (candleIndex === -1) {
        continue;
      }
      const x = xForIndex(candleIndex);
      const y = priceY(trade.entryPrice);
      ctx.save();
      ctx.translate(x, y - 16);
      ctx.fillStyle = trade.side === "long" ? "rgba(54, 211, 153, 0.95)" : "rgba(255, 110, 129, 0.95)";
      ctx.beginPath();
      if (trade.side === "long") {
        ctx.moveTo(0, -10);
        ctx.lineTo(9, 8);
        ctx.lineTo(-9, 8);
      } else {
        ctx.moveTo(0, 10);
        ctx.lineTo(9, -8);
        ctx.lineTo(-9, -8);
      }
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }

    const activeIndex = hoverIndex ?? candles.length - 1;
    const activeCandle = candles[activeIndex];
    const activeX = xForIndex(activeIndex);
    const activeY = priceY(activeCandle.close);

    ctx.strokeStyle = status === "running" ? "rgba(255, 191, 36, 0.75)" : "rgba(74, 216, 181, 0.58)";
    ctx.setLineDash([4, 6]);
    ctx.beginPath();
    ctx.moveTo(activeX, padding.top);
    ctx.lineTo(activeX, rect.height - padding.bottom);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.strokeStyle = "rgba(242, 186, 74, 0.82)";
    ctx.beginPath();
    ctx.moveTo(padding.left, activeY);
    ctx.lineTo(rect.width - padding.right + 22, activeY);
    ctx.stroke();

    ctx.fillStyle = "rgba(7, 18, 30, 0.95)";
    ctx.fillRect(rect.width - padding.right + 8, activeY - 12, 56, 24);
    ctx.fillStyle = "#ffd080";
    ctx.font = "12px 'Segoe UI'";
    ctx.fillText(activeCandle.close.toFixed(0), rect.width - padding.right + 15, activeY + 5);

    ctx.fillStyle = "rgba(230, 240, 255, 0.65)";
    ctx.font = "11px 'Segoe UI'";
    const last = candles.at(-1);
    if (last) {
      ctx.fillText(shortTime(candles[0].time), padding.left, rect.height - 14);
      ctx.fillText(shortTime(last.time), rect.width - padding.right - 40, rect.height - 14);
    }
  }, [candles, gaps, hoverIndex, status, trades]);

  const focusIndex = hoverIndex ?? (candles.length > 0 ? candles.length - 1 : null);
  const focus = focusIndex !== null ? candles[focusIndex] : null;

  return (
    <section className="btPanel btPanel-cinema">
      <div className="btPanelHeader">
        <div>
          <h3>Market Cinema</h3>
          <p>Recent execution tape with gap guards and trade intent overlaid on the backtest path.</p>
        </div>
        <StatusBadge status={status} />
      </div>
      <div className="btCinemaFrame">
        <canvas
          ref={canvasRef}
          className="btCanvas"
          onPointerLeave={() => setHoverIndex(null)}
          onPointerMove={(event) => {
            const rect = event.currentTarget.getBoundingClientRect();
            const ratio = (event.clientX - rect.left) / Math.max(1, rect.width);
            const index = Math.min(
              candles.length - 1,
              Math.max(0, Math.floor(ratio * candles.length)),
            );
            setHoverIndex(index);
          }}
        />
        <div className="btCinemaOverlay">
          <div>
            <span>Window</span>
            <strong>{candles.length} candles</strong>
          </div>
          <div>
            <span>Gaps in view</span>
            <strong>{gaps.length}</strong>
          </div>
          <div>
            <span>Trades in view</span>
            <strong>{trades.length}</strong>
          </div>
        </div>
      </div>
      {focus ? (
        <div className="btTapeStats">
          <div>
            <span>Focus time</span>
            <strong>{shortTime(focus.time)}</strong>
          </div>
          <div>
            <span>Close</span>
            <strong>{focus.close.toFixed(2)}</strong>
          </div>
          <div>
            <span>Range</span>
            <strong>{(focus.high - focus.low).toFixed(2)}</strong>
          </div>
          <div>
            <span>Volume</span>
            <strong>{compact(focus.volume)}</strong>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function EquityCanvas({ points, startingEquity }: EquityCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || points.length === 0) {
      return;
    }

    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(rect.width * dpr));
    const height = Math.max(1, Math.floor(rect.height * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, rect.width, rect.height);

    const padding = { top: 20, right: 16, bottom: 26, left: 16 };
    const innerWidth = rect.width - padding.left - padding.right;
    const innerHeight = rect.height - padding.top - padding.bottom;
    const minEquity = Math.min(startingEquity, ...points.map((point) => point.equity));
    const maxEquity = Math.max(startingEquity, ...points.map((point) => point.equity));
    const span = Math.max(1, maxEquity - minEquity);
    const xForIndex = (index: number) =>
      padding.left + (index / Math.max(1, points.length - 1)) * innerWidth;
    const yForValue = (value: number) =>
      padding.top + ((maxEquity - value) / span) * innerHeight;

    const bg = ctx.createLinearGradient(0, 0, rect.width, rect.height);
    bg.addColorStop(0, "rgba(42, 208, 162, 0.10)");
    bg.addColorStop(0.45, "rgba(255, 184, 61, 0.06)");
    bg.addColorStop(1, "rgba(12, 20, 31, 0.96)");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, rect.width, rect.height);

    const baseY = yForValue(startingEquity);
    ctx.strokeStyle = "rgba(133, 160, 183, 0.18)";
    ctx.setLineDash([5, 6]);
    ctx.beginPath();
    ctx.moveTo(padding.left, baseY);
    ctx.lineTo(rect.width - padding.right, baseY);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.beginPath();
    points.forEach((point, index) => {
      const x = xForIndex(index);
      const y = yForValue(point.equity);
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    const fill = ctx.createLinearGradient(0, padding.top, 0, rect.height);
    fill.addColorStop(0, "rgba(54, 211, 153, 0.36)");
    fill.addColorStop(1, "rgba(54, 211, 153, 0.02)");
    ctx.lineTo(rect.width - padding.right, rect.height - padding.bottom);
    ctx.lineTo(padding.left, rect.height - padding.bottom);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();

    ctx.beginPath();
    points.forEach((point, index) => {
      const x = xForIndex(index);
      const y = yForValue(point.equity);
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.strokeStyle = "rgba(94, 246, 192, 0.92)";
    ctx.lineWidth = 2.25;
    ctx.stroke();

    const focusIndex = hoverIndex ?? points.length - 1;
    const focusPoint = points[focusIndex];
    const x = xForIndex(focusIndex);
    const y = yForValue(focusPoint.equity);
    ctx.strokeStyle = "rgba(255, 188, 65, 0.72)";
    ctx.setLineDash([4, 6]);
    ctx.beginPath();
    ctx.moveTo(x, padding.top);
    ctx.lineTo(x, rect.height - padding.bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#ffd082";
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();
  }, [hoverIndex, points, startingEquity]);

  const focusIndex = hoverIndex ?? (points.length > 0 ? points.length - 1 : null);
  const focus = focusIndex !== null ? points[focusIndex] : null;

  return (
    <section className="btPanel">
      <div className="btPanelHeader">
        <div>
          <h3>Equity Pulse</h3>
          <p>Growing equity line with the capital baseline still visible underneath the motion.</p>
        </div>
      </div>
      <div className="btEquityFrame">
        <canvas
          ref={canvasRef}
          className="btCanvas btCanvas-short"
          onPointerLeave={() => setHoverIndex(null)}
          onPointerMove={(event) => {
            const rect = event.currentTarget.getBoundingClientRect();
            const ratio = (event.clientX - rect.left) / Math.max(1, rect.width);
            const index = Math.min(
              points.length - 1,
              Math.max(0, Math.floor(ratio * points.length)),
            );
            setHoverIndex(index);
          }}
        />
      </div>
      {focus ? (
        <div className="btTapeStats">
          <div>
            <span>Focus time</span>
            <strong>{shortTime(focus.time)}</strong>
          </div>
          <div>
            <span>Equity</span>
            <strong>{money(focus.equity)}</strong>
          </div>
          <div>
            <span>Delta</span>
            <strong className={focus.equity >= startingEquity ? "valueUp" : "valueDown"}>
              {money(focus.equity - startingEquity)}
            </strong>
          </div>
        </div>
      ) : null}
    </section>
  );
}

export function BacktestCinema({ initialSnapshot }: BacktestCinemaProps) {
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
        const response = await fetch("/api/backtest/snapshot", { cache: "no-store" });
        if (!response.ok) {
          throw new Error(`Snapshot request failed with ${response.status}`);
        }
        const next = (await response.json()) as BacktestSnapshot;
        if (!cancelled) {
          startTransition(() => {
            setSnapshot(next);
          });
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

    const timer = window.setInterval(refresh, 8000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [autoRefresh]);

  const active = deferredSnapshot;
  const progressPct = Math.max(0, Math.min(1, active.progress.progressPct));
  const progressStyle = { width: `${progressPct * 100}%` } as CSSProperties;

  return (
    <main className="shell stack btShell">
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
            <span>{active.summary.symbol}</span>
            <strong>
              {active.summary.executionTimeframe} execution | {compact(active.progress.nextIndex)} /{" "}
              {compact(active.progress.totalRows)} steps
            </strong>
          </div>
          <div className="btProgressBar">
            <div className="btProgressFill" style={progressStyle} />
          </div>
          <div className="btProgressCopy btProgressCopy-bottom">
            <span>{percent(progressPct)} complete</span>
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
          detail={`${active.summary.gapWindows} gap windows guarded`}
        />
        <MetricTile
          label="Best / worst"
          value={`${number(active.summary.bestTradeR)}R / ${number(active.summary.worstTradeR)}R`}
          tone="neutral"
          detail="Closed-trade distribution"
        />
      </section>

      {error ? <section className="btErrorBanner">{error}</section> : null}

      <section className="btGridMain">
        <PriceCanvas
          candles={active.candles}
          trades={active.windowTrades}
          gaps={active.windowGapWindows}
          status={active.progress.status}
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
                <span>Execution</span>
                <strong>{active.summary.executionTimeframe}</strong>
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
          <EquityCanvas
            points={active.equity}
            startingEquity={active.summary.startingEquity}
          />
        </section>
      </section>

      <section className="btGridSecondary">
        <BreakdownPanel title="Session heat" items={active.summary.sessionBreakdown} />
        <BreakdownPanel title="Quality tiers" items={active.summary.qualityBreakdown} />
        <BreakdownPanel title="Market states" items={active.summary.stateBreakdown} />
      </section>

      <section className="btGridSecondary">
        <section className="btPanel">
          <div className="btPanelHeader">
            <div>
              <h3>Recent closed trades</h3>
              <p>The latest finished outcomes, with context tags still visible.</p>
            </div>
          </div>
          {active.recentTrades.length === 0 ? (
            <div className="btEmptyState">No closed trades written yet.</div>
          ) : (
            <div className="btTable">
              {active.recentTrades.map((trade) => (
                <div className="btTableRow" key={`${trade.symbol}-${trade.closedAt}-${trade.entryPrice}`}>
                  <div className="btTableTitle">
                    <strong>{trade.side.toUpperCase()}</strong>
                    <span>{shortTime(trade.closedAt)}</span>
                  </div>
                  <div className="btTradeMeta">
                    <span>{trade.sessionName || "no session"}</span>
                    <span>{trade.marketState || "unknown"}</span>
                    <span>{trade.setupQualityLabel || "unlabeled"}</span>
                  </div>
                  <div className="btTradeNumbers">
                    <strong className={trade.realizedR >= 0 ? "valueUp" : "valueDown"}>
                      {number(trade.realizedR)}R
                    </strong>
                    <span>{money(trade.realizedPnl)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="btPanel">
          <div className="btPanelHeader">
            <div>
              <h3>Gap guard ledger</h3>
              <p>Historical outages the engine now fences off instead of pretending continuity.</p>
            </div>
          </div>
          {active.gapWindows.length === 0 ? (
            <div className="btEmptyState">No outage windows recorded.</div>
          ) : (
            <div className="btTable">
              {active.gapWindows.slice(-10).reverse().map((gap) => (
                <div className="btTableRow" key={`gap-${gap.gapId}`}>
                  <div className="btTableTitle">
                    <strong>Gap #{gap.gapId}</strong>
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
