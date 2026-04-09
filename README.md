# Sniff Insiders

An AI-powered multi-agent system for detecting early stock trends using:
- SEC insider transaction filings (Form 4)
- SEC fundamental filings (8-K, 10-Q, 10-K)
- Real-time market news correlation
- Geopolitical event analysis

## Architecture

```
sniff-insiders/
├── agents/
│   ├── edgar_agent.py        # SEC EDGAR filing scraper
│   ├── insider_agent.py      # Insider transaction analyzer
│   ├── news_agent.py         # Market & geopolitical news fetcher
│   ├── correlation_agent.py  # Cross-signal correlation engine
│   └── orchestrator.py       # Master agent coordinating all agents
├── config/
│   └── settings.py           # API keys, thresholds, tickers watchlist
├── data/
│   ├── cache/                # Local cache for API responses
│   ├── reports/              # Generated signal reports (JSON + txt)
│   └── db.py                 # SQLite persistence layer
├── reports/
│   └── report_generator.py   # Signal reports & alerts
├── utils/
│   ├── logger.py             # Rich structured logging
│   └── helpers.py            # Shared utilities
└── tests/
    └── test_agents.py
```

## Agents

| Agent | Role |
|-------|------|
| **EDGAR Agent** | Polls SEC EDGAR for Form 4, 8-K, 10-K, 10-Q filings |
| **Insider Agent** | Detects unusual insider buy/sell clusters |
| **News Agent** | Fetches market news + geopolitical events via RSS |
| **Correlation Agent** | Synthesizes all signals via Claude AI |
| **Orchestrator** | Schedules, coordinates, and surfaces alerts |
| **Report Generator** | Saves JSON + plaintext reports to `data/reports/` |

## Quickstart

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure secrets
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY and SEC_USER_AGENT

# 3. Run once
python -m agents.orchestrator --tickers AAPL NVDA MSFT --days 30

# 4. Run as daemon (polls every 60 min)
python -m agents.orchestrator --daemon --interval 60

# 5. Run tests
python -m pytest tests/ -v
```

## Configuration

| Variable | Description | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API key for AI synthesis | — |
| `SEC_USER_AGENT` | Required by SEC EDGAR (name + email) | `SniffInsiders dev@example.com` |
| `DEFAULT_TICKERS` | Watchlist (edit `config/settings.py`) | 18 large-caps |
| `ALERT_SCORE_THRESHOLD` | Score >= this triggers an alert | `0.60` |
| `POLL_INTERVAL_MINUTES` | Daemon re-run cadence | `60` |

## Signal Scoring

The correlation engine combines:

| Signal | Weight |
|---|---|
| Insider cluster buy | 40% |
| Insider large buy | 20% |
| Earnings surprise (8-K) | 15% |
| News sentiment | 15% |
| Geopolitical impact | 10% |

Scores range from 0.0 (no signal) to 1.0 (very strong). Direction is BULLISH / BEARISH / NEUTRAL.
