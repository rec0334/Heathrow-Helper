# Heathrow Helper

An unofficial passenger assistant for **London Heathrow Airport (LHR)**. A chat web app that answers natural-language travel questions using live data from Heathrow's own public APIs.

**Live demo:** https://heathrow-helper.vercel.app

> Built to help first-time fliers and older travellers find flight, terminal, lounge and transport info without needing flight numbers or juggling multiple apps.

---

## Features

- **Live flight status** — departures and arrivals from Heathrow's live board, including delays, gate states (Gate Open / Boarding / Closing / Closed), cancellations and baggage belts.
- **Search by destination** — "flights to Dubai", "flights from T3 to New York"; no flight number required.
- **Smart connection check** — paste two flight numbers, get a realistic-layover verdict with alliance-specific minimum connection times.
- **Lounges + credit-card access** — accurate per-terminal lounge listings plus card-specific access (Amex, HSBC, Barclays, Chase, Capital One, Revolut, Priority Pass, LoungeKey, DragonPass).
- **Live security & immigration waits** — from Heathrow's official feed.
- **Disruption alerts** — scraped from Heathrow's homepage banner.
- **Transport, customs, VAT, parking, baggage, special assistance** and more.
- **Multi-language** — language auto-detected, replies translated on the fly (15+ languages).
- **No accounts, no tracking** — chat processed in-memory only.

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, Flask (app-factory pattern) |
| NLP | `langdetect`, `deep-translator`, fuzzy matching (`difflib`), n-gram intent routing |
| Live data | Heathrow public flight + wait-time APIs, AviationStack fallback |
| Static data | 17 curated JSON datasets (airlines, lounges, cards, transport, customs, etc.) |
| Frontend | Server-rendered Jinja2, vanilla CSS (tokens / dark mode), progressive enhancement JS |
| Deploy | Vercel (serverless via `api/index.py`) |

## Architecture

The Flask app is built with the **application-factory pattern**. The `app/` package exposes `create_app()`, which assembles a Flask instance and registers all routes from `app/routes.py`. Both the local runner (`app.py`) and the Vercel serverless entrypoint (`api/index.py`) construct their instance via this factory — no global app at import time.

```text
┌─────────────┐    POST /chat   ┌──────────────────────┐
│  Browser    │ ──────────────▶ │  app/ package        │
│  (Jinja2)   │ ◀────────────── │  create_app()        │
└─────────────┘     JSON        │   └─ routes.py       │
                                └──────────┬───────────┘
                                           │
                                           ▼
                                  ┌──────────────────┐
                                  │  app/bot.py      │  intent router
                                  └─────┬────────────┘
                                        │
                ┌───────────────────────┼───────────────────────┐
                ▼                       ▼                       ▼
         Heathrow live API       17× JSON datasets        AviationStack
         (flights, waits,        (lounges, cards,         (non-LHR legs
          disruptions)            transport, customs)      for connections)
```

Entry points:

| Context | File | What it does |
|---|---|---|
| Local dev | `app.py` | Thin runner — calls `create_app()`, then `app.run()` |
| Vercel prod | `api/index.py` | Imports `create_app()` and exposes the WSGI `app` |
| Tests | `tests/test_live.py` | Smoke-tests intent routing via `app.bot.respond` |

In-memory TTL cache (60 s) shields upstream APIs from repeat calls.

## Run locally

Clone and create a virtual environment:

```bash
git clone https://github.com/rec0334/Heathrow-Helper.git
cd Heathrow-Helper
python -m venv .venv
```

Activate the venv. **Windows (PowerShell):**

```powershell
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

Install deps, copy the env template, and run:

```bash
pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
python app.py
```

Then open <http://localhost:5000>.

### Environment

| Variable | Required | Purpose |
|---|---|---|
| `AVIATIONSTACK_KEY` | optional | Enables non-LHR flight lookups for connection checks |

The Heathrow live-board API needs no key.

## Deploy

Deployed on **Vercel** — `vercel.json` rewrites all traffic to `api/index.py`, which wraps the Flask app as a serverless function. Push to `main` triggers an auto-deploy.

```bash
vercel link        # one-time
vercel --prod      # deploy
vercel env add AVIATIONSTACK_KEY production
```

## Project structure

```text
Heathrow-Helper/
├── app.py                  # Thin local runner — instantiates create_app()
├── app/                    # Application package
│   ├── __init__.py         #   create_app() factory
│   ├── routes.py           #   HTTP routes (registered on the Flask instance)
│   ├── bot.py              #   Intent routing, live-data clients, translation
│   ├── templates/          #   Jinja2 (index, about, privacy, terms, contact)
│   └── static/             #   CSS tokens, dark theme, chat JS, favicon
├── api/
│   └── index.py            # Vercel serverless entrypoint (imports create_app)
├── data/                   # 17 curated JSON datasets
├── tests/
│   └── test_live.py        # Smoke test for bot intent routing
├── docs/                   # Tech-stack PDF
├── vercel.json             # Vercel rewrites
├── requirements.txt
├── .env.example            # AVIATIONSTACK_KEY placeholder
├── LICENSE                 # All Rights Reserved
└── README.md
```

> **Why both `app.py` and `app/`?** `app.py` is intentionally kept as a thin runner so `python app.py` still works for local development. Python's import system prefers the package over the module of the same name, so inside the runner `from app import create_app` resolves to `app/__init__.py`. No collision.

## Endpoints

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Chat UI |
| `/chat` | POST | `{ "message": "..." }` → bot reply JSON |
| `/health` | GET | Liveness probe |
| `/sitemap.xml`, `/robots.txt` | GET | SEO |
| `/about`, `/privacy`, `/terms`, `/contact` | GET | Static pages |

## Roadmap

- Arrivals coverage on par with departures
- Per-lounge live capacity hints
- PWA install / offline shell

## Disclaimer

Independent project. Not affiliated with, endorsed by, or operated by Heathrow Airport Limited or LHR Airports Limited. Always confirm critical travel info with your airline and the official Heathrow channels.

## License

**All Rights Reserved** © 2026 Revanth Reddy Chitti.

This repository is published for portfolio and review only. The source code, curated data, and "Heathrow Helper" branding are not licensed for reuse, redistribution, hosting, or model training. See [LICENSE](LICENSE) for the full notice. For licensing inquiries, contact chittirev559451@gmail.com.
