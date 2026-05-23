"""Public Binance REST market-data client with retry and TLS controls."""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning

from backend.app.config import load_env_file
from backend.app.config.models import ConfigBundle


def _format_time(ms: int) -> str:
    return datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


class BinanceRestClient:
    """Small Binance REST client for public OHLCV access.

    The client keeps authenticated headers available for future expansion, but
    the current implementation is focused on public kline downloads. Retry
    behavior is driven entirely by configuration so long historical jobs remain
    restartable rather than brittle.
    """

    def __init__(
        self,
        config: ConfigBundle,
        retry_callback=None,
        session: requests.Session | None = None,
    ) -> None:
        load_env_file()
        self.config = config
        self.binance = config.system.binance
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.api_secret = os.getenv("BINANCE_API_SECRET")
        self.retry_callback = retry_callback
        self.session = session or requests.Session()
        self._warnings_configured = False
        self.klines_url = urljoin(
            self.binance.base_url.rstrip("/") + "/",
            self.binance.klines_path.lstrip("/"),
        )

    def _verify_setting(self) -> bool | str:
        env_ca_bundle = os.getenv("BINANCE_CA_BUNDLE_PATH")
        env_ssl_verify = os.getenv("BINANCE_SSL_VERIFY")

        if env_ca_bundle:
            bundle_path = Path(env_ca_bundle)
            if not bundle_path.is_absolute():
                bundle_path = Path.cwd() / bundle_path
            if not bundle_path.exists():
                raise FileNotFoundError(f"Configured CA bundle not found: {bundle_path}")
            return str(bundle_path)

        if env_ssl_verify is not None:
            lowered = env_ssl_verify.strip().lower()
            if lowered in {"false", "0", "no", "off"}:
                return False
            if lowered in {"true", "1", "yes", "on"}:
                return True
            raise ValueError(f"Invalid BINANCE_SSL_VERIFY override: {env_ssl_verify!r}")

        if self.binance.ca_bundle_path:
            bundle_path = Path(self.binance.ca_bundle_path)
            if not bundle_path.is_absolute():
                bundle_path = Path.cwd() / bundle_path
            if not bundle_path.exists():
                raise FileNotFoundError(f"Configured CA bundle not found: {bundle_path}")
            return str(bundle_path)
        return bool(self.binance.ssl_verify)

    def _configure_tls_warning_behavior(self, verify_setting: bool | str) -> None:
        if self._warnings_configured:
            return
        if verify_setting is False:
            disable_warnings(InsecureRequestWarning)
        self._warnings_configured = True

    def describe_verify_mode(self) -> str:
        verify_setting = self._verify_setting()
        if isinstance(verify_setting, str):
            return f"custom CA bundle ({verify_setting})"
        if verify_setting:
            return "enabled"
        return "disabled"

    def _retry_delay(self, attempt: int) -> float:
        return self.binance.retry_backoff_seconds * attempt

    def _emit_retry(self, attempt: int, delay: float, reason: object) -> None:
        if callable(self.retry_callback):
            self.retry_callback(
                attempt=attempt,
                total_attempts=self.binance.retry_attempts,
                delay=delay,
                reason=reason,
            )

    def get_klines(
        self,
        *,
        symbol: str | None = None,
        interval: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
        verbose: bool = True,
    ) -> list[list[object]]:
        symbol = (symbol or self.config.system.market.symbol).upper()
        interval = interval or self.binance.default_interval
        limit = limit or self.binance.historical_limit

        params: dict[str, object] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key

        verify_setting = self._verify_setting()
        self._configure_tls_warning_behavior(verify_setting)
        start_clock = time.time()

        if verbose:
            print(f"\nFetching {symbol} | {interval}")
            if start_time is not None:
                print(f"  From: {_format_time(start_time)}")
            if end_time is not None:
                print(f"  To:   {_format_time(end_time)}")
            print(f"  TLS verify: {self.describe_verify_mode()}")

        last_error: Exception | None = None
        retry_codes = set(self.binance.retry_status_codes)
        for attempt in range(1, self.binance.retry_attempts + 1):
            try:
                response = self.session.get(
                    self.klines_url,
                    params=params,
                    headers=headers,
                    timeout=self.binance.request_timeout_seconds,
                    verify=verify_setting,
                )
                if response.status_code == 200:
                    data = response.json()
                    if verbose:
                        elapsed = time.time() - start_clock
                        print(f"Received {len(data)} candles")
                        print(f"Elapsed: {elapsed:.2f} sec")
                        if data:
                            print(f"  Range: {_format_time(int(data[0][0]))} -> {_format_time(int(data[-1][0]))}")
                    return data

                last_error = Exception(
                    f"Binance API error: {response.status_code} | {response.text}"
                )
                if response.status_code not in retry_codes:
                    raise last_error
            except requests.RequestException as exc:
                last_error = exc

            if attempt < self.binance.retry_attempts:
                delay = self._retry_delay(attempt)
                self._emit_retry(attempt, delay, last_error)
                if not callable(self.retry_callback) and self.binance.retry_logging_enabled:
                    print(
                        "Binance request failed "
                        f"(attempt {attempt}/{self.binance.retry_attempts}): {last_error}"
                    )
                    print(f"Retrying in {delay:.2f}s...")
                time.sleep(delay)

        raise RuntimeError(
            f"Binance request failed after {self.binance.retry_attempts} attempts: {last_error}"
        )
