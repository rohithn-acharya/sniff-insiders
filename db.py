"""
data/db.py
SQLite persistence layer for Sniff Insiders.
Stores raw filings, parsed insider transactions, news items, and signals.
"""

import sqlite3
import json
import os
from datetime import datetime
from config.settings import DB_PATH


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # concurrent reads
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_conn()
    c = conn.cursor()

    # ── Raw Form 4 filings ───────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS insider_transactions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker          TEXT NOT NULL,
        cik             TEXT,
        filer_name      TEXT,
        role            TEXT,        -- e.g. 'CEO', 'Director', '10% Owner'
        transaction_date TEXT,
        filed_date      TEXT,
        transaction_type TEXT,       -- 'P' = Purchase, 'S' = Sale, 'A' = Award
        shares          REAL,
        price_per_share REAL,
        total_value     REAL,
        shares_owned_after REAL,
        form_url        TEXT,
        created_at      TEXT DEFAULT (datetime('now')),
        UNIQUE(ticker, filer_name, transaction_date, transaction_type, shares)
    )
    """)

    # ── SEC filings index (10-K, 10-Q, 8-K) ─────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS sec_filings (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker      TEXT,
        cik         TEXT,
        form_type   TEXT,
        filed_date  TEXT,
        period      TEXT,
        filing_url  TEXT UNIQUE,
        summary     TEXT,           -- AI-generated summary
        created_at  TEXT DEFAULT (datetime('now'))
    )
    """)

    # ── News items ───────────────────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS news_items (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        source      TEXT,
        title       TEXT,
        url         TEXT UNIQUE,
        published   TEXT,
        tickers_mentioned TEXT,     -- JSON array
        sentiment   REAL,           -- -1.0 to 1.0
        geopolitical INTEGER DEFAULT 0,  -- 1 if flagged as geo event
        summary     TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    )
    """)

    # ── Composite signals / alerts ────────────────────────────────────────────
    c.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker      TEXT NOT NULL,
        score       REAL,
        direction   TEXT,           -- 'BULLISH' | 'BEARISH' | 'NEUTRAL'
        components  TEXT,           -- JSON of sub-scores
        reasoning   TEXT,           -- AI explanation
        alert_sent  INTEGER DEFAULT 0,
        created_at  TEXT DEFAULT (datetime('now'))
    )
    """)

    conn.commit()
    conn.close()
    print("[DB] Tables initialized ✓")


# ── Helper writers ────────────────────────────────────────────────────────────

def insert_insider_transaction(tx: dict):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO insider_transactions
            (ticker, cik, filer_name, role, transaction_date, filed_date,
             transaction_type, shares, price_per_share, total_value,
             shares_owned_after, form_url)
            VALUES (:ticker, :cik, :filer_name, :role, :transaction_date,
                    :filed_date, :transaction_type, :shares, :price_per_share,
                    :total_value, :shares_owned_after, :form_url)
        """, tx)
        conn.commit()
    finally:
        conn.close()


def insert_signal(ticker: str, score: float, direction: str,
                  components: dict, reasoning: str):
    conn = get_conn()
    conn.execute("""
        INSERT INTO signals (ticker, score, direction, components, reasoning)
        VALUES (?, ?, ?, ?, ?)
    """, (ticker, score, direction, json.dumps(components), reasoning))
    conn.commit()
    conn.close()


def get_recent_insider_txns(ticker: str, days: int = 30) -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM insider_transactions
        WHERE ticker = ?
          AND transaction_date >= date('now', ? || ' days')
        ORDER BY transaction_date DESC
    """, (ticker, f"-{days}")).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_signals(limit: int = 20) -> list:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM signals
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
