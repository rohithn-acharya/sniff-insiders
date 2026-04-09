"""
config/settings.py
Central configuration for Sniff Insiders.
Load secrets from .env — never hardcode API keys.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── SEC EDGAR ────────────────────────────────────────────────────────────────
EDGAR_BASE_URL = "https://data.sec.gov"
EDGAR_HEADERS = {
    # SEC requires a real User-Agent with contact info
    "User-Agent": os.getenv("SEC_USER_AGENT", "SniffInsiders dev@example.com"),
    "Accept-Encoding": "gzip, deflate",
}
EDGAR_RATE_LIMIT_SECS = 0.12  # SEC allows ~10 req/sec; stay safe at ~8

# ─── Anthropic (AI correlation layer) ────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = "claude-sonnet-4-6"

# ─── News feeds (free, no key needed) ────────────────────────────────────────
NEWS_FEEDS = [
    # Market news
    "https://feeds.finance.yahoo.com/rss/2.0/headline",
    "https://www.investing.com/rss/news.rss",
    # Geopolitical
    "https://feeds.reuters.com/Reuters/worldNews",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
]

# ─── Watchlist ────────────────────────────────────────────────────────────────
# Default tickers to monitor — override via CLI or env
DEFAULT_TICKERS = [
    "NVDA", "MSFT", "AAPL", "GOOGL", "AMZN",
    "META", "TSLA", "AMD", "INTC", "TSM",
    "JPM", "GS", "BAC",        # Financials
    "XOM", "CVX",              # Energy / geopolitical sensitivity
    "LMT", "RTX", "NOC",       # Defense (geopolitical plays)
]

# ─── Signal thresholds ───────────────────────────────────────────────────────
INSIDER_CLUSTER_MIN_TRADES = 3     # Min # of insiders buying/selling in window
INSIDER_CLUSTER_WINDOW_DAYS = 14   # Rolling window (days) for cluster detection
LARGE_TRADE_USD_THRESHOLD = 500_000  # Flag trades > $500K
FORM4_LOOKBACK_DAYS = 30           # How many days back to fetch Form 4 filings

# ─── Scoring weights (correlation engine) ────────────────────────────────────
WEIGHTS = {
    "insider_cluster_buy":   0.40,
    "insider_large_buy":     0.20,
    "earnings_surprise":     0.15,
    "news_sentiment":        0.15,
    "geopolitical_signal":   0.10,
}
ALERT_SCORE_THRESHOLD = 0.60  # Score >= this triggers an alert

# ─── Database ────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sniff.db")

# ─── Scheduler ───────────────────────────────────────────────────────────────
POLL_INTERVAL_MINUTES = 60  # How often the orchestrator re-runs
