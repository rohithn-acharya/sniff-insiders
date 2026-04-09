"""
agents/edgar_agent.py

EDGAR Agent — fetches SEC Form 4 (insider transactions) and key filings
(8-K, 10-Q, 10-K) for a list of tickers.

SEC EDGAR API docs: https://www.sec.gov/developer
Key endpoints used:
  - /submissions/{CIK}.json        → filing history for a company
  - /cgi-bin/browse-edgar?...      → full-text search
  - https://efts.sec.gov/LATEST/search-index?...  → EDGAR full-text search
"""

import time
import requests
import json
from datetime import datetime, timedelta
from typing import Optional

from config.settings import (
    EDGAR_BASE_URL, EDGAR_HEADERS, EDGAR_RATE_LIMIT_SECS,
    FORM4_LOOKBACK_DAYS
)
from data.db import insert_insider_transaction, get_conn
from utils.logger import log

AGENT = "EDGAR"

# ── Ticker → CIK resolution ───────────────────────────────────────────────────

_TICKER_CIK_CACHE: dict[str, str] = {}

def get_cik(ticker: str) -> Optional[str]:
    """Resolve ticker symbol to SEC CIK number."""
    if ticker in _TICKER_CIK_CACHE:
        return _TICKER_CIK_CACHE[ticker]

    url = f"{EDGAR_BASE_URL}/submissions/CIK.json"
    # EDGAR provides a ticker→CIK map
    map_url = "https://www.sec.gov/files/company_tickers.json"
    try:
        r = requests.get(map_url, headers=EDGAR_HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        for entry in data.values():
            if entry["ticker"].upper() == ticker.upper():
                cik = str(entry["cik_str"]).zfill(10)
                _TICKER_CIK_CACHE[ticker] = cik
                return cik
    except Exception as e:
        log(AGENT, f"CIK lookup failed for {ticker}: {e}", "error")
    return None


def _rate_sleep():
    time.sleep(EDGAR_RATE_LIMIT_SECS)


# ── Form 4 fetcher ────────────────────────────────────────────────────────────

def fetch_form4_filings(ticker: str) -> list[dict]:
    """
    Fetch recent Form 4 filings for a ticker.
    Returns a list of parsed transaction dicts ready for DB insertion.
    """
    cik = get_cik(ticker)
    if not cik:
        log(AGENT, f"Cannot resolve CIK for {ticker}", "warn")
        return []

    log(AGENT, f"Fetching Form 4s for {ticker} (CIK={cik})")

    submissions_url = f"{EDGAR_BASE_URL}/submissions/CIK{cik}.json"
    _rate_sleep()

    try:
        r = requests.get(submissions_url, headers=EDGAR_HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log(AGENT, f"Submissions fetch failed: {e}", "error")
        return []

    filings = data.get("filings", {}).get("recent", {})
    forms      = filings.get("form", [])
    accessions = filings.get("accessionNumber", [])
    dates      = filings.get("filingDate", [])
    primary    = filings.get("primaryDocument", [])

    cutoff = (datetime.now() - timedelta(days=FORM4_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    results = []
    for form, acc, date, doc in zip(forms, accessions, dates, primary):
        if form != "4":
            continue
        if date < cutoff:
            break  # filings are newest-first; stop when past window

        acc_clean = acc.replace("-", "")
        # primaryDocument sometimes has an XSLT prefix (e.g. xslF345X06/file.xml)
        # which returns an HTML render. Strip it to get the raw XML.
        raw_doc = doc.split("/")[-1] if "/" in doc else doc
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{acc_clean}/{raw_doc}"
        )
        parsed = _parse_form4(filing_url, ticker, cik, date)
        if parsed:
            results.extend(parsed)
        _rate_sleep()

    log(AGENT, f"Found {len(results)} Form 4 transactions for {ticker}", "success")
    return results


def _parse_form4(filing_url: str, ticker: str, cik: str, filed_date: str) -> list[dict]:
    """
    Parse a Form 4 XML document into a list of transaction records.
    SEC Form 4 is XML: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany
    """
    try:
        _rate_sleep()
        r = requests.get(filing_url, headers=EDGAR_HEADERS, timeout=15)
        r.raise_for_status()
        content = r.text
    except Exception as e:
        log(AGENT, f"Failed to fetch {filing_url}: {e}", "warn")
        return []

    # Parse XML with lxml
    try:
        from lxml import etree
        root = etree.fromstring(content.encode())
    except Exception:
        return []

    def txt(node, path):
        el = node.find(path)
        return el.text.strip() if el is not None and el.text else None

    # Reporter (the insider)
    filer_name = txt(root, ".//reportingOwner/reportingOwnerId/rptOwnerName")
    role_el    = root.find(".//reportingOwner/reportingOwnerRelationship")
    role_parts = []
    if role_el is not None:
        for tag in ["isDirector", "isOfficer", "isTenPercentOwner"]:
            el = role_el.find(tag)
            if el is not None and el.text and el.text.strip() == "1":
                role_parts.append(tag.replace("is", ""))
        title_el = role_el.find("officerTitle")
        if title_el is not None and title_el.text:
            role_parts.append(title_el.text.strip())
    role = ", ".join(role_parts) or "Unknown"

    transactions = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        try:
            tx_type = txt(txn, "transactionCoding/transactionCode")  # P/S/A etc.
            tx_date = txt(txn, "transactionDate/value")
            shares_str = txt(txn, "transactionAmounts/transactionShares/value")
            price_str  = txt(txn, "transactionAmounts/transactionPricePerShare/value")
            owned_str  = txt(txn, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")

            shares = float(shares_str) if shares_str else 0.0
            price  = float(price_str)  if price_str  else 0.0
            owned  = float(owned_str)  if owned_str  else 0.0
            total  = shares * price

            transactions.append({
                "ticker":           ticker,
                "cik":              cik,
                "filer_name":       filer_name,
                "role":             role,
                "transaction_date": tx_date,
                "filed_date":       filed_date,
                "transaction_type": tx_type,
                "shares":           shares,
                "price_per_share":  price,
                "total_value":      total,
                "shares_owned_after": owned,
                "form_url":         filing_url,
            })
        except Exception:
            continue

    return transactions


# ── 8-K fetcher (material events) ────────────────────────────────────────────

def fetch_8k_filings(ticker: str, days: int = 14) -> list[dict]:
    """Fetch recent 8-K filings (material events, earnings, M&A)."""
    cik = get_cik(ticker)
    if not cik:
        return []

    log(AGENT, f"Fetching 8-Ks for {ticker}")
    submissions_url = f"{EDGAR_BASE_URL}/submissions/CIK{cik}.json"
    _rate_sleep()

    try:
        r = requests.get(submissions_url, headers=EDGAR_HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log(AGENT, f"8-K fetch failed: {e}", "error")
        return []

    filings    = data.get("filings", {}).get("recent", {})
    forms      = filings.get("form", [])
    accessions = filings.get("accessionNumber", [])
    dates      = filings.get("filingDate", [])
    primary    = filings.get("primaryDocument", [])

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    results = []
    for form, acc, date, doc in zip(forms, accessions, dates, primary):
        if form not in ("8-K", "8-K/A"):
            continue
        if date < cutoff:
            break
        acc_clean  = acc.replace("-", "")
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{acc_clean}/{doc}"
        )
        results.append({
            "ticker":     ticker,
            "cik":        cik,
            "form_type":  form,
            "filed_date": date,
            "filing_url": filing_url,
        })
        _rate_sleep()

    log(AGENT, f"Found {len(results)} 8-K filings for {ticker}", "success")
    return results


# ── Main run function ─────────────────────────────────────────────────────────

def run(tickers: list[str]) -> dict:
    """
    Entry point called by the orchestrator.
    Returns dict of {ticker: {"transactions": [...], "8ks": [...]}}
    """
    log(AGENT, f"Starting run for {len(tickers)} tickers", "agent")
    results = {}
    for ticker in tickers:
        txns = fetch_form4_filings(ticker)
        for tx in txns:
            insert_insider_transaction(tx)

        eightks = fetch_8k_filings(ticker)

        results[ticker] = {
            "transactions": txns,
            "8ks":          eightks,
        }

    log(AGENT, "Run complete ✓", "success")
    return results


if __name__ == "__main__":
    from config.settings import DEFAULT_TICKERS
    run(DEFAULT_TICKERS[:3])  # quick test on 3 tickers
