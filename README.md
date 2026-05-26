# Mike AI System

Automated Finance Controller + AI Agent pipelines for Mike's e-commerce / dropshipping business.

**Stack:** Python · PostgreSQL · APScheduler · Google Sheets API · Slack · WhatsApp Business API · Claude Sonnet · GPT-4o · Docker

---

## Repository Structure

```
mike-ai-system/
├── database/
│   └── schema.sql              ← PostgreSQL schema (tables, views, triggers)
├── dashboard/
│   ├── backend/                ← FastAPI + JWT auth + NOVA AI chat
│   └── frontend/               ← React + Vite + Tailwind Mission Control UI
├── docs/
│   ├── architecture.md         ← System design & data flow
│   └── disaster-recovery.md    ← Full restore runbook
├── scripts/
│   └── python/                 ← Finance pipeline + APScheduler
│       ├── scheduler.py        ← Cron job runner (replaces n8n)
│       ├── main.py             ← Pipeline orchestrator (all modes)
│       ├── config.py           ← Env var loader
│       ├── sheets_parser.py    ← Google Sheets ingestion
│       ├── pl_processor.py     ← P&L processing + anomaly detection
│       ├── slack_reporter.py   ← Slack reports + alerts
│       ├── whatsapp_alerts.py  ← WhatsApp EOD messages
│       ├── Dockerfile          ← Scheduler container image
│       └── requirements.txt    ← Python dependencies
├── HOW_TO_DEPLOY.md            ← Complete deployment guide
├── docker-compose.yml          ← All 4 services
└── .env.example                ← Environment variable template
```

---

## Services

| Service | Port | Description |
|---|---|---|
| `postgres` | 5432 | PostgreSQL 15 — persistent finance data |
| `scheduler` | — | APScheduler — runs all cron jobs automatically |
| `dashboard-backend` | 8000 | FastAPI — REST API + NOVA AI chat |
| `dashboard-frontend` | 3000 | React Mission Control dashboard |

---

## Automated Schedule (Europe/Amsterdam)

| Time | Mode | What it does |
|---|---|---|
| 06:50 daily | `sync_only` | Pre-fetch Google Sheet data |
| 07:00 daily | `morning_report` | Slack P&L daily report |
| Every 30 min | `read_invoices` | Scan + log supplier invoices |
| 21:00 daily | `eod_report` | WhatsApp EOD summary to Mike |
| 00:00 daily | `reconcile` | Sheet vs DB row-count audit |

Every job logs start/end/duration to the `agent_runs` table and sends a Slack alert to `#alerts` on failure.

---

## Quick Start

See **[HOW_TO_DEPLOY.md](HOW_TO_DEPLOY.md)** for the complete step-by-step guide.

### TL;DR

```bash
git clone https://github.com/mikeaifreak/mike-ai-system.git
cd mike-ai-system
cp .env.example .env
# Fill in all values in .env
docker-compose up --build -d
```

---

## Running Pipeline Modes Manually

```bash
# Sync Google Sheet → DB (no notifications)
docker exec mike-ai-system-scheduler-1 python main.py --mode sync_only

# Full morning report → Slack
docker exec mike-ai-system-scheduler-1 python main.py --mode morning_report

# EOD WhatsApp summary
docker exec mike-ai-system-scheduler-1 python main.py --mode eod_report

# Nightly reconciliation
docker exec mike-ai-system-scheduler-1 python main.py --mode reconcile

# Invoice scan
docker exec mike-ai-system-scheduler-1 python main.py --mode read_invoices
```

---

## Useful Maintenance Commands

```bash
# Live scheduler logs
docker-compose logs -f scheduler

# Restart all services
docker-compose restart

# Stop all services
docker-compose down

# Check database tables
docker exec -it mike-ai-system-postgres-1 psql -U mike_admin -d mike_finance -c "\dt"
```

---

## Environment Variables

See [`.env.example`](.env.example) for the full list. Required groups:

- `POSTGRES_*` — database connection
- `GOOGLE_*` — Sheets API service account
- `SLACK_*` — bot token + channel IDs
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` — AI models
- `WHATSAPP_*` — Meta Cloud API credentials
- `JWT_SECRET` / `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` — dashboard auth
- `SCHEDULER_TIMEZONE` — defaults to `Europe/Amsterdam`

---

## Support

- Architecture details: [`docs/architecture.md`](docs/architecture.md)
- Disaster recovery: [`docs/disaster-recovery.md`](docs/disaster-recovery.md)
- Full deployment guide: [`HOW_TO_DEPLOY.md`](HOW_TO_DEPLOY.md)
