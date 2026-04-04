"""
agents/correlation_agent.py

Correlation Agent — the brain of Sniff Insiders.
Takes signals from all other agents and uses Claude AI to synthesize:
  1. Insider transaction patterns
  2. SEC filing signals (8-K, earnings surprises)
  3. News sentiment (market + geopolitical)

Produces a composite score per ticker and a plain-English rationale.
"""

import json
import requests
from typing import Optional

from config.settings import (
    ANTHROPIC_API_KEY, AI_MODEL,
    WEIGHTS, ALERT_SCORE_THRESHOLD
)
from data.db import insert_signal, get_latest_signals
from utils.logger import log, log_signal

AGENT = "CORRELATOR"

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


# ── AI reasoning call ─────────────────────────────────────────────────────────

def ai_synthesize(ticker: str, insider_data: dict, news_items: list, geo_impact: float) -> dict:
    """
    Call Claude to synthesize all signals into a human-readable analysis.
    Returns {"score": float, "direction": str, "reasoning": str}
    """
    if not ANTHROPIC_API_KEY:
        log(AGENT, "No ANTHROPIC_API_KEY — skipping AI synthesis", "warn")
        return _rule_based_fallback(ticker, insider_data, geo_impact)

    # Build the prompt
    insider_summary = insider_data.get("summary", "No insider data")
    insider_score   = insider_data.get("score", 0.0)
    insider_txns    = insider_data.get("raw_txns", [])[:5]  # last 5

    news_summary = "\n".join([
        f"  [{n['sentiment']:+.2f}] {n['title'][:100]}"
        for n in (news_items or [])[:5]
    ]) or "No recent news found."

    prompt = f"""You are a financial analyst specializing in insider trading signals and early trend detection.

Analyze the following data for ticker: {ticker}

## INSIDER TRANSACTIONS (Score: {insider_score:.2f})
{insider_summary}

Recent transactions:
{json.dumps(insider_txns, indent=2, default=str)}

## RECENT NEWS
{news_summary}

## GEOPOLITICAL SENTIMENT IMPACT
Estimated geopolitical delta for this ticker: {geo_impact:+.2f}

## YOUR TASK
1. Synthesize these signals into a BULLISH / BEARISH / NEUTRAL verdict
2. Provide a confidence score from 0.0 to 1.0 (0=no signal, 1=very strong)
3. Write 2-3 sentences of plain-English reasoning for why

Respond ONLY with valid JSON (no markdown, no preamble):
{{
  "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
  "score": <float 0.0-1.0>,
  "reasoning": "<2-3 sentence explanation>"
}}"""

    headers = {
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }
    payload = {
        "model":      AI_MODEL,
        "max_tokens": 300,
        "messages":   [{"role": "user", "content": prompt}],
    }

    try:
        r = requests.post(ANTHROPIC_URL, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        content = r.json()["content"][0]["text"].strip()
        # Strip any accidental markdown fences
        content = content.replace("```json", "").replace("```", "").strip()
        result  = json.loads(content)
        log(AGENT, f"AI synthesis for {ticker}: {result['direction']} ({result['score']:.2f})")
        return result
    except Exception as e:
        log(AGENT, f"AI synthesis failed for {ticker}: {e}", "error")
        return _rule_based_fallback(ticker, insider_data, geo_impact)


def _rule_based_fallback(ticker: str, insider_data: dict, geo_impact: float) -> dict:
    """Simple rule-based scoring when AI is unavailable."""
    insider_score = insider_data.get("score", 0.0)
    composite = insider_score * 0.7 + geo_impact * 0.3

    direction = (
        "BULLISH" if composite > 0.3 else
        "BEARISH" if composite < -0.2 else
        "NEUTRAL"
    )
    return {
        "direction": direction,
        "score":     abs(composite),
        "reasoning": (
            f"Rule-based: insider score={insider_score:.2f}, "
            f"geo_impact={geo_impact:+.2f}. "
            f"No AI key configured — using weighted formula."
        ),
    }


# ── Composite scorer ──────────────────────────────────────────────────────────

def score_ticker(
    ticker:       str,
    insider_data: dict,
    news_items:   list,
    geo_impact:   float = 0.0,
) -> dict:
    """
    Produce a final composite signal for one ticker.
    """
    ai_result = ai_synthesize(ticker, insider_data, news_items, geo_impact)

    direction = ai_result.get("direction", "NEUTRAL")
    score     = ai_result.get("score", 0.0)
    reasoning = ai_result.get("reasoning", "")

    # Build component breakdown for audit trail
    components = {
        "insider_score":  insider_data.get("score", 0.0),
        "insider_dir":    insider_data.get("direction", "NEUTRAL"),
        "geo_impact":     geo_impact,
        "ai_score":       score,
        "ai_direction":   direction,
        **insider_data.get("components", {}),
    }

    # Persist to DB
    insert_signal(ticker, score, direction, components, reasoning)

    # Surface alert if above threshold
    if score >= ALERT_SCORE_THRESHOLD:
        log_signal(ticker, direction, score, reasoning)

    return {
        "ticker":     ticker,
        "score":      score,
        "direction":  direction,
        "reasoning":  reasoning,
        "components": components,
    }


def run(
    tickers:       list[str],
    insider_results: dict,
    news_result:   dict,
) -> dict[str, dict]:
    """
    Entry point called by orchestrator.
    
    Args:
        tickers:         list of tickers to score
        insider_results: output from insider_agent.run()
        news_result:     output from news_agent.run()
    """
    log(AGENT, f"Correlating signals for {len(tickers)} tickers", "agent")

    geo_impacts = news_result.get("geo_impacts", {})
    all_news    = news_result.get("all_items", [])

    final_signals = {}
    for ticker in tickers:
        insider_data = insider_results.get(ticker, {})
        ticker_news  = [
            n for n in all_news
            if ticker in (n.get("tickers_mentioned") or [])
        ]
        geo_impact = geo_impacts.get(ticker, 0.0)

        signal = score_ticker(ticker, insider_data, ticker_news, geo_impact)
        final_signals[ticker] = signal

    # Print leaderboard
    _print_leaderboard(final_signals)
    return final_signals


def _print_leaderboard(signals: dict):
    """Print ranked signal table."""
    from rich.table import Table
    from rich.console import Console

    c = Console()
    table = Table(title="📊 Sniff Insiders — Signal Leaderboard", show_lines=True)
    table.add_column("Ticker", style="bold cyan")
    table.add_column("Direction", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Reasoning")

    ranked = sorted(signals.values(), key=lambda x: x["score"], reverse=True)
    for s in ranked:
        color = "green" if s["direction"] == "BULLISH" else "red" if s["direction"] == "BEARISH" else "yellow"
        table.add_row(
            s["ticker"],
            f"[{color}]{s['direction']}[/{color}]",
            f"{s['score']:.2f}",
            (s["reasoning"] or "")[:80] + "…",
        )
    c.print(table)


if __name__ == "__main__":
    # Standalone test with mock data
    mock_insider = {
        "NVDA": {
            "score": 0.75, "direction": "BULLISH",
            "summary": "3 insiders bought NVDA last week. CEO purchased $2M.",
            "components": {"cluster_buy_score": 0.8, "executive_buy_score": 1.0},
            "raw_txns": [],
        }
    }
    mock_news = {
        "all_items": [],
        "geo_items": [],
        "geo_impacts": {"NVDA": 0.1},
    }
    results = run(["NVDA"], mock_insider, mock_news)
