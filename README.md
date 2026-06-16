# Heathrow Helper

An unofficial passenger assistant for **London Heathrow Airport (LHR)**. A chat web app that answers natural-language travel questions using live data from Heathrow's own public APIs.

**Live demo:** https://heathrow-helper.onrender.com

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
| Backend | Python 3.12, Flask, Gunicorn |
| NLP | `langdetect`, `deep-translator`, fuzzy matching (`difflib`), n-gram intent routing |
| Live data | Heathrow public flight + wait-time APIs, AviationStack fallback |
| Static data | 17 curated JSON datasets (airlines, lounges, cards, transport, customs, etc.) |
| Frontend | Server-rendered Jinja2, vanilla CSS (tokens / dark mode), progressive enhancement JS |
| Deploy | Render (primary), Vercel (serverless via `api/index.py`) |

## Architecture

```
┌─────────────┐    POST /chat    ┌──────────────┐
│  Browser    │ ───────────────▶ │  Flask app   │  app.py
│  (Jinja2)   │ ◀─────────────── │              │
└─────────────┘     JSON         └──────┬───────┘
                                        │
                                        ▼
                              ┌──────────────────┐
                              │   bot.respond    │  intent router
                              └─────┬────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
       Heathrow live API     17× JSON datasets      AviationStack
       (flights, waits,      (lounges, cards,       (non-LHR legs
        disruptions)          transport, customs)    for connections)
```

In-memory TTL cache (60 s) shields upstream APIs from repeat calls.

## Run locally

```bash
git clone https://github.com/rec0334/Heathrow-Helper.git
cd Heathrow-Helper
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
copy .env.example .env          # then add your AviationStack key (optional)
python app.py
```

Open http://localhost:5000

### Environment

| Variable | Required | Purpose |
|---|---|---|
| `AVIATIONSTACK_KEY` | optional | Enables non-LHR flight lookups for connection checks |

The Heathrow live-board API needs no key.

## Deploy

- **Render** — `render.yaml` is checked in; create a new Web Service from the repo, set `AVIATIONSTACK_KEY`, done.
- **Vercel** — `vercel.json` + `api/index.py` route all traffic through a serverless function.

## Project structure

```
heathrow-bot/
├── app.py              # Flask routes, security headers, SEO (sitemap/robots)
├── bot.py              # Intent routing, live-data clients, translation
├── api/index.py        # Vercel serverless entrypoint
├── data/               # 17 curated JSON datasets
├── templates/          # Jinja2 (index, about, privacy, terms, contact)
├── static/             # CSS tokens, dark theme, chat JS, favicon
├── docs/               # Tech-stack PDF
├── render.yaml         # Render deploy config
├── vercel.json         # Vercel rewrites
├── Procfile            # gunicorn app:app
└── requirements.txt
```

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
