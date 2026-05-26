"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type ResearchCommandDeckProps = {
  symbolScope: string;
  symbols: string[];
  activeSymbol: string;
  executionTimeframe: string;
  clockTimeframe: string;
  triggerTimeframe: string;
  defaultStartDate: string | null;
  defaultEndDate: string | null;
  recommendedUniverse: string[];
  selectionPolicy: string;
};

function toDateInput(value: string | null): string {
  if (!value) {
    return "";
  }
  return value.slice(0, 10);
}

function toRunnerDate(value: string): string {
  return `${value} 00:00:00`;
}

export function ResearchCommandDeck({
  symbolScope,
  symbols,
  activeSymbol: initialActiveSymbol,
  executionTimeframe,
  clockTimeframe,
  triggerTimeframe,
  defaultStartDate,
  defaultEndDate,
  recommendedUniverse,
  selectionPolicy,
}: ResearchCommandDeckProps) {
  const router = useRouter();
  const [watchlist, setWatchlist] = useState(symbols.join(","));
  const [replaySymbol, setReplaySymbol] = useState(initialActiveSymbol);
  const [startDate, setStartDate] = useState(toDateInput(defaultStartDate));
  const [endDate, setEndDate] = useState(toDateInput(defaultEndDate));
  const [replaySteps, setReplaySteps] = useState("500");
  const [busyMode, setBusyMode] = useState<"backtest" | "replay" | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const backtestStart = startDate ? toRunnerDate(startDate) : null;
  const backtestEnd = endDate ? toRunnerDate(endDate) : null;
  const normalizedWatchlist = watchlist
    .split(",")
    .map((value) => value.trim().toUpperCase())
    .filter(Boolean)
    .filter((value, index, array) => array.indexOf(value) === index);
  const resolvedReplaySymbol = (replaySymbol || normalizedWatchlist[0] || "BTCUSDT").toUpperCase();
  const legacyUniverse = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT"];
  const applyUniverse = (universe: string[]) => {
    const joined = universe.join(",");
    setWatchlist(joined);
    setReplaySymbol(universe[0] ?? "BTCUSDT");
  };

  const launch = async (mode: "backtest" | "replay") => {
    if (!backtestStart || !backtestEnd) {
      setMessage("Select both start and end dates first.");
      return;
    }
    if (mode === "backtest" && normalizedWatchlist.length === 0) {
      setMessage("Provide at least one symbol in the watchlist.");
      return;
    }

    setBusyMode(mode);
    setMessage(null);
    try {
      const response = await fetch("/api/research/run", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          mode,
          symbol: resolvedReplaySymbol,
          symbols: mode === "backtest" ? normalizedWatchlist.join(",") : undefined,
          startDate: backtestStart,
          endDate: backtestEnd,
          steps: mode === "replay" ? Number(replaySteps || "500") : undefined,
        }),
      });
      const payload = (await response.json()) as { message?: string; error?: string };
      if (!response.ok) {
        throw new Error(payload.error ?? "Launch failed");
      }
      setMessage(payload.message ?? `${mode} launched.`);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Launch failed");
    } finally {
      setBusyMode(null);
    }
  };

  return (
    <section className="btPanel researchDock">
      <div className="btPanelHeader">
        <div>
          <h3>Research Control</h3>
          <p>Launch runs fast. Keep the timing model honest.</p>
        </div>
      </div>

      <div className="researchGrid">
        <label className="researchField">
          <span>Watchlist symbols</span>
          <input
            value={watchlist}
            onChange={(event) => setWatchlist(event.target.value.toUpperCase())}
            className="researchInput"
          />
          <small className="subtle">
            Diversify the scan universe. Let the selector prune by evidence.
          </small>
        </label>
        <label className="researchField">
          <span>Replay focus symbol</span>
          <input
            value={replaySymbol}
            onChange={(event) => setReplaySymbol(event.target.value.toUpperCase())}
            className="researchInput"
          />
          <small className="subtle">
            Replay stays single-symbol so the tape stays readable.
          </small>
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
        <label className="researchField">
          <span>Replay steps</span>
          <input
            type="number"
            min="10"
            step="10"
            value={replaySteps}
            onChange={(event) => setReplaySteps(event.target.value)}
            className="researchInput"
          />
        </label>
      </div>

      <div className="researchMetaRow">
        <div className="researchMetaCard">
          <span>Execution layer</span>
          <strong>{executionTimeframe}</strong>
        </div>
        <div className="researchMetaCard">
          <span>Clock layer</span>
          <strong>{clockTimeframe}</strong>
        </div>
        <div className="researchMetaCard">
          <span>Trigger layer</span>
          <strong>{triggerTimeframe}</strong>
        </div>
        <div className="researchMetaCard">
          <span>Logic contract</span>
          <strong>Arm on {executionTimeframe}, fire on {triggerTimeframe}</strong>
        </div>
        <div className="researchMetaCard">
          <span>Watchlist scope</span>
          <strong>{symbolScope}</strong>
        </div>
        <div className="researchMetaCard">
          <span>Chart focus</span>
          <strong>{resolvedReplaySymbol}</strong>
        </div>
        <div className="researchMetaCard">
          <span>Session model</span>
          <strong>London + New York primary</strong>
        </div>
        <div className="researchMetaCard">
          <span>Range preset</span>
          <strong>Entire downloaded history by default</strong>
        </div>
      </div>

      <div className="researchPresetRow">
        <button
          type="button"
          className="researchGhostButton"
          onClick={() => applyUniverse(recommendedUniverse)}
        >
          Use evidence-pruned universe
        </button>
        <button
          type="button"
          className="researchGhostButton"
          onClick={() => applyUniverse(legacyUniverse)}
        >
          Load legacy L1 basket
        </button>
        <span className="subtle">{selectionPolicy}</span>
      </div>

      <div className="researchActionRow">
        <button
          type="button"
          className="researchPrimaryButton"
          onClick={() => launch("backtest")}
          disabled={busyMode !== null}
        >
          {busyMode === "backtest" ? "Launching backtest..." : "Run Backtest"}
        </button>
        <button
          type="button"
          className="researchSecondaryButton"
          onClick={() =>
            router.push(
              `/replay?symbol=${encodeURIComponent(resolvedReplaySymbol)}&timeframe=${encodeURIComponent(
                executionTimeframe,
              )}&start=${encodeURIComponent(backtestStart ?? "")}&end=${encodeURIComponent(
                backtestEnd ?? "",
              )}`,
            )
          }
        >
          Open Replay Workspace
        </button>
        <button
          type="button"
          className="researchGhostButton"
          onClick={() => launch("replay")}
          disabled={busyMode !== null}
        >
          {busyMode === "replay" ? "Launching replay..." : "Run Replay Job"}
        </button>
      </div>

      <div className="researchFooter">
        <span>
          Backtest uses the full watchlist. Replay uses one focus symbol. Session gating still comes from config.
        </span>
        {message ? <strong>{message}</strong> : null}
      </div>
    </section>
  );
}
