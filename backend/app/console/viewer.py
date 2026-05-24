"""Helpers for opening the local backtest viewer automatically."""

from __future__ import annotations

import shutil
import socket
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen

def start_backtest_viewer_launcher(
    *,
    emit: Callable[[str], None] | None = None,
    url: str = "http://127.0.0.1:3000/backtest",
    repo_root: Path | None = None,
    timeout_seconds: float = 60.0,
) -> None:
    """Launch the Next.js backtest viewer in the background and open a browser."""

    thread = threading.Thread(
        target=_launch_backtest_viewer,
        kwargs={
            "emit": emit,
            "url": url,
            "repo_root": repo_root,
            "timeout_seconds": timeout_seconds,
        },
        daemon=True,
        name="backtest-viewer-launcher",
    )
    thread.start()


def _launch_backtest_viewer(
    *,
    emit: Callable[[str], None] | None,
    url: str,
    repo_root: Path | None,
    timeout_seconds: float,
) -> None:
    root = repo_root or Path(__file__).resolve().parents[3]
    frontend_dir = root / "frontend"

    if _url_ready(url):
        _notify(emit, f"Backtest viewer already available at {url}; opening browser.")
        webbrowser.open(url, new=2)
        return

    npm_exec = _find_npm()
    if npm_exec is None:
        _notify(emit, "Viewer auto-open skipped because npm is not available on PATH.")
        return

    if not frontend_dir.exists():
        _notify(emit, f"Viewer auto-open skipped because frontend directory is missing: {frontend_dir}")
        return

    if not (frontend_dir / "node_modules").exists():
        _notify(emit, f"Viewer auto-open skipped because frontend dependencies are not installed in {frontend_dir}.")
        return

    log_path = frontend_dir / ".backtest-viewer.log"
    if not _port_open("127.0.0.1", 3000):
        _notify(emit, "Starting local backtest viewer server on http://127.0.0.1:3000/backtest")
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"\n\n=== viewer launch {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            subprocess.Popen(
                [npm_exec, "run", "dev"],
                cwd=frontend_dir,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=_creation_flags(),
                start_new_session=_start_new_session(),
            )
    else:
        _notify(emit, "Port 3000 is already open; waiting for /backtest to become available.")

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _url_ready(url):
            _notify(emit, f"Opening backtest viewer at {url}")
            webbrowser.open(url, new=2)
            return
        time.sleep(1.0)

    _notify(emit, f"Viewer server did not become ready within {int(timeout_seconds)}s. Start it manually from frontend/.")


def _notify(emit: Callable[[str], None] | None, message: str) -> None:
    if emit is not None:
        emit(message)


def _find_npm() -> str | None:
    for candidate in ("npm", "npm.cmd", "npm.exe"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.75)
        return sock.connect_ex((host, port)) == 0


def _url_ready(url: str) -> bool:
    try:
        with urlopen(url, timeout=1.5) as response:  # noqa: S310 - local operator URL only
            return 200 <= response.status < 300
    except (OSError, URLError):
        return False


def _creation_flags() -> int:
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP") and hasattr(subprocess, "DETACHED_PROCESS"):
        return subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    return 0


def _start_new_session() -> bool:
    return not hasattr(subprocess, "DETACHED_PROCESS")
