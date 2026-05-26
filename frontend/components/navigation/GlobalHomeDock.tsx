"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

function routeLabel(pathname: string): string {
  if (pathname === "/") {
    return "Mission Control";
  }
  if (pathname === "/backtest") {
    return "Backtest Cinema";
  }
  if (pathname === "/replay") {
    return "Replay Lab";
  }
  if (pathname === "/portfolio") {
    return "Portfolio Frame";
  }
  if (pathname === "/dashboard") {
    return "Forward Desk";
  }
  return "Scalping System";
}

export function GlobalHomeDock() {
  const pathname = usePathname();
  const label = routeLabel(pathname);
  const atHome = pathname === "/";

  return (
    <div className="globalHomeDock">
      <div className="globalHomeBrand">
        <span>Scalping System</span>
        <strong>{label}</strong>
      </div>
      <div className="globalHomeActions">
        <span className="globalRoutePill">{pathname === "/" ? "Hub" : pathname}</span>
        <Link href="/" className={`globalHomeLink ${atHome ? "is-home" : ""}`}>
          {atHome ? "Mission Control" : "Back to Home"}
        </Link>
      </div>
    </div>
  );
}
