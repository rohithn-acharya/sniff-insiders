"""
utils/logger.py
Rich-based structured logger for all agents.
"""

from rich.console import Console
from rich.theme import Theme
from datetime import datetime

_theme = Theme({
    "info":    "cyan",
    "success": "bold green",
    "warn":    "bold yellow",
    "error":   "bold red",
    "signal":  "bold magenta",
    "agent":   "bold blue",
})

console = Console(theme=_theme)


def log(agent: str, msg: str, level: str = "info"):
    ts = datetime.now().strftime("%H:%M:%S")
    console.print(f"[{level}][{ts}] [{agent}][/{level}] {msg}")


def log_signal(ticker: str, direction: str, score: float, reason: str):
    console.rule(f"[signal]🚨 SIGNAL: {ticker} — {direction} (score={score:.2f})[/signal]")
    console.print(f"  [dim]{reason}[/dim]")
    console.rule()
