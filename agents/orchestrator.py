"""
agents/orchestrator.py

Orchestrator — the master agent that:
  1. Schedules and runs all sub-agents in the right order
  2. Manages the data pipeline: EDGAR → Insider → News → Correlation
  3. Can run once (CLI) or on a schedule (daemon mode)
  4. Produces a final report

Pipeline flow:
  ┌─────────────┐     ┌──────────────┐     ┌────────────┐
  │ EDGAR Agent │────▶│ Insider Agent│────▶│            │
  └─────────────┘     └──────────────┘     │ Correlation│──▶ Alerts
  ┌─────────────┐                          │   Agent    │
  │  News Agent │─────────────────────────▶│            │
  └─────────────┘                          └────────────┘
"""

import argparse
import schedule
import time
from datetime import datetime

from config.settings import DEFAULT_TICKERS, POLL_INTERVAL_MINUTES
from data.db import init_db
from utils.logger import log

import agents.edgar_agent       as edgar_agent
import agents.insider_agent     as insider_agent
import agents.news_agent        as news_agent
import agents.correlation_agent as correlation_agent
import reports.report_generator as report_generator

AGENT = "ORCHESTRATOR"


def run_pipeline(tickers: list[str], days: int = 30) -> dict:
    """
    Execute the full multi-agent pipeline for a list of tickers.
    Returns the final correlation results.
    """
    start = datetime.now()
    log(AGENT, f"{'='*60}", "agent")
    log(AGENT, f"Pipeline START — {len(tickers)} tickers | lookback={days}d", "agent")
    log(AGENT, f"{'='*60}", "agent")

    # ── Phase 1: Fetch SEC filings ─────────────────────────────────────────
    log(AGENT, "Phase 1: EDGAR Agent — fetching filings", "info")
    edgar_results = edgar_agent.run(tickers)

    # ── Phase 2: Analyze insider transactions ──────────────────────────────
    log(AGENT, "Phase 2: Insider Agent — analyzing transactions", "info")
    insider_results = insider_agent.run(tickers, days=days)

    # ── Phase 3: Fetch news & geopolitical signals ─────────────────────────
    log(AGENT, "Phase 3: News Agent — fetching market & geo news", "info")
    news_result = news_agent.run(watchlist=tickers)

    # ── Phase 4: Correlate & score ─────────────────────────────────────────
    log(AGENT, "Phase 4: Correlation Agent — synthesizing signals", "info")
    final_signals = correlation_agent.run(tickers, insider_results, news_result)

    # ── Phase 5: Generate reports ──────────────────────────────────────────────
    log(AGENT, "Phase 5: Report Generator — saving outputs", "info")
    report_generator.run(final_signals)

    elapsed = (datetime.now() - start).total_seconds()
    log(AGENT, f"Pipeline COMPLETE in {elapsed:.1f}s", "success")

    return final_signals


def _scheduled_run(tickers: list[str]):
    """Wrapper for scheduled execution."""
    log(AGENT, f"Scheduled run triggered at {datetime.now().isoformat()}", "info")
    try:
        run_pipeline(tickers)
    except Exception as e:
        log(AGENT, f"Pipeline error: {e}", "error")


def main():
    parser = argparse.ArgumentParser(
        description="Sniff Insiders — Multi-Agent Insider Signal Detector"
    )
    parser.add_argument(
        "--tickers", nargs="+", default=DEFAULT_TICKERS,
        help="Ticker symbols to watch (default: built-in watchlist)"
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Lookback window in days for insider transactions"
    )
    parser.add_argument(
        "--daemon", action="store_true",
        help="Run continuously on a schedule instead of once"
    )
    parser.add_argument(
        "--interval", type=int, default=POLL_INTERVAL_MINUTES,
        help="Poll interval in minutes (daemon mode only)"
    )
    args = parser.parse_args()

    # Ensure DB is ready
    init_db()

    if args.daemon:
        log(AGENT, f"Daemon mode: running every {args.interval} minutes", "agent")
        # Run immediately on start
        _scheduled_run(args.tickers)
        # Then schedule
        schedule.every(args.interval).minutes.do(_scheduled_run, tickers=args.tickers)
        while True:
            schedule.run_pending()
            time.sleep(30)
    else:
        run_pipeline(args.tickers, days=args.days)


if __name__ == "__main__":
    main()
