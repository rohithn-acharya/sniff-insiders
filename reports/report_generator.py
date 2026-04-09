"""
reports/report_generator.py

Generates structured signal reports from correlation results.
Supports:
  - Rich console tables (already handled inline by correlation_agent)
  - Plaintext summary for logging / email
  - JSON export for downstream consumers
"""

import json
import os
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from data.db import get_latest_signals
from utils.logger import log

AGENT = "REPORTER"

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "reports")


def _ensure_reports_dir():
    os.makedirs(REPORTS_DIR, exist_ok=True)


# ── Formatters ────────────────────────────────────────────────────────────────

def _direction_color(direction: str) -> str:
    return {"BULLISH": "green", "BEARISH": "red"}.get(direction, "yellow")


def print_console_report(signals: dict[str, dict]):
    """Print a rich formatted report to the terminal."""
    c = Console()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    c.print(Panel(f"[bold]Sniff Insiders — Signal Report[/bold]\n[dim]{ts}[/dim]",
                  expand=False))

    table = Table(show_lines=True, header_style="bold white on dark_blue")
    table.add_column("Ticker",    style="bold cyan", width=8)
    table.add_column("Direction", width=10)
    table.add_column("Score",     justify="right", width=7)
    table.add_column("Insider",   justify="right", width=8)
    table.add_column("Geo ∆",     justify="right", width=7)
    table.add_column("Reasoning")

    ranked = sorted(signals.values(), key=lambda x: x["score"], reverse=True)
    for s in ranked:
        color     = _direction_color(s["direction"])
        insider_s = s.get("components", {}).get("insider_score", 0.0)
        geo_s     = s.get("components", {}).get("geo_impact", 0.0)
        reasoning = (s.get("reasoning") or "")[:90]
        if len(s.get("reasoning") or "") > 90:
            reasoning += "…"

        table.add_row(
            s["ticker"],
            f"[{color}]{s['direction']}[/{color}]",
            f"{s['score']:.2f}",
            f"{insider_s:+.2f}",
            f"{geo_s:+.2f}",
            reasoning,
        )

    c.print(table)


def generate_text_report(signals: dict[str, dict]) -> str:
    """Return a plaintext summary suitable for email or logging."""
    lines = [
        "=" * 60,
        f"SNIFF INSIDERS — SIGNAL REPORT  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 60,
    ]

    ranked = sorted(signals.values(), key=lambda x: x["score"], reverse=True)
    alerts = [s for s in ranked if s["score"] >= 0.60]

    if alerts:
        lines.append(f"\n🚨 ALERTS ({len(alerts)} ticker(s) above threshold):\n")
        for s in alerts:
            lines.append(f"  {s['ticker']:6s}  {s['direction']:7s}  score={s['score']:.2f}")
            if s.get("reasoning"):
                lines.append(f"         {s['reasoning'][:100]}")
    else:
        lines.append("\nNo tickers above alert threshold this run.")

    lines.append("\nFull leaderboard:\n")
    for s in ranked:
        lines.append(f"  {s['ticker']:6s}  {s['direction']:7s}  {s['score']:.2f}")

    lines.append("=" * 60)
    return "\n".join(lines)


def generate_json_report(signals: dict[str, dict]) -> dict:
    """Return a structured dict ready for json.dumps."""
    return {
        "generated_at": datetime.now().isoformat(),
        "signal_count":  len(signals),
        "alerts":        [s for s in signals.values() if s["score"] >= 0.60],
        "signals":       list(signals.values()),
    }


# ── Persistence ───────────────────────────────────────────────────────────────

def save_json_report(signals: dict[str, dict], filename: Optional[str] = None) -> str:
    """Write a JSON report to disk and return the file path."""
    _ensure_reports_dir()
    if not filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"signal_report_{ts}.json"

    path = os.path.join(REPORTS_DIR, filename)
    report = generate_json_report(signals)
    with open(path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    log(AGENT, f"JSON report saved → {path}", "success")
    return path


def save_text_report(signals: dict[str, dict], filename: Optional[str] = None) -> str:
    """Write a plaintext report to disk and return the file path."""
    _ensure_reports_dir()
    if not filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"signal_report_{ts}.txt"

    path = os.path.join(REPORTS_DIR, filename)
    with open(path, "w") as f:
        f.write(generate_text_report(signals))

    log(AGENT, f"Text report saved → {path}", "success")
    return path


# ── Entry point ───────────────────────────────────────────────────────────────

def run(signals: dict[str, dict], save: bool = True):
    """
    Generate and optionally persist all report formats.
    Called at the end of the orchestrator pipeline.
    """
    log(AGENT, "Generating reports", "agent")
    print_console_report(signals)

    if save:
        save_json_report(signals)
        save_text_report(signals)


if __name__ == "__main__":
    # Render the most recent signals from the DB
    from data.db import init_db, get_latest_signals
    init_db()

    raw = get_latest_signals(limit=50)
    # Re-hydrate signals dict keyed by ticker
    signals = {}
    for row in raw:
        import json as _json
        components = _json.loads(row.get("components") or "{}")
        signals[row["ticker"]] = {
            "ticker":     row["ticker"],
            "score":      row["score"],
            "direction":  row["direction"],
            "reasoning":  row["reasoning"],
            "components": components,
        }

    if signals:
        run(signals, save=False)
    else:
        print("No signals in DB yet. Run the orchestrator first.")
