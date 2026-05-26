"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

const ITEMS = [
  {
    key: "home",
    href: "/",
    label: "Home",
    detail: "Mission control",
  },
  {
    key: "backtest",
    href: "/backtest",
    label: "Backtest",
    detail: "Historical research",
  },
  {
    key: "replay",
    href: "/replay",
    label: "Replay",
    detail: "Bar-by-bar inspection",
  },
  {
    key: "paper",
    href: "/dashboard?mode=paper",
    label: "Paper Forward",
    detail: "Simulated execution",
  },
  {
    key: "live",
    href: "/dashboard?mode=live",
    label: "Live Forward",
    detail: "Broker-aware runtime",
  },
] as const;

export function ModeSwitchRail() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const dashboardMode = searchParams.get("mode") ?? "paper";

  return (
    <nav className="modeRail" aria-label="Mode switcher">
      {ITEMS.map((item) => {
        const active =
          (item.key === "home" && pathname === "/") ||
          (item.key === "backtest" && pathname === "/backtest") ||
          (item.key === "replay" && pathname === "/replay") ||
          (pathname === "/dashboard" && dashboardMode === item.key);

        return (
          <Link
            key={item.key}
            href={item.href}
            className={`modeRailLink ${active ? "is-active" : ""}`}
          >
            <span>{item.label}</span>
            <strong>{item.detail}</strong>
          </Link>
        );
      })}
    </nav>
  );
}
