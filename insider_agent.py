"""
agents/insider_agent.py

Insider Agent — analyzes raw Form 4 transactions to detect:
  1. Insider CLUSTER buys (multiple insiders buying within short window)
  2. Large single trades above threshold
  3. CEO/CFO specific signals (higher weight)
  4. Ratio of buys to total compensation (awards vs. purchases)

Key insight: Award grants (type 'A') are routine compensation.
Real signal comes from OPEN MARKET PURCHASES ('P') — those are discretionary.
"""

from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional

from config.settings import (
    INSIDER_CLUSTER_MIN_TRADES,
    INSIDER_CLUSTER_WINDOW_DAYS,
    LARGE_TRADE_USD_THRESHOLD,
    WEIGHTS,
)
from data.db import get_recent_insider_txns
from utils.logger import log

AGENT = "INSIDER"

# Roles that carry higher signal weight
HIGH_SIGNAL_ROLES = {"CEO", "CFO", "President", "COO", "Director"}

# Transaction type meanings (SEC codes)
TX_TYPES = {
    "P": "Open Market Purchase",   # 🟢 Strong bullish signal
    "S": "Open Market Sale",       # 🔴 Bearish (but often routine)
    "A": "Award / Grant",          # ⚪ Routine — low signal
    "D": "Disposition to Issuer",  # ⚪ Often tax-related
    "F": "Tax Withholding",        # ⚪ Routine
    "G": "Gift",                   # ⚪ Neutral
    "M": "Option Exercise",        # ⚠️  Watch if large
}


def analyze_ticker(ticker: str, days: int = 30) -> dict:
    """
    Analyze insider transactions for a single ticker.
    Returns a score dict with sub-components.
    """
    txns = get_recent_insider_txns(ticker, days)

    if not txns:
        log(AGENT, f"No transactions found for {ticker}", "warn")
        return _empty_score(ticker)

    log(AGENT, f"Analyzing {len(txns)} transactions for {ticker}")

    # Filter to open market purchases and sales only
    purchases = [t for t in txns if t["transaction_type"] == "P"]
    sales      = [t for t in txns if t["transaction_type"] == "S"]

    score_components = {
        "cluster_buy_score":   _cluster_score(purchases, ticker),
        "large_buy_score":     _large_trade_score(purchases),
        "large_sell_score":    _large_trade_score(sales) * -1,  # negative signal
        "executive_buy_score": _executive_score(purchases),
        "buy_sell_ratio":      _buy_sell_ratio(purchases, sales),
    }

    # Composite insider score (0.0 to 1.0, or negative)
    raw = (
        score_components["cluster_buy_score"]   * 0.35 +
        score_components["large_buy_score"]      * 0.25 +
        score_components["executive_buy_score"]  * 0.20 +
        score_components["buy_sell_ratio"]       * 0.10 +
        score_components["large_sell_score"]     * 0.10
    )
    composite = max(-1.0, min(1.0, raw))  # clamp to [-1, 1]

    direction = (
        "BULLISH" if composite > 0.3 else
        "BEARISH" if composite < -0.3 else
        "NEUTRAL"
    )

    result = {
        "ticker":     ticker,
        "score":      composite,
        "direction":  direction,
        "components": score_components,
        "summary":    _summarize(ticker, purchases, sales, score_components),
        "raw_txns":   txns,
    }

    log(AGENT,
        f"{ticker}: score={composite:.2f} [{direction}] "
        f"buys={len(purchases)} sells={len(sales)}",
        "success")
    return result


def _cluster_score(purchases: list, ticker: str) -> float:
    """
    Detect if multiple DISTINCT insiders bought within CLUSTER_WINDOW_DAYS.
    Returns 0.0–1.0.

    Rationale: One insider buying could be noise. Three+ buying in the same
    2-week window is a strong consensus signal — they all saw something.
    """
    if not purchases:
        return 0.0

    window = timedelta(days=INSIDER_CLUSTER_WINDOW_DAYS)
    dates  = sorted([
        datetime.strptime(t["transaction_date"], "%Y-%m-%d")
        for t in purchases
        if t.get("transaction_date")
    ])

    max_cluster = 0
    for i, anchor in enumerate(dates):
        # Count distinct filers within the window starting at anchor
        filers_in_window = set()
        for j in range(i, len(dates)):
            if dates[j] - anchor <= window:
                filers_in_window.add(purchases[j].get("filer_name", f"unknown_{j}"))
            else:
                break
        max_cluster = max(max_cluster, len(filers_in_window))

    # Score: 0 insiders=0.0, MIN_TRADES insiders=0.5, 2x=1.0
    score = min(1.0, max_cluster / (INSIDER_CLUSTER_MIN_TRADES * 2))
    if max_cluster >= INSIDER_CLUSTER_MIN_TRADES:
        log(AGENT, f"🔵 Cluster detected for {ticker}: {max_cluster} insiders", "signal")
    return score


def _large_trade_score(trades: list) -> float:
    """
    Score based on presence of large-dollar open market trades.
    Returns 0.0–1.0.
    """
    if not trades:
        return 0.0

    large = [t for t in trades if (t.get("total_value") or 0) >= LARGE_TRADE_USD_THRESHOLD]
    if not large:
        return 0.0

    max_val = max(t.get("total_value", 0) for t in large)
    # Logarithmic scale: $500K = 0.5, $5M = 0.75, $50M = 1.0
    import math
    score = min(1.0, math.log10(max_val / LARGE_TRADE_USD_THRESHOLD + 1) / 2)
    return score


def _executive_score(purchases: list) -> float:
    """
    Boost score if CEO/CFO/COO made an open-market purchase.
    These insiders have the most information — their discretionary buys are signal-rich.
    """
    if not purchases:
        return 0.0

    for tx in purchases:
        role = tx.get("role", "")
        for high_role in HIGH_SIGNAL_ROLES:
            if high_role.lower() in role.lower():
                total = tx.get("total_value", 0)
                if total and total >= 50_000:
                    log(AGENT, f"👔 Executive buy: {tx.get('filer_name')} ({role}) ${total:,.0f}", "signal")
                    return 1.0
    return 0.0


def _buy_sell_ratio(purchases: list, sales: list) -> float:
    """
    Ratio of buy volume to (buy + sell) volume.
    Returns 0.5 if equal, approaches 1.0 if all buys, 0.0 if all sells.
    """
    buy_vol  = sum(t.get("total_value", 0) or 0 for t in purchases)
    sell_vol = sum(t.get("total_value", 0) or 0 for t in sales)
    total    = buy_vol + sell_vol
    if total == 0:
        return 0.5  # no data — neutral
    return buy_vol / total


def _summarize(ticker, purchases, sales, components) -> str:
    lines = [f"Insider activity for {ticker}:"]
    if purchases:
        total_buy = sum(t.get("total_value", 0) or 0 for t in purchases)
        lines.append(f"  • {len(purchases)} open-market purchases totaling ${total_buy:,.0f}")
    if sales:
        total_sell = sum(t.get("total_value", 0) or 0 for t in sales)
        lines.append(f"  • {len(sales)} open-market sales totaling ${total_sell:,.0f}")
    if components["cluster_buy_score"] > 0.4:
        lines.append("  • ⚡ Insider CLUSTER detected — multiple insiders bought")
    if components["executive_buy_score"] > 0:
        lines.append("  • 👔 C-suite / Director made a discretionary purchase")
    return "\n".join(lines)


def _empty_score(ticker: str) -> dict:
    return {
        "ticker":     ticker,
        "score":      0.0,
        "direction":  "NEUTRAL",
        "components": {},
        "summary":    f"No recent insider transactions found for {ticker}",
        "raw_txns":   [],
    }


def run(tickers: list[str], days: int = 30) -> dict[str, dict]:
    """Entry point for orchestrator."""
    log(AGENT, f"Analyzing {len(tickers)} tickers", "agent")
    return {ticker: analyze_ticker(ticker, days) for ticker in tickers}


if __name__ == "__main__":
    from config.settings import DEFAULT_TICKERS
    from data.db import init_db
    init_db()
    results = run(["NVDA", "MSFT"])
    for ticker, r in results.items():
        print(f"\n{ticker}: {r['direction']} (score={r['score']:.2f})")
        print(r["summary"])
