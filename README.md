# Sniff Insiders 🕵️

An AI-powered multi-agent system for detecting early stock trends using:
- SEC insider transaction filings (Form 4)
- SEC fundamental filings (10-K, 10-Q, 8-K)
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
├── data/
│   ├── cache/                # Local cache for API responses
│   └── db.py                 # SQLite DB layer
├── config/
│   └── settings.py           # API keys, thresholds, tickers watchlist
├── utils/
│   ├── logger.py             # Structured logging
│   └── helpers.py            # Shared utilities
├── reports/
│   └── report_generator.py   # Signal reports & alerts
└── tests/
    └── test_agents.py
```

## Agents

| Agent | Role |
|-------|------|
| **EDGAR Agent** | Polls SEC EDGAR for Form 4, 10-K, 10-Q, 8-K filings |
| **Insider Agent** | Detects unusual insider buy/sell clusters |
| **News Agent** | Fetches market news + geopolitical events |
| **Correlation Agent** | Finds signal convergence across data sources |
| **Orchestrator** | Schedules, coordinates, and surfaces alerts |

## Quickstart

```bash
pip install -r requirements.txt
python -m agents.orchestrator --tickers AAPL NVDA MSFT --days 30
```

