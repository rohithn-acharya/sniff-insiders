"""
agents/news_agent.py

News Agent — aggregates market news and geopolitical events,
tags tickers mentioned, and scores sentiment.

Data sources (all free, no API key):
  - Yahoo Finance RSS
  - Reuters World RSS
  - NYT World RSS
  - SEC EDGAR full-text search (for filing news)

Geopolitical keywords trigger a flag used by the correlation engine
to boost/dampen sector signals (e.g., defense stocks on conflict news).
"""

import feedparser
import time
import re
from datetime import datetime, timezone
from typing import Optional

from config.settings import NEWS_FEEDS, DEFAULT_TICKERS
from data.db import get_conn
from utils.logger import log

AGENT = "NEWS"

# ── Geopolitical signal keywords ──────────────────────────────────────────────
GEO_KEYWORDS = [
    "war", "conflict", "sanction", "tariff", "embargo", "invasion",
    "military", "nato", "treaty", "nuclear", "missile", "coup",
    "trade war", "export ban", "chip ban", "supply chain",
    "inflation", "fed rate", "interest rate", "recession",
    "opec", "oil price", "energy crisis", "pipeline",
    "taiwan", "ukraine", "russia", "china", "iran", "north korea",
    "middle east", "israel", "gaza", "red sea",
]

# ── Sector sensitivity map ────────────────────────────────────────────────────
# Which sectors benefit/hurt from geopolitical events
GEO_SECTOR_IMPACT = {
    "defense":  ["LMT", "RTX", "NOC", "GD", "BA"],
    "energy":   ["XOM", "CVX", "COP", "OXY"],
    "semis":    ["NVDA", "AMD", "INTC", "TSM", "AMAT", "ASML"],
    "financials":["JPM", "GS", "BAC", "C", "MS"],
}


# ── Simple sentiment scorer ───────────────────────────────────────────────────

POSITIVE_WORDS = {
    "surge", "rally", "beat", "record", "growth", "profit", "gain",
    "upgrade", "strong", "bullish", "outperform", "buy", "breakout",
    "expand", "innovate", "partnership", "deal", "breakthrough",
}
NEGATIVE_WORDS = {
    "crash", "plunge", "miss", "loss", "decline", "warn", "downgrade",
    "bearish", "sell", "layoff", "recall", "fine", "lawsuit", "probe",
    "investigation", "fraud", "default", "bankruptcy", "tariff", "ban",
}

def _sentiment(text: str) -> float:
    """
    Very lightweight lexicon-based sentiment.
    Returns -1.0 (very negative) to 1.0 (very positive).
    In production you'd swap this for a fine-tuned FinBERT model.
    """
    words = re.findall(r'\b\w+\b', text.lower())
    pos = sum(1 for w in words if w in POSITIVE_WORDS)
    neg = sum(1 for w in words if w in NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def _is_geopolitical(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in GEO_KEYWORDS)


def _extract_tickers(text: str, watchlist: list[str]) -> list[str]:
    """Find which watchlist tickers are mentioned in the text."""
    found = []
    for ticker in watchlist:
        # Match whole-word ticker (avoid false positives like 'AMD' in 'amidst')
        pattern = rf'\b{re.escape(ticker)}\b'
        if re.search(pattern, text, re.IGNORECASE):
            found.append(ticker)
    return found


# ── Feed fetcher ──────────────────────────────────────────────────────────────

def fetch_all_feeds(watchlist: Optional[list[str]] = None) -> list[dict]:
    """
    Poll all configured RSS feeds and return parsed news items.
    """
    watchlist = watchlist or DEFAULT_TICKERS
    all_items = []

    for feed_url in NEWS_FEEDS:
        log(AGENT, f"Fetching {feed_url}")
        try:
            parsed = feedparser.parse(feed_url)
            entries = parsed.get("entries", [])
            log(AGENT, f"  Got {len(entries)} items")

            for entry in entries:
                title   = entry.get("title", "")
                summary = entry.get("summary", "")
                url     = entry.get("link", "")
                pub     = entry.get("published", "")

                combined = f"{title} {summary}"

                item = {
                    "source":            feed_url,
                    "title":             title,
                    "url":               url,
                    "published":         pub,
                    "tickers_mentioned": _extract_tickers(combined, watchlist),
                    "sentiment":         _sentiment(combined),
                    "geopolitical":      int(_is_geopolitical(combined)),
                    "summary":           summary[:500],
                }
                all_items.append(item)

        except Exception as e:
            log(AGENT, f"Feed error {feed_url}: {e}", "error")

        time.sleep(0.5)  # polite delay between feeds

    log(AGENT, f"Total news items fetched: {len(all_items)}", "success")
    return all_items


def save_news_items(items: list[dict]):
    """Persist news items to DB, skipping duplicates."""
    import json
    conn = get_conn()
    saved = 0
    for item in items:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO news_items
                (source, title, url, published, tickers_mentioned, sentiment, geopolitical, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                item["source"], item["title"], item["url"], item["published"],
                json.dumps(item["tickers_mentioned"]),
                item["sentiment"], item["geopolitical"], item["summary"],
            ))
            saved += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    log(AGENT, f"Saved {saved} new news items to DB", "success")


def get_ticker_news(ticker: str, limit: int = 10) -> list[dict]:
    """Retrieve recent news mentioning a specific ticker."""
    import json
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM news_items
        WHERE tickers_mentioned LIKE ?
        ORDER BY published DESC
        LIMIT ?
    """, (f'%"{ticker}"%', limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_geo_signals() -> list[dict]:
    """Get recent geopolitical news items."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM news_items
        WHERE geopolitical = 1
        ORDER BY published DESC
        LIMIT 20
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def sector_geo_impact(geo_items: list[dict]) -> dict[str, float]:
    """
    Given geopolitical news items, estimate sentiment impact per sector.
    Returns {ticker: sentiment_delta} for relevant tickers.
    """
    if not geo_items:
        return {}

    avg_sentiment = sum(i["sentiment"] for i in geo_items) / len(geo_items)

    impacts = {}
    for sector, tickers in GEO_SECTOR_IMPACT.items():
        for ticker in tickers:
            # Defense benefits from conflict (inverse of general sentiment)
            if sector == "defense":
                impacts[ticker] = -avg_sentiment * 0.3  # conflict → defense up
            elif sector == "energy":
                impacts[ticker] = -avg_sentiment * 0.2
            else:
                impacts[ticker] = avg_sentiment * 0.1

    return impacts


def run(watchlist: Optional[list[str]] = None) -> dict:
    """Entry point for orchestrator."""
    log(AGENT, "Starting news fetch run", "agent")
    items    = fetch_all_feeds(watchlist)
    save_news_items(items)
    geo      = [i for i in items if i["geopolitical"]]
    impacts  = sector_geo_impact(geo)

    log(AGENT,
        f"Geopolitical items: {len(geo)} | Sector impacts mapped: {len(impacts)}",
        "success")
    return {
        "all_items":    items,
        "geo_items":    geo,
        "geo_impacts":  impacts,
    }


if __name__ == "__main__":
    from data.db import init_db
    init_db()
    result = run()
    print(f"\nGeo items: {len(result['geo_items'])}")
    for item in result["geo_items"][:3]:
        print(f"  [{item['sentiment']:+.2f}] {item['title'][:80]}")
