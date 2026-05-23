import type { DashboardSnapshot } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function fetchPortfolioSnapshot(): Promise<unknown> {
  const response = await fetch(`${API_BASE}/portfolio`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to fetch portfolio snapshot: ${response.status}`);
  }
  return response.json();
}

export async function fetchHealth(): Promise<unknown> {
  const response = await fetch(`${API_BASE}/health`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to fetch health endpoint: ${response.status}`);
  }
  return response.json();
}

export function getInitialDashboardSnapshot(): DashboardSnapshot | null {
  return null;
}

