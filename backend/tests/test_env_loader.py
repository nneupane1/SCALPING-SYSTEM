from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.app.config import load_env_file, load_env_files


class EnvLoaderTests(unittest.TestCase):
    def test_secret_env_overrides_base_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / ".env"
            secret = Path(tmpdir) / "secret.env"
            base.write_text("BINANCE_API_KEY=base-key\nTRADING_SYSTEM_MODE=paper\n", encoding="utf-8")
            secret.write_text("BINANCE_API_KEY=secret-key\n", encoding="utf-8")

            original_key = os.environ.get("BINANCE_API_KEY")
            original_mode = os.environ.get("TRADING_SYSTEM_MODE")
            os.environ.pop("BINANCE_API_KEY", None)
            os.environ.pop("TRADING_SYSTEM_MODE", None)
            try:
                load_env_files((base, secret))
                self.assertEqual("secret-key", os.environ.get("BINANCE_API_KEY"))
                self.assertEqual("paper", os.environ.get("TRADING_SYSTEM_MODE"))
            finally:
                self._restore("BINANCE_API_KEY", original_key)
                self._restore("TRADING_SYSTEM_MODE", original_mode)

    def test_default_stack_loads_dot_env_then_secret_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = Path.cwd()
            base = Path(tmpdir) / ".env"
            secret = Path(tmpdir) / "secret.env"
            base.write_text("BINANCE_SSL_VERIFY=true\n", encoding="utf-8")
            secret.write_text("BINANCE_SSL_VERIFY=false\n", encoding="utf-8")

            original_verify = os.environ.get("BINANCE_SSL_VERIFY")
            os.environ.pop("BINANCE_SSL_VERIFY", None)
            try:
                os.chdir(tmpdir)
                load_env_file()
                self.assertEqual("false", os.environ.get("BINANCE_SSL_VERIFY"))
            finally:
                os.chdir(original_cwd)
                self._restore("BINANCE_SSL_VERIFY", original_verify)

    @staticmethod
    def _restore(name: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
