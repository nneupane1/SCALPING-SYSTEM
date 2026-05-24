"""Console dashboards and command-line presentation helpers."""

from .dashboard import CommandDashboard
from .viewer import start_backtest_viewer_launcher

__all__ = ["CommandDashboard", "start_backtest_viewer_launcher"]
