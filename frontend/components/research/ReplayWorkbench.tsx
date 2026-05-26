"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { ModeSwitchRail } from "../navigation/ModeSwitchRail";
import { TradingChart } from "../TradingChart";
import type { CandlePoint } from "../../lib/types";

type ReplayResponse = {
  candles: CandlePoint[];
  truncated: boolean;
  sampleStride: number;
  returnedRows: number;
};

const PLAYBACK_SPEEDS = [
  { label: "Slow", value: 900 },
  { label: "Desk", value: 380 },
  { label: "Fast", value: 140 },
] as const;

function dateOnly(value: string | null, fallback: string): string {
  if (!value) {
    return fallback;
  }
  return value.slice(0, 10);
}

function runnerDate(value: string): string {
  return `${value} 00:00:00`;
}

function focusTime(candle: CandlePoint | undefined): string {
  if (!candle) {
    return "--";
  }
  const parsed = new Date(candle.time);
  if (Number.isNaN(parsed.getTime())) {
    return candle.time;
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

export function ReplayWorkbench() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [symbol, setSymbol] = useState(searchParams.get("symbol") ?? "BTCUSDT");
  const [timeframe, setTimeframe] = useState(searchParams.get("timeframe") ?? "5m");
  const [startDate, setStartDate] = useState(
    dateOnly(searchParams.get("start"), "2026-05-01"),
  );
  const [endDate, setEndDate] = useState(dateOnly(searchParams.get("end"), "2026-05-23"));
  const [candles, setCandles] = useState<CandlePoint[]>([]);
  const [cursorIndex, setCursorIndex] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState<number>(PLAYBACK_SPEEDS[1].value);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [sampleStride, setSampleStride] = useState(1);

  const loadReplaySlice = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const query = new URLSearchParams({
        symbol,
        timeframe,
        start: runnerDate(startDate),
        end: runnerDate(endDate),
        maxRows: "2400",
      });
      const response = await fetch(`/api/market/candles?${query.toString()}`, {
        cache: "no-store",
      });
      const payload = (await response.json()) as ReplayResponse & { error?: string };
      if (!response.ok) {
        throw new Error(payload.error ?? "Unable to load replay candles");
      }
      setCandles(payload.candles);
      setTruncated(payload.truncated);
      setSampleStride(payload.sampleStride);
      setCursorIndex(payload.candles.length > 0 ? Math.min(payload.candles.length - 1, 120) : null);
      setPlaying(false);
      setMessage(
        payload.candles.length > 0
          ? `Loaded ${payload.returnedRows.toLocaleString()} candles for replay.`
          : "No candles found for this range.",
      );
      router.replace(
        `/replay?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(
          timeframe,
        )}&start=${encodeURIComponent(runnerDate(startDate))}&end=${encodeURIComponent(
          runnerDate(endDate),
        )}`,
      );
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Unable to load replay candles");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadReplaySlice();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!playing || cursorIndex === null || candles.length === 0) {
      return;
    }
    if (cursorIndex >= candles.length - 1) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(() => {
      setCursorIndex((value) =>
        value === null ? 0 : Math.min(candles.length - 1, value + 1),
      );
    }, playSpeed);
    return () => window.clearTimeout(timer);
  }, [candles.length, cursorIndex, playSpeed, playing]);

  const focusCandle =
    cursorIndex !== null && cursorIndex >= 0 && cursorIndex < candles.length
      ? candles[cursorIndex]
      : undefined;
  const visibleCount = cursorIndex !== null ? cursorIndex + 1 : 0;
  const progressPct =
    candles.length > 0 && cursorIndex !== null ? ((cursorIndex + 1) / candles.length) * 100 : 0;
  const replayTone = useMemo(() => {
    if (!focusCandle) {
      return "Awaiting slice";
    }
    return focusCandle.close >= focusCandle.open ? "Expansion candle" : "Counter candle";
  }, [focusCandle]);

  return (
    <main className="shell stack btShell">
      <ModeSwitchRail />
      <section className="btHero">
        <div className="btHeroCopy">
          <div className="btEyebrow">Replay workspace</div>
          <h1>Scrub the historical tape like an operator, not a spreadsheet.</h1>
          <p>
            Load a real historical slice from disk, then step or play through it with a
            TradingView-style candlestick surface, date control, and continuous zoom.
          </p>
        </div>
        <div className="btHeroMeta">
          <div className="btHeroMetaLine">
            <span>Symbol</span>
            <strong>{symbol}</strong>
          </div>
          <div className="btHeroMetaLine">
            <span>Timeframe</span>
            <strong>{timeframe}</strong>
          </div>
          <div className="btHeroMetaLine">
            <span>Playback head</span>
            <strong>{focusTime(focusCandle)}</strong>
          </div>
          <div className="btToggleRow">
            <button
              type="button"
              className={`btToggle ${playing ? "is-on" : ""}`}
              onClick={() => setPlaying((value) => !value)}
              disabled={candles.length === 0}
            >
              {playing ? "Pause replay" : "Play replay"}
            </button>
            <span className="subtle">{replayTone}</span>
          </div>
        </div>
        <div className="btProgressDeck">
          <div className="btProgressCopy">
            <span>{symbol}</span>
            <strong>
              {visibleCount.toLocaleString()} / {candles.length.toLocaleString()} replay bars
            </strong>
          </div>
          <div className="btProgressBar">
            <div className="btProgressFill" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="btProgressCopy btProgressCopy-bottom">
            <span>{progressPct.toFixed(1)}% revealed</span>
            <strong>{truncated ? `sampled x${sampleStride}` : "full slice"}</strong>
          </div>
        </div>
      </section>

      <section className="btPanel researchDock">
        <div className="btPanelHeader">
          <div>
            <h3>Replay Loader</h3>
            <p>
              Choose the exact historical slice and timeframe you want to inspect. Backtests
              still respect London / New York entry windows; this replay view lets you inspect
              the underlying tape across any date you load.
            </p>
          </div>
        </div>

        <div className="researchGrid">
          <label className="researchField">
            <span>Symbol</span>
            <input
              value={symbol}
              onChange={(event) => setSymbol(event.target.value.toUpperCase())}
              className="researchInput"
            />
          </label>
          <label className="researchField">
            <span>Timeframe</span>
            <select
              value={timeframe}
              onChange={(event) => setTimeframe(event.target.value)}
              className="researchInput"
            >
              <option value="1m">1m</option>
              <option value="5m">5m</option>
              <option value="15m">15m</option>
            </select>
          </label>
          <label className="researchField">
            <span>Start date</span>
            <input
              type="date"
              value={startDate}
              onChange={(event) => setStartDate(event.target.value)}
              className="researchInput"
            />
          </label>
          <label className="researchField">
            <span>End date</span>
            <input
              type="date"
              value={endDate}
              onChange={(event) => setEndDate(event.target.value)}
              className="researchInput"
            />
          </label>
        </div>

        <div className="researchMetaRow">
          <div className="researchMetaCard">
            <span>Playback speed</span>
            <strong>{PLAYBACK_SPEEDS.find((item) => item.value === playSpeed)?.label}</strong>
          </div>
          <div className="researchMetaCard">
            <span>Sampling</span>
            <strong>{truncated ? `Stride ${sampleStride}` : "Full fidelity"}</strong>
          </div>
          <div className="researchMetaCard">
            <span>Loaded bars</span>
            <strong>{candles.length.toLocaleString()}</strong>
          </div>
        </div>

        <div className="researchActionRow">
          <button
            type="button"
            className="researchPrimaryButton"
            onClick={() => void loadReplaySlice()}
            disabled={loading}
          >
            {loading ? "Loading slice..." : "Load Replay Slice"}
          </button>
          <button
            type="button"
            className="researchSecondaryButton"
            onClick={() => router.push("/backtest")}
          >
            Backtest Command Center
          </button>
          <select
            value={String(playSpeed)}
            onChange={(event) => setPlaySpeed(Number(event.target.value))}
            className="researchInput researchSpeedSelect"
          >
            {PLAYBACK_SPEEDS.map((speed) => (
              <option key={speed.value} value={speed.value}>
                {speed.label}
              </option>
            ))}
          </select>
        </div>

        <div className="researchFooter">
          <span>
            If the date span is very large, the API samples the slice to keep the browser fast
            enough for smooth zooming and playback.
          </span>
          {message ? <strong>{message}</strong> : null}
        </div>
      </section>

      <section className="btPanel">
        <div className="btPanelHeader">
          <div>
            <h3>Bar Replay</h3>
            <p>Step bar by bar, scrub the tape, then drag-pan and zoom the chart around the revealed window.</p>
          </div>
        </div>

        <div className="replayTransport">
          <button
            type="button"
            className="toolButton"
            onClick={() => {
              setPlaying(false);
              setCursorIndex(candles.length > 0 ? 0 : null);
            }}
            disabled={candles.length === 0}
          >
            Jump to start
          </button>
          <button
            type="button"
            className="toolButton"
            onClick={() => {
              setPlaying(false);
              setCursorIndex((value) => Math.max(0, (value ?? 0) - 1));
            }}
            disabled={candles.length === 0 || cursorIndex === null || cursorIndex <= 0}
          >
            Step back
          </button>
          <button
            type="button"
            className="toolButton"
            onClick={() => setPlaying((value) => !value)}
            disabled={candles.length === 0}
          >
            {playing ? "Pause" : "Play"}
          </button>
          <button
            type="button"
            className="toolButton"
            onClick={() =>
              setCursorIndex((value) =>
                value === null ? 0 : Math.min(candles.length - 1, value + 1),
              )
            }
            disabled={candles.length === 0 || cursorIndex === null || cursorIndex >= candles.length - 1}
          >
            Step forward
          </button>
          <button
            type="button"
            className="toolButton"
            onClick={() => {
              setPlaying(false);
              setCursorIndex(candles.length > 0 ? candles.length - 1 : null);
            }}
            disabled={candles.length === 0}
          >
            Jump to end
          </button>
        </div>

        <div className="replaySliderWrap">
          <div className="replaySliderMeta">
            <span>Bar {cursorIndex === null ? 0 : cursorIndex + 1} / {candles.length}</span>
            <strong>{focusTime(focusCandle)}</strong>
          </div>
          <input
            type="range"
            min={0}
            max={Math.max(0, candles.length - 1)}
            value={Math.max(0, cursorIndex ?? 0)}
            onChange={(event) => {
              setPlaying(false);
              setCursorIndex(Number(event.target.value));
            }}
            className="replaySlider"
            disabled={candles.length === 0}
          />
        </div>
      </section>

      <TradingChart
        candles={candles}
        signal={null}
        position={null}
        symbol={symbol}
        timeframe={timeframe}
        cursorIndex={cursorIndex}
      />
    </main>
  );
}
