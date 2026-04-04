"""
tests/test_agents.py
Unit tests for Sniff Insiders agents.
Run with: python -m pytest tests/ -v
"""

import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.db import init_db, insert_insider_transaction, get_recent_insider_txns
from agents.insider_agent import (
    _cluster_score, _large_trade_score, _executive_score, _buy_sell_ratio
)
from agents.news_agent import _sentiment, _is_geopolitical, _extract_tickers


# ── DB tests ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    """Point DB to a temp file for each test."""
    import config.settings as settings
    settings.DB_PATH = str(tmp_path / "test.db")
    import data.db as db
    db.DB_PATH = settings.DB_PATH
    init_db()


def test_insert_and_retrieve_txn():
    tx = {
        "ticker": "TEST", "cik": "0001234567",
        "filer_name": "John CEO", "role": "CEO",
        "transaction_date": "2025-01-15", "filed_date": "2025-01-16",
        "transaction_type": "P", "shares": 10000,
        "price_per_share": 50.0, "total_value": 500000,
        "shares_owned_after": 60000, "form_url": "https://example.com/form4",
    }
    insert_insider_transaction(tx)
    rows = get_recent_insider_txns("TEST", days=60)
    assert len(rows) == 1
    assert rows[0]["filer_name"] == "John CEO"


# ── Insider agent tests ───────────────────────────────────────────────────────

def make_txn(date, filer, value=100_000, tx_type="P"):
    return {
        "transaction_date": date,
        "filer_name": filer,
        "transaction_type": tx_type,
        "total_value": value,
        "role": "Director",
    }


def test_cluster_score_no_cluster():
    """Single insider buying — should not trigger cluster."""
    txns = [make_txn("2025-01-10", "Alice")]
    score = _cluster_score(txns, "TEST")
    assert score < 0.4


def test_cluster_score_with_cluster():
    """Three distinct insiders buying in 2 weeks — should score high."""
    txns = [
        make_txn("2025-01-10", "Alice"),
        make_txn("2025-01-12", "Bob"),
        make_txn("2025-01-14", "Charlie"),
    ]
    score = _cluster_score(txns, "TEST")
    assert score >= 0.5


def test_large_trade_score_below_threshold():
    txns = [make_txn("2025-01-10", "Alice", value=100_000)]
    score = _large_trade_score(txns)
    assert score == 0.0  # below $500K threshold


def test_large_trade_score_above_threshold():
    txns = [make_txn("2025-01-10", "Alice", value=2_000_000)]
    score = _large_trade_score(txns)
    assert score > 0.0


def test_executive_score_ceo_buy():
    txns = [{"role": "CEO", "filer_name": "Tim CEO", "total_value": 1_000_000}]
    score = _executive_score(txns)
    assert score == 1.0


def test_executive_score_small_buy():
    """CEO buying < $50K should not trigger executive score."""
    txns = [{"role": "CEO", "filer_name": "Tim CEO", "total_value": 10_000}]
    score = _executive_score(txns)
    assert score == 0.0


def test_buy_sell_ratio_all_buys():
    buys  = [make_txn("2025-01-10", "Alice", value=1_000_000)]
    sells = []
    ratio = _buy_sell_ratio(buys, sells)
    assert ratio == 1.0


def test_buy_sell_ratio_all_sells():
    buys  = []
    sells = [make_txn("2025-01-10", "Alice", value=1_000_000)]
    ratio = _buy_sell_ratio(buys, sells)
    assert ratio == 0.0


# ── News agent tests ──────────────────────────────────────────────────────────

def test_sentiment_positive():
    score = _sentiment("Stock surged to record gains on strong profit growth")
    assert score > 0.0


def test_sentiment_negative():
    score = _sentiment("Company crashes, massive losses, SEC investigation, bankruptcy")
    assert score < 0.0


def test_sentiment_neutral():
    score = _sentiment("The company released its quarterly report today")
    assert -0.2 < score < 0.2


def test_geopolitical_flag():
    assert _is_geopolitical("NATO sanctions Russia over Ukraine invasion") is True
    assert _is_geopolitical("Apple announces new iPhone model") is False


def test_extract_tickers():
    text    = "NVDA and AMD are both up today, while AAPL struggled"
    tickers = ["NVDA", "AMD", "AAPL", "MSFT"]
    found   = _extract_tickers(text, tickers)
    assert set(found) == {"NVDA", "AMD", "AAPL"}
    assert "MSFT" not in found


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
