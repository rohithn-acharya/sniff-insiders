"""
utils/helpers.py
Shared utility functions used across agents.
"""

import re
from datetime import datetime, date
from typing import Optional


def safe_float(value, default: float = 0.0) -> float:
    """Convert a value to float, returning default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default: int = 0) -> int:
    """Convert a value to int, returning default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parse a YYYY-MM-DD string into a date object."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def truncate(text: str, max_len: int = 200) -> str:
    """Truncate a string to max_len characters, appending '…' if cut."""
    if not text or len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def normalize_ticker(ticker: str) -> str:
    """Uppercase and strip whitespace from a ticker symbol."""
    return ticker.strip().upper()


def format_usd(amount: float) -> str:
    """Format a dollar amount as a human-readable string (e.g. $1.2M)."""
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}K"
    return f"${amount:.0f}"


def chunk_list(lst: list, size: int) -> list[list]:
    """Split a list into chunks of at most `size` items."""
    return [lst[i:i + size] for i in range(0, len(lst), size)]
