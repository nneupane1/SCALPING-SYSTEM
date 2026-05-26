"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type {
  BacktestEquityPoint,
  BacktestTrade,
  GapWindow,
} from "../lib/backtest-types";
import type { CandlePoint, PositionView, SignalView } from "../lib/types";

type TradingChartProps = {
  candles: CandlePoint[];
  signal: SignalView | null;
  position: PositionView | null;
  symbol?: string;
  timeframe?: string;
  cursorIndex?: number | null;
  equityPoints?: BacktestEquityPoint[];
  startingEquity?: number;
  trades?: BacktestTrade[];
  gaps?: GapWindow[];
  panelTitle?: string;
  panelSubtitle?: string;
  activityLabel?: string;
};

const MIN_VISIBLE_CANDLES = 12;
const ZOOM_STEP = 1.16;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function formatPrice(value: number): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

function formatCompact(value: number): string {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function shortTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("en-GB", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
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

function rangeLabel(candle: CandlePoint | null): string {
  if (!candle) {
    return "--";
  }
  return formatPrice(candle.high - candle.low);
}

export function TradingChart({
  candles,
  signal,
  position,
  symbol = "BTCUSDT",
  timeframe = "5m",
  cursorIndex = null,
  equityPoints,
  startingEquity,
  trades,
  gaps,
  panelTitle = "Structure View",
  panelSubtitle,
  activityLabel,
}: TradingChartProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dragStateRef = useRef<{
    pointerId: number;
    startX: number;
    startAnchor: number;
    stepWidth: number;
  } | null>(null);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [zoomScale, setZoomScale] = useState(1);
  const [windowAnchor, setWindowAnchor] = useState(0);
  const [isDragging, setIsDragging] = useState(false);

  const sourceCandles =
    cursorIndex !== null ? candles.slice(0, Math.max(0, cursorIndex + 1)) : candles;
  const maxZoomScale = Math.max(1, sourceCandles.length / MIN_VISIBLE_CANDLES);
  const safeZoomScale = Math.min(Math.max(zoomScale, 1), maxZoomScale);
  const visibleCount = Math.min(
    sourceCandles.length,
    Math.max(MIN_VISIBLE_CANDLES, Math.round(sourceCandles.length / safeZoomScale)),
  );
  const maxAnchor = Math.max(0, sourceCandles.length - visibleCount);
  const clampedAnchor = Math.min(windowAnchor, maxAnchor);
  const endExclusive = Math.max(visibleCount, sourceCandles.length - clampedAnchor);
  const startIndex = Math.max(0, endExclusive - visibleCount);
  const visibleCandles = sourceCandles.slice(startIndex, endExclusive);

  const windowStartMillis = visibleCandles.length
    ? utcMillis(visibleCandles[0].time)
    : Number.NaN;
  const windowEndMillis = visibleCandles.length
    ? utcMillis(visibleCandles[visibleCandles.length - 1].time)
    : Number.NaN;

  const visibleEquity = useMemo(() => {
    if (!equityPoints || equityPoints.length === 0 || !Number.isFinite(windowStartMillis)) {
      return [];
    }
    const filtered = equityPoints.filter((point) => {
      const time = utcMillis(point.time);
      return time >= windowStartMillis && time <= windowEndMillis;
    });
    if (filtered.length > 1) {
      return filtered;
    }
    return equityPoints.slice(-Math.min(visibleCandles.length, equityPoints.length));
  }, [equityPoints, visibleCandles.length, windowEndMillis, windowStartMillis]);

  const visibleTrades = useMemo(() => {
    if (!trades || trades.length === 0 || !Number.isFinite(windowStartMillis)) {
      return [];
    }
    return trades.filter((trade) => {
      const opened = utcMillis(trade.openedAt);
      const closed = utcMillis(trade.closedAt);
      return closed >= windowStartMillis && opened <= windowEndMillis;
    });
  }, [trades, windowEndMillis, windowStartMillis]);

  const visibleGaps = useMemo(() => {
    if (!gaps || gaps.length === 0 || !Number.isFinite(windowStartMillis)) {
      return [];
    }
    return gaps.filter((gap) => {
      const start = utcMillis(gap.missingStart);
      const end = utcMillis(gap.missingEnd);
      return end >= windowStartMillis && start <= windowEndMillis;
    });
  }, [gaps, windowEndMillis, windowStartMillis]);

  const focusIndex =
    hoverIndex ?? (visibleCandles.length > 0 ? visibleCandles.length - 1 : null);
  const focus = focusIndex !== null ? visibleCandles[focusIndex] : null;
  const focusTimeMs = focus ? utcMillis(focus.time) : Number.NaN;
  const focusEquity = useMemo(() => {
    if (visibleEquity.length === 0 || !Number.isFinite(focusTimeMs)) {
      return null;
    }
    return visibleEquity.reduce((closest, point) => {
      if (!closest) {
        return point;
      }
      return Math.abs(utcMillis(point.time) - focusTimeMs) <
        Math.abs(utcMillis(closest.time) - focusTimeMs)
        ? point
        : closest;
    }, visibleEquity[0] ?? null);
  }, [focusTimeMs, visibleEquity]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || visibleCandles.length === 0) {
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

    const padding = { top: 28, right: 78, bottom: 28, left: 18 };
    const paneGap = 12;
    const innerWidth = rect.width - padding.left - padding.right;
    const innerHeight = rect.height - padding.top - padding.bottom;
    const showVolume = visibleCandles.some((candle) => (candle.volume ?? 0) > 0);
    const showEquity = visibleEquity.length > 1 && typeof startingEquity === "number";
    const volumeHeight = showVolume ? Math.max(72, innerHeight * 0.18) : 0;
    const equityHeight = showEquity ? Math.max(76, innerHeight * 0.18) : 0;
    const usedGapCount = (showVolume ? 1 : 0) + (showEquity ? 1 : 0);
    const priceHeight = innerHeight - volumeHeight - equityHeight - usedGapCount * paneGap;
    const priceTop = padding.top;
    const volumeTop = priceTop + priceHeight + (showVolume ? paneGap : 0);
    const equityTop =
      volumeTop + volumeHeight + (showEquity && showVolume ? paneGap : showEquity ? paneGap : 0);

    const overlayLevels = [
      signal?.entryPrice,
      signal?.stopPrice,
      signal?.targetPrice,
      position?.entryPrice,
      position?.stopPrice,
    ].filter((value): value is number => typeof value === "number");

    const rawMin = Math.min(
      ...visibleCandles.map((candle) => candle.low),
      ...(overlayLevels.length > 0 ? overlayLevels : [Number.POSITIVE_INFINITY]),
    );
    const rawMax = Math.max(
      ...visibleCandles.map((candle) => candle.high),
      ...(overlayLevels.length > 0 ? overlayLevels : [Number.NEGATIVE_INFINITY]),
    );
    const rawSpan = Math.max(1, rawMax - rawMin);
    const priceMin = rawMin - rawSpan * 0.12;
    const priceMax = rawMax + rawSpan * 0.12;
    const priceSpan = Math.max(1, priceMax - priceMin);
    const step = innerWidth / Math.max(1, visibleCandles.length);
    const bodyWidth = Math.max(3, Math.min(16, step * 0.6));

    const xForIndex = (index: number) => padding.left + index * step + step / 2;
    const xForTime = (timeMs: number) => {
      if (!Number.isFinite(windowStartMillis) || !Number.isFinite(windowEndMillis)) {
        return padding.left;
      }
      const ratio =
        windowEndMillis === windowStartMillis
          ? 1
          : clamp((timeMs - windowStartMillis) / (windowEndMillis - windowStartMillis), 0, 1);
      return padding.left + ratio * innerWidth;
    };
    const priceY = (value: number) => priceTop + ((priceMax - value) / priceSpan) * priceHeight;

    const background = ctx.createLinearGradient(0, 0, 0, rect.height);
    background.addColorStop(0, "rgba(255, 184, 77, 0.09)");
    background.addColorStop(0.35, "rgba(15, 26, 38, 0.1)");
    background.addColorStop(1, "rgba(6, 12, 19, 0.98)");
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, rect.width, rect.height);

    const drawGrid = (top: number, heightValue: number, rows: number) => {
      ctx.strokeStyle = "rgba(113, 145, 178, 0.16)";
      ctx.lineWidth = 1;
      for (let row = 0; row <= rows; row += 1) {
        const y = top + (heightValue / rows) * row;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(rect.width - padding.right + 10, y);
        ctx.stroke();
      }
    };

    drawGrid(priceTop, priceHeight, 5);
    if (showVolume) {
      drawGrid(volumeTop, volumeHeight, 2);
    }
    if (showEquity) {
      drawGrid(equityTop, equityHeight, 2);
    }

    ctx.strokeStyle = "rgba(113, 145, 178, 0.12)";
    for (let column = 0; column <= 6; column += 1) {
      const x = padding.left + (innerWidth / 6) * column;
      ctx.beginPath();
      ctx.moveTo(x, priceTop);
      ctx.lineTo(x, rect.height - padding.bottom);
      ctx.stroke();
    }

    const drawLevel = (price: number, label: string, stroke: string, fill: string) => {
      const y = priceY(price);
      ctx.save();
      ctx.setLineDash([6, 6]);
      ctx.strokeStyle = stroke;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(rect.width - padding.right + 16, y);
      ctx.stroke();
      ctx.restore();

      const labelWidth = Math.max(54, ctx.measureText(label).width + 18);
      ctx.fillStyle = fill;
      ctx.fillRect(rect.width - padding.right - labelWidth - 4, y - 12, labelWidth, 22);
      ctx.fillStyle = "#f3f8ff";
      ctx.font = "11px 'Segoe UI'";
      ctx.fillText(label, rect.width - padding.right - labelWidth + 6, y + 4);
    };

    if (signal) {
      drawLevel(
        signal.entryPrice,
        `Entry ${formatPrice(signal.entryPrice)}`,
        "rgba(95, 246, 192, 0.88)",
        "rgba(13, 82, 63, 0.84)",
      );
      drawLevel(
        signal.stopPrice,
        `Stop ${formatPrice(signal.stopPrice)}`,
        "rgba(248, 113, 113, 0.84)",
        "rgba(92, 28, 39, 0.84)",
      );
      drawLevel(
        signal.targetPrice,
        `Target ${formatPrice(signal.targetPrice)}`,
        "rgba(255, 192, 93, 0.84)",
        "rgba(94, 57, 12, 0.84)",
      );
    } else if (position) {
      drawLevel(
        position.entryPrice,
        `Entry ${formatPrice(position.entryPrice)}`,
        "rgba(95, 246, 192, 0.84)",
        "rgba(13, 82, 63, 0.84)",
      );
      drawLevel(
        position.stopPrice,
        `Stop ${formatPrice(position.stopPrice)}`,
        "rgba(248, 113, 113, 0.84)",
        "rgba(92, 28, 39, 0.84)",
      );
    }

    for (const gap of visibleGaps) {
      const gapStartMs = utcMillis(gap.previousExecutionClose ?? gap.missingStart);
      const gapEndMs = utcMillis(gap.nextExecutionClose ?? gap.missingEnd);
      const shadeStart = xForTime(gapStartMs);
      const shadeEnd = xForTime(gapEndMs);
      const left = Math.min(shadeStart, shadeEnd);
      const right = Math.max(shadeStart, shadeEnd);
      const shade = ctx.createLinearGradient(left, 0, right, rect.height);
      shade.addColorStop(0, "rgba(248, 113, 113, 0.06)");
      shade.addColorStop(0.5, "rgba(248, 113, 113, 0.17)");
      shade.addColorStop(1, "rgba(248, 113, 113, 0.06)");
      ctx.fillStyle = shade;
      ctx.fillRect(left, priceTop, Math.max(8, right - left), priceHeight);
    }

    if (showVolume) {
      const volumeMax = Math.max(1, ...visibleCandles.map((candle) => candle.volume ?? 0));
      for (let index = 0; index < visibleCandles.length; index += 1) {
        const candle = visibleCandles[index];
        const volume = candle.volume ?? 0;
        const x = xForIndex(index);
        const barHeight = (volume / volumeMax) * (volumeHeight - 14);
        const up = candle.close >= candle.open;
        const gradient = ctx.createLinearGradient(0, volumeTop + volumeHeight, 0, volumeTop);
        if (up) {
          gradient.addColorStop(0, "rgba(33, 137, 115, 0.18)");
          gradient.addColorStop(1, "rgba(90, 248, 189, 0.72)");
        } else {
          gradient.addColorStop(0, "rgba(130, 48, 48, 0.16)");
          gradient.addColorStop(1, "rgba(255, 148, 120, 0.68)");
        }
        ctx.fillStyle = gradient;
        ctx.fillRect(
          x - Math.max(2, bodyWidth / 2),
          volumeTop + volumeHeight - barHeight - 6,
          Math.max(3, bodyWidth),
          barHeight,
        );
      }
    }

    for (let index = 0; index < visibleCandles.length; index += 1) {
      const candle = visibleCandles[index];
      const x = xForIndex(index);
      const openY = priceY(candle.open);
      const closeY = priceY(candle.close);
      const highY = priceY(candle.high);
      const lowY = priceY(candle.low);
      const up = candle.close >= candle.open;

      ctx.strokeStyle = up ? "rgba(44, 208, 165, 0.98)" : "rgba(247, 122, 111, 0.98)";
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(x, highY);
      ctx.lineTo(x, lowY);
      ctx.stroke();

      const bodyTop = Math.min(openY, closeY);
      const bodyHeight = Math.max(2, Math.abs(closeY - openY));
      const bodyGradient = ctx.createLinearGradient(0, bodyTop, 0, bodyTop + bodyHeight);
      if (up) {
        bodyGradient.addColorStop(0, "rgba(122, 255, 204, 0.98)");
        bodyGradient.addColorStop(1, "rgba(28, 166, 136, 0.7)");
      } else {
        bodyGradient.addColorStop(0, "rgba(255, 188, 118, 0.98)");
        bodyGradient.addColorStop(1, "rgba(238, 93, 87, 0.7)");
      }
      ctx.fillStyle = bodyGradient;
      ctx.fillRect(x - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);
    }

    for (const trade of visibleTrades) {
      const entryX = xForTime(utcMillis(trade.openedAt));
      const exitX = xForTime(utcMillis(trade.closedAt));
      const entryY = priceY(trade.entryPrice);
      const exitY = priceY(trade.exitPrice);
      const entryTone =
        trade.side === "long" ? "rgba(54, 211, 153, 0.95)" : "rgba(255, 110, 129, 0.95)";
      const exitTone =
        trade.realizedPnl >= 0 ? "rgba(255, 209, 122, 0.92)" : "rgba(255, 140, 122, 0.92)";

      ctx.save();
      ctx.setLineDash([4, 6]);
      ctx.strokeStyle = "rgba(236, 245, 255, 0.28)";
      ctx.lineWidth = 1.1;
      ctx.beginPath();
      ctx.moveTo(entryX, entryY);
      ctx.lineTo(exitX, exitY);
      ctx.stroke();
      ctx.restore();

      ctx.save();
      ctx.translate(entryX, entryY + (trade.side === "long" ? -16 : 16));
      ctx.fillStyle = entryTone;
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

      ctx.fillStyle = exitTone;
      ctx.beginPath();
      ctx.arc(exitX, exitY, 4.5, 0, Math.PI * 2);
      ctx.fill();
    }

    if (showEquity) {
      const equityMin = Math.min(startingEquity ?? 0, ...visibleEquity.map((point) => point.equity));
      const equityMax = Math.max(startingEquity ?? 0, ...visibleEquity.map((point) => point.equity));
      const equitySpan = Math.max(1, equityMax - equityMin);
      const equityY = (value: number) =>
        equityTop + ((equityMax - value) / equitySpan) * equityHeight;

      ctx.beginPath();
      visibleEquity.forEach((point, index) => {
        const x = xForTime(utcMillis(point.time));
        const y = equityY(point.equity);
        if (index === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
      const fill = ctx.createLinearGradient(0, equityTop, 0, equityTop + equityHeight);
      fill.addColorStop(0, "rgba(54, 211, 153, 0.32)");
      fill.addColorStop(1, "rgba(54, 211, 153, 0.02)");
      ctx.lineTo(rect.width - padding.right, equityTop + equityHeight);
      ctx.lineTo(padding.left, equityTop + equityHeight);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();

      ctx.beginPath();
      visibleEquity.forEach((point, index) => {
        const x = xForTime(utcMillis(point.time));
        const y = equityY(point.equity);
        if (index === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.strokeStyle = "rgba(94, 246, 192, 0.92)";
      ctx.lineWidth = 2.1;
      ctx.stroke();

      const baseY = equityY(startingEquity ?? 0);
      ctx.strokeStyle = "rgba(133, 160, 183, 0.16)";
      ctx.setLineDash([4, 6]);
      ctx.beginPath();
      ctx.moveTo(padding.left, baseY);
      ctx.lineTo(rect.width - padding.right + 10, baseY);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    const activeIndex = focusIndex ?? visibleCandles.length - 1;
    const activeCandle = visibleCandles[activeIndex];
    const activeX = xForIndex(activeIndex);
    const activeY = priceY(activeCandle.close);

    ctx.strokeStyle = isDragging
      ? "rgba(148, 201, 255, 0.74)"
      : "rgba(255, 191, 36, 0.82)";
    ctx.setLineDash([4, 6]);
    ctx.beginPath();
    ctx.moveTo(activeX, priceTop);
    ctx.lineTo(activeX, rect.height - padding.bottom);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.strokeStyle = "rgba(255, 191, 36, 0.66)";
    ctx.beginPath();
    ctx.moveTo(padding.left, activeY);
    ctx.lineTo(rect.width - padding.right + 18, activeY);
    ctx.stroke();

    ctx.fillStyle = "rgba(7, 18, 30, 0.96)";
    ctx.fillRect(rect.width - padding.right + 8, activeY - 12, 68, 24);
    ctx.fillStyle = "#ffd080";
    ctx.font = "12px 'Segoe UI'";
    ctx.fillText(formatPrice(activeCandle.close), rect.width - padding.right + 14, activeY + 5);

    if (showEquity && focusEquity) {
      const equityMin = Math.min(startingEquity ?? 0, ...visibleEquity.map((point) => point.equity));
      const equityMax = Math.max(startingEquity ?? 0, ...visibleEquity.map((point) => point.equity));
      const equitySpan = Math.max(1, equityMax - equityMin);
      const equityY = (value: number) =>
        equityTop + ((equityMax - value) / equitySpan) * equityHeight;
      const y = equityY(focusEquity.equity);
      ctx.fillStyle = "#7df5c1";
      ctx.beginPath();
      ctx.arc(xForTime(utcMillis(focusEquity.time)), y, 4, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.fillStyle = "rgba(227, 239, 253, 0.6)";
    ctx.font = "11px 'Segoe UI'";
    for (let row = 0; row <= 5; row += 1) {
      const level = priceMax - (priceSpan / 5) * row;
      const y = priceTop + (priceHeight / 5) * row;
      ctx.fillText(formatPrice(level), rect.width - padding.right + 10, y - 4);
    }

    if (showVolume) {
      ctx.fillStyle = "rgba(227, 239, 253, 0.44)";
      const volumeMax = Math.max(1, ...visibleCandles.map((candle) => candle.volume ?? 0));
      ctx.fillText(formatCompact(volumeMax), rect.width - padding.right + 10, volumeTop + 10);
    }

    if (showEquity && focusEquity) {
      ctx.fillStyle = "rgba(125, 245, 193, 0.72)";
      ctx.fillText(
        formatPrice(focusEquity.equity),
        rect.width - padding.right + 10,
        equityTop + 12,
      );
    }

    ctx.fillStyle = "rgba(227, 239, 253, 0.62)";
    if (visibleCandles[0]) {
      ctx.fillText(shortTime(visibleCandles[0].time), padding.left, rect.height - 10);
      ctx.fillText(
        shortTime(visibleCandles[visibleCandles.length - 1].time),
        rect.width - padding.right - 50,
        rect.height - 10,
      );
    }

    ctx.fillStyle = "rgba(255, 255, 255, 0.82)";
    ctx.font = "12px 'Segoe UI'";
    ctx.fillText(`${symbol}  ${timeframe}  ${visibleCandles.length} candles`, padding.left, 16);
  }, [
    focus,
    focusEquity,
    focusIndex,
    isDragging,
    position,
    safeZoomScale,
    signal,
    startingEquity,
    symbol,
    timeframe,
    visibleCandles,
    visibleEquity,
    visibleGaps,
    visibleTrades,
    windowEndMillis,
    windowStartMillis,
  ]);

  if (sourceCandles.length === 0) {
    return (
      <section className="panel chart">
        <div className="panelHeader">
          <div>
            <h3>{panelTitle}</h3>
            <div className="subtle">No candles available for the active sequence.</div>
          </div>
        </div>
      </section>
    );
  }

  const hasBacktestOverlays = visibleTrades.length > 0 || visibleGaps.length > 0;
  const resolvedSubtitle =
    panelSubtitle ??
    (hasBacktestOverlays
      ? "Drag to pan, wheel to zoom, and inspect historical candles with synchronized price, volume, equity, trade, and gap overlays."
      : "Drag to pan, wheel to zoom, and read synchronized price, volume, and equity context off one surface.");
  const resolvedActivityLabel =
    activityLabel ??
    (signal
      ? `Signal ${signal.side}`
      : position
        ? "Position live"
        : hasBacktestOverlays
          ? `${visibleTrades.length} trades | ${visibleGaps.length} gaps`
          : "No Signal");

  return (
    <section className="panel chart">
      <div className="panelHeader">
        <div>
          <h3>{panelTitle}</h3>
          <div className="subtle">{resolvedSubtitle}</div>
        </div>
        <div className="chartHeaderTools">
          <span className="chartTimeframeChip">{symbol} | {timeframe}</span>
          <div className="pill">{resolvedActivityLabel}</div>
        </div>
      </div>

      <div className="chartToolbar">
        <div className="chartToolbarGroup">
          <button
            type="button"
            className="toolButton"
            onClick={() =>
              setWindowAnchor((value) =>
                Math.min(maxAnchor, value + Math.max(3, Math.floor(visibleCount / 4))),
              )
            }
            disabled={clampedAnchor >= maxAnchor}
          >
            Pan left
          </button>
          <button
            type="button"
            className="toolButton"
            onClick={() =>
              setWindowAnchor((value) =>
                Math.max(0, value - Math.max(3, Math.floor(visibleCount / 4))),
              )
            }
            disabled={clampedAnchor <= 0}
          >
            Pan right
          </button>
        </div>
        <div className="chartToolbarGroup">
          <button
            type="button"
            className="toolButton"
            onClick={() => {
              setZoomScale((value) => Math.min(maxZoomScale, value * ZOOM_STEP));
              setHoverIndex(null);
            }}
            disabled={safeZoomScale >= maxZoomScale}
          >
            Zoom in
          </button>
          <button
            type="button"
            className="toolButton"
            onClick={() => {
              setZoomScale((value) => Math.max(1, value / ZOOM_STEP));
              setHoverIndex(null);
            }}
            disabled={safeZoomScale <= 1}
          >
            Zoom out
          </button>
          <button
            type="button"
            className="toolButton"
            onClick={() => {
              setZoomScale(1);
              setWindowAnchor(0);
              setHoverIndex(null);
            }}
          >
            Reset view
          </button>
        </div>
      </div>

      <div className="chartStage">
        <canvas
          ref={canvasRef}
          className={`chartCanvas ${isDragging ? "is-dragging" : ""}`}
          onPointerDown={(event) => {
            if (visibleCandles.length === 0) {
              return;
            }
            const rect = event.currentTarget.getBoundingClientRect();
            const stepWidth = (rect.width - 18 - 78) / Math.max(1, visibleCandles.length);
            dragStateRef.current = {
              pointerId: event.pointerId,
              startX: event.clientX,
              startAnchor: clampedAnchor,
              stepWidth,
            };
            setIsDragging(true);
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerUp={(event) => {
            if (
              dragStateRef.current &&
              dragStateRef.current.pointerId === event.pointerId
            ) {
              dragStateRef.current = null;
              setIsDragging(false);
              event.currentTarget.releasePointerCapture(event.pointerId);
            }
          }}
          onPointerCancel={() => {
            dragStateRef.current = null;
            setIsDragging(false);
          }}
          onPointerLeave={() => {
            if (!dragStateRef.current) {
              setHoverIndex(null);
            }
          }}
          onPointerMove={(event) => {
            const rect = event.currentTarget.getBoundingClientRect();
            const ratio = (event.clientX - rect.left) / Math.max(1, rect.width);
            const index = Math.min(
              visibleCandles.length - 1,
              Math.max(0, Math.floor(ratio * visibleCandles.length)),
            );

            if (dragStateRef.current) {
              const deltaX = event.clientX - dragStateRef.current.startX;
              const shift = Math.round(deltaX / Math.max(1, dragStateRef.current.stepWidth));
              setWindowAnchor(
                clamp(dragStateRef.current.startAnchor + shift, 0, maxAnchor),
              );
              return;
            }

            setHoverIndex(index);
          }}
          onWheel={(event) => {
            event.preventDefault();
            if (event.deltaY < 0) {
              setZoomScale((value) => Math.min(maxZoomScale, value * ZOOM_STEP));
            } else {
              setZoomScale((value) => Math.max(1, value / ZOOM_STEP));
            }
          }}
        />
        <div className="chartOverlay">
          <div className="chartOverlayCard">
            <span>Window</span>
            <strong>{visibleCandles.length} candles</strong>
          </div>
          <div className="chartOverlayCard">
            <span>Timeframe</span>
            <strong>{timeframe}</strong>
          </div>
          <div className="chartOverlayCard">
            <span>Zoom</span>
            <strong>{Math.round(safeZoomScale * 100)}%</strong>
          </div>
          <div className="chartOverlayCard">
            <span>Focus close</span>
            <strong>{focus ? formatPrice(focus.close) : "--"}</strong>
          </div>
          <div className="chartOverlayCard">
            <span>Bias</span>
            <strong>{resolvedActivityLabel}</strong>
          </div>
          {hasBacktestOverlays ? (
            <>
              <div className="chartOverlayCard">
                <span>Trade markers</span>
                <strong>{visibleTrades.length}</strong>
              </div>
              <div className="chartOverlayCard">
                <span>Gap shadows</span>
                <strong>{visibleGaps.length}</strong>
              </div>
            </>
          ) : null}
        </div>
      </div>

      <div className="chartTapeStats">
        <div>
          <span>Focus time</span>
          <strong>{focus ? shortTime(focus.time) : "--"}</strong>
        </div>
        <div>
          <span>Open</span>
          <strong>{focus ? formatPrice(focus.open) : "--"}</strong>
        </div>
        <div>
          <span>High</span>
          <strong>{focus ? formatPrice(focus.high) : "--"}</strong>
        </div>
        <div>
          <span>Low</span>
          <strong>{focus ? formatPrice(focus.low) : "--"}</strong>
        </div>
        <div>
          <span>Close</span>
          <strong>{focus ? formatPrice(focus.close) : "--"}</strong>
        </div>
        <div>
          <span>Range</span>
          <strong>{rangeLabel(focus)}</strong>
        </div>
        <div>
          <span>Volume</span>
          <strong>{focus ? formatCompact(focus.volume ?? 0) : "--"}</strong>
        </div>
        {hasBacktestOverlays ? (
          <div>
            <span>Overlays</span>
            <strong>{visibleTrades.length}T / {visibleGaps.length}G</strong>
          </div>
        ) : null}
        {focusEquity ? (
          <div>
            <span>Equity sync</span>
            <strong>{formatPrice(focusEquity.equity)}</strong>
          </div>
        ) : null}
      </div>

      {signal || position ? (
        <div className="metricGrid">
          <div className="metricCard">
            <span className="metricLabel">Entry</span>
            <div className="metricValue">{signal ? formatPrice(signal.entryPrice) : "-"}</div>
          </div>
          <div className="metricCard">
            <span className="metricLabel">Stop</span>
            <div className="metricValue">
              {signal
                ? formatPrice(signal.stopPrice)
                : position
                  ? formatPrice(position.stopPrice)
                  : "-"}
            </div>
          </div>
          <div className="metricCard">
            <span className="metricLabel">Target</span>
            <div className="metricValue">{signal ? formatPrice(signal.targetPrice) : "-"}</div>
          </div>
          <div className="metricCard">
            <span className="metricLabel">Runner</span>
            <div className="metricValue">
              {position ? `${position.remainingQuantity.toFixed(2)} left` : "Flat"}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
