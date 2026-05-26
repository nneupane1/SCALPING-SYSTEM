import Link from "next/link";

const routeCards = [
  {
    href: "/backtest",
    eyebrow: "Research deck",
    title: "Backtest Cinema",
    copy:
      "Run a watchlist as one portfolio, then pivot between symbol tapes with aggregate equity, gap guards, trade overlays, and execution telemetry.",
    badge: "Portfolio + symbol drilldown",
  },
  {
    href: "/dashboard",
    eyebrow: "Operator desk",
    title: "Live Dashboard",
    copy:
      "One-screen command view for scanner state, signal posture, active risk, and the shape of the session in motion.",
    badge: "Execution surface",
  },
  {
    href: "/replay",
    eyebrow: "Decision audit",
    title: "Replay Lab",
    copy:
      "Slow the same engine down candle by candle and inspect whether structure, timing, and management still hold under scrutiny.",
    badge: "Forensic mode",
  },
  {
    href: "/portfolio",
    eyebrow: "Capital memory",
    title: "Portfolio Frame",
    copy:
      "Track how realized PnL, drawdown, streaks, and trade archetypes accumulate into a distribution you can actually trust.",
    badge: "Performance state",
  },
];

const launchCommands = [
  "python main_download_watchlist.py",
  "python main_backtest.py --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,AVAXUSDT",
  "python main_paper.py",
  "python main_live.py",
  "cd frontend && npm run dev",
];

const systemTiles = [
  { label: "Canonical tape", value: "1m 24/7", detail: "All higher frames rebuilt internally." },
  { label: "Execution clock", value: "5m", detail: "Momentum, pullback, resumption." },
  { label: "Context lens", value: "15m", detail: "Soft alignment, not hard domination." },
  { label: "Watchlist model", value: "5 symbols", detail: "Scan many, execute the best few." },
  { label: "Primary sessions", value: "London + NY", detail: "Berlin-time session gating." },
];

export default function HomePage() {
  return (
    <main className="shell stack homeShell">
      <section className="homeHero">
        <div className="homeHeroLead">
          <div className="homeRibbon">
            <span className="homeRibbonLabel">Scalping Operating System</span>
            <span className="homeRibbonDivider" />
            <span className="homeRibbonText">Research, replay, paper, live</span>
          </div>
          <h1>Build edge like a desk, not like a notebook.</h1>
          <p className="homeHeroCopy">
            The system is no longer just a backend runner. It now has a gap-aware research
            stack, a multi-symbol backtest cockpit, structured session filters, and an
            execution path built around one canonical market tape.
          </p>
          <div className="homeActionRow">
            <Link href="/backtest" className="homePrimaryLink">
              Open Backtest Cinema
            </Link>
            <Link href="/dashboard" className="homeSecondaryLink">
              Open Live Dashboard
            </Link>
          </div>
        </div>

        <aside className="homeCommandPanel">
          <div className="homeCommandHeader">
            <span className="homePanelEyebrow">Launch rail</span>
            <strong>Fastest way to get moving</strong>
          </div>
          <div className="homeCommandList">
            {launchCommands.map((command) => (
              <div className="homeCommandRow" key={command}>
                <span className="homePrompt">$</span>
                <code>{command}</code>
              </div>
            ))}
          </div>
          <div className="homeCommandFooter">
            <div>
              <span>Default route</span>
              <strong>Backtest first, refine second</strong>
            </div>
            <div>
              <span>Viewer</span>
              <strong>http://localhost:3000/backtest</strong>
            </div>
          </div>
        </aside>
      </section>

      <section className="homeTickerBand">
        <div className="homeTicker">
          <span>Canonical 1m stream</span>
          <span>Watchlist backtests with top-N execution</span>
          <span>Gap-aware backtesting</span>
          <span>London + New York execution windows</span>
          <span>5m execution / 15m context</span>
          <span>Partial at +1R, runner by structure</span>
          <span>Viewer auto-opens from CLI</span>
        </div>
      </section>

      <section className="homeSystemStrip">
        {systemTiles.map((tile) => (
          <article className="homeSystemTile" key={tile.label}>
            <span>{tile.label}</span>
            <strong>{tile.value}</strong>
            <p>{tile.detail}</p>
          </article>
        ))}
      </section>

      <section className="homeRouteGrid">
        {routeCards.map((card) => (
          <Link href={card.href} className="homeRouteCard" key={card.href}>
            <div className="homeRouteTop">
              <span className="homePanelEyebrow">{card.eyebrow}</span>
              <span className="homeRouteBadge">{card.badge}</span>
            </div>
            <h2>{card.title}</h2>
            <p>{card.copy}</p>
            <div className="homeRouteFoot">
              <span>Open route</span>
              <strong>{card.href}</strong>
            </div>
          </Link>
        ))}
      </section>

      <section className="homeLowerGrid">
        <section className="homeStatementPanel">
          <div className="homePanelHeader">
            <div>
              <span className="homePanelEyebrow">Why this feels different</span>
              <h3>One market narrative, multiple operating modes.</h3>
            </div>
          </div>
          <div className="homeStatementList">
            <div className="homeStatementRow">
              <strong>Research path</strong>
              <p>
                Historical `1m` data is downloaded once, repaired, audited, rebuilt into `5m`
                and `15m`, then replayed through the same engine that drives paper and live.
              </p>
            </div>
            <div className="homeStatementRow">
              <strong>Execution discipline</strong>
              <p>
                The system enters only after structure proves continuation, takes partial at
                `+1R`, kills risk early, and lets the runner earn the right to stay alive.
              </p>
            </div>
            <div className="homeStatementRow">
              <strong>Operator visibility</strong>
              <p>
                Console dashboards, gap ledgers, rejection counters, and the cinematic
                backtest viewer all exist for one reason: you should always know what the
                engine is doing and why.
              </p>
            </div>
          </div>
        </section>

        <section className="homeSignalPanel">
          <div className="homePanelHeader">
            <div>
              <span className="homePanelEyebrow">Current stack</span>
              <h3>What the platform now contains</h3>
            </div>
          </div>
          <div className="homeSignalGrid">
            <div className="homeSignalCard">
              <span>Scanner</span>
              <strong>Impulse quality + pullback structure</strong>
            </div>
            <div className="homeSignalCard">
              <span>Strategy</span>
              <strong>Session-aware, context-shaped execution</strong>
            </div>
            <div className="homeSignalCard">
              <span>Backtest</span>
              <strong>Checkpointed, gap-aware, viewer-linked</strong>
            </div>
            <div className="homeSignalCard">
              <span>Frontend</span>
              <strong>From mock shell to live backtest cockpit</strong>
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}
