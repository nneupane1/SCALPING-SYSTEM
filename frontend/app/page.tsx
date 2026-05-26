import Image from "next/image";
import Link from "next/link";

const routeCards = [
  {
    href: "/backtest",
    eyebrow: "Research",
    title: "Backtest Cinema",
    copy: "Portfolio run, symbol drilldown, gap guards, real-time audit.",
    accent: "Historical command deck",
  },
  {
    href: "/replay",
    eyebrow: "Audit",
    title: "Replay Lab",
    copy: "Step through one symbol bar by bar and inspect timing honestly.",
    accent: "Forensic tape review",
  },
  {
    href: "/dashboard?mode=paper",
    eyebrow: "Forward",
    title: "Paper Desk",
    copy: "Monitor simulated live execution without touching the exchange.",
    accent: "Session-aware dry run",
  },
  {
    href: "/dashboard?mode=live",
    eyebrow: "Execution",
    title: "Live Desk",
    copy: "Broker-aware forward runtime with the same decision engine.",
    accent: "Production posture",
  },
];

const quickMetrics = [
  { label: "Brand", value: "QuantFund AI" },
  { label: "Execution", value: "5m" },
  { label: "Trigger", value: "1m honest clock" },
  { label: "Sessions", value: "London + NY" },
];

const quickLaunch = [
  "python main_download_watchlist.py",
  "python main_backtest.py",
  "cd frontend && npm run dev",
];

const workflow = [
  "Download the watchlist",
  "Run the backtest",
  "Inspect the cinema",
  "Replay the best and worst days",
];

export default function HomePage() {
  return (
    <main className="shell stack homeShell">
      <section className="homeHero homeHeroQuant">
        <div className="homeHeroLead homeHeroLeadQuant">
          <div className="homeRibbon">
            <span className="homeRibbonLabel">QuantFund AI</span>
            <span className="homeRibbonDivider" />
            <span className="homeRibbonText">Research cockpit</span>
          </div>

          <div className="homeHeroHeadline">
            <h1>Run the desk from one clean cockpit.</h1>
            <p className="homeHeroCopy">
              Multi-symbol research, replay, paper, and live views without the noise of a
              cluttered dev shell.
            </p>
          </div>

          <div className="homeActionRow">
            <Link href="/backtest" className="homePrimaryLink">
              Open Backtest Cinema
            </Link>
            <Link href="/replay" className="homeSecondaryLink">
              Open Replay Lab
            </Link>
          </div>

          <div className="homeMetricStrip">
            {quickMetrics.map((metric) => (
              <div className="homeMetricChip" key={metric.label}>
                <span>{metric.label}</span>
                <strong>{metric.value}</strong>
              </div>
            ))}
          </div>
        </div>

        <div className="homeVisualCard">
          <div className="homeVisualFrame">
            <Image
              src="/brand/quantfund-ai-hero.png"
              alt="QuantFund AI cinematic trading cockpit"
              fill
              priority
              sizes="(max-width: 960px) 100vw, 42vw"
              className="homeVisualImage"
            />
            <div className="homeVisualOverlay">
              <div className="homeVisualBadge">
                <span>QuantFund AI</span>
                <strong>Mission Control</strong>
              </div>
              <div className="homeVisualBadge">
                <span>Watchlist model</span>
                <strong>Scan many, trade few</strong>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="homeCommandBand">
        <div className="homeCompactPanel">
          <div className="homeCompactHeader">
            <span className="homePanelEyebrow">Quick launch</span>
            <strong>Shortest path into research</strong>
          </div>
          <div className="homeCompactList">
            {quickLaunch.map((command) => (
              <div className="homeCommandRow homeCommandRowCompact" key={command}>
                <span className="homePrompt">$</span>
                <code>{command}</code>
              </div>
            ))}
          </div>
        </div>

        <div className="homeCompactPanel">
          <div className="homeCompactHeader">
            <span className="homePanelEyebrow">Workflow</span>
            <strong>What to do next</strong>
          </div>
          <div className="homeFlowRail">
            {workflow.map((step, index) => (
              <div className="homeFlowStep" key={step}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{step}</strong>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="homeRouteGrid homeRouteGridCompact">
        {routeCards.map((card) => (
          <Link href={card.href} className="homeRouteCard homeRouteCardQuant" key={card.href}>
            <div className="homeRouteTop">
              <span className="homePanelEyebrow">{card.eyebrow}</span>
              <span className="homeRouteBadge">{card.accent}</span>
            </div>
            <h2>{card.title}</h2>
            <p>{card.copy}</p>
            <div className="homeRouteFoot">
              <span>Open</span>
              <strong>{card.href}</strong>
            </div>
          </Link>
        ))}
      </section>
    </main>
  );
}
