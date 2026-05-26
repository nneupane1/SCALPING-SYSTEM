import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type RunMode = "backtest" | "replay";

type RunRequest = {
  mode?: RunMode;
  symbol?: string;
  symbols?: string;
  startDate?: string;
  endDate?: string;
  steps?: number;
};

type RunRegistry = Partial<Record<RunMode, { pid: number; startedAt: string; command: string[] }>>;

function resolveRepoRoot(): string {
  const candidates = [
    process.cwd(),
    path.resolve(process.cwd(), ".."),
    path.resolve(process.cwd(), "../.."),
  ];
  for (const candidate of candidates) {
    if (
      fs.existsSync(path.join(candidate, "main_backtest.py")) &&
      fs.existsSync(path.join(candidate, "frontend"))
    ) {
      return candidate;
    }
  }
  return path.resolve(process.cwd(), "..");
}

function registryPath(repoRoot: string): string {
  return path.join(repoRoot, "frontend", ".research-runners.json");
}

function logPath(repoRoot: string): string {
  return path.join(repoRoot, "frontend", ".research-viewer.log");
}

function readRegistry(repoRoot: string): RunRegistry {
  const filePath = registryPath(repoRoot);
  if (!fs.existsSync(filePath)) {
    return {};
  }
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8")) as RunRegistry;
  } catch {
    return {};
  }
}

function writeRegistry(repoRoot: string, registry: RunRegistry): void {
  fs.writeFileSync(registryPath(repoRoot), JSON.stringify(registry, null, 2));
}

function isPidAlive(pid: number | undefined): boolean {
  if (!pid) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function sanitizeRegistry(registry: RunRegistry): RunRegistry {
  const cleaned: RunRegistry = {};
  for (const mode of ["backtest", "replay"] as const) {
    const entry = registry[mode];
    if (entry && isPidAlive(entry.pid)) {
      cleaned[mode] = entry;
    }
  }
  return cleaned;
}

export async function POST(request: Request) {
  const repoRoot = resolveRepoRoot();
  const payload = (await request.json()) as RunRequest;
  const mode = payload.mode;
  if (mode !== "backtest" && mode !== "replay") {
    return Response.json({ error: "mode must be backtest or replay" }, { status: 400 });
  }

  const symbol = (payload.symbol ?? "BTCUSDT").toUpperCase();
  const symbols = String(payload.symbols ?? "")
    .split(",")
    .map((value) => value.trim().toUpperCase())
    .filter(Boolean)
    .filter((value, index, array) => array.indexOf(value) === index);
  const startDate = payload.startDate;
  const endDate = payload.endDate;
  if (!startDate || !endDate) {
    return Response.json({ error: "startDate and endDate are required" }, { status: 400 });
  }

  const registry = sanitizeRegistry(readRegistry(repoRoot));
  if (registry[mode]) {
    return Response.json(
      {
        error: `${mode} is already running under pid ${registry[mode]!.pid}. Stop it before launching another run.`,
      },
      { status: 409 },
    );
  }

  const pythonExecutable = process.env.PYTHON_EXECUTABLE || "python";
  const command =
    mode === "backtest"
      ? [
          "main_backtest.py",
          "--no-viewer",
          ...(symbols.length > 0
            ? ["--symbols", symbols.join(",")]
            : ["--symbol", symbol]),
          "--start-date",
          startDate,
          "--end-date",
          endDate,
        ]
      : [
          "main_replay.py",
          "--symbol",
          symbol,
          "--start-date",
          startDate,
          "--end-date",
          endDate,
          "--steps",
          String(Math.max(10, Number(payload.steps ?? 500))),
        ];

  const outFd = fs.openSync(logPath(repoRoot), "a");
  const child = spawn(pythonExecutable, command, {
    cwd: repoRoot,
    detached: true,
    stdio: ["ignore", outFd, outFd],
    windowsHide: true,
    env: process.env,
  });
  child.unref();

  const nextRegistry = sanitizeRegistry({
    ...registry,
    [mode]: {
      pid: child.pid ?? -1,
      startedAt: new Date().toISOString(),
      command: [pythonExecutable, ...command],
    },
  });
  writeRegistry(repoRoot, nextRegistry);

  return Response.json({
    ok: true,
    pid: child.pid,
    message:
      mode === "backtest"
        ? `${mode} launched for ${symbols.length > 0 ? symbols.join(", ") : symbol} | ${startDate} -> ${endDate}`
        : `${mode} launched for ${symbol} | ${startDate} -> ${endDate}`,
  });
}
