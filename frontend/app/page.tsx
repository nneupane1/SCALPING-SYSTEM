import Link from "next/link";

export default function HomePage() {
  return (
    <main className="shell stack">
      <section className="hero">
        <span className="pill">Scalping Operating System</span>
        <h1>Observe movement. Commit only when structure regains control.</h1>
        <p className="subtle">
          This frontend is the operator surface for the backend rule engine. It is
          designed to show why the system is acting, not just what price is doing.
        </p>
        <nav className="nav">
          <Link href="/backtest">Backtest</Link>
          <Link href="/dashboard">Dashboard</Link>
          <Link href="/replay">Replay</Link>
          <Link href="/portfolio">Portfolio</Link>
        </nav>
      </section>
    </main>
  );
}
