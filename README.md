# Mike AI System

Automated Finance Controller + AI Agent pipelines for Mike's e-commerce / dropshipping business.

**Stack:** Python · PostgreSQL · Google Sheets API · Slack · WhatsApp Business API · n8n · Claude Sonnet · GPT-4o

---

## Repository Structure

```
mike-ai-system/
├── .github/workflows/          ← GitHub Actions CI (JSON validation)
├── database/
│   └── schema.sql              ← PostgreSQL schema (tables, views, triggers)
├── docs/
│   ├── architecture.md         ← System design & data flow
│   └── disaster-recovery.md    ← Full restore runbook
├── n8n/
│   ├── workflows/
│   │   ├── finance/            ← P&L pipeline workflows
│   │   ├── product-research/   ← (System 2 — future)
│   │   ├── creative/           ← (System 3 — future)
│   │   ├── whatsapp/           ← WhatsApp AI agent workflows
│   │   └── shared/             ← Backup, error handler, utilities
│   └── environments/           ← Per-environment .env templates
├── scripts/
│   ├── backup-workflows-to-git.sh
│   ├── restore-workflows-from-git.sh
│   ├── export-all-workflows.sh
│   ├── import-all-workflows.sh
│   └── python/                 ← Finance pipeline Python source
└── .env.example
```

---

## Quick Start

### 1. Clone & configure

```bash
git clone git@github.com:YOUR_ORG/mike-ai-system.git
cd mike-ai-system
cp .env.example .env
# Fill in all values in .env
```

### 2. Apply the database schema

```bash
psql "$POSTGRES_URL" -f database/schema.sql
```

### 3. Install Python dependencies

```bash
cd scripts/python
pip install -r requirements.txt
```

### 4. Test the pipeline manually

```bash
# Full morning run
python scripts/python/main.py --mode morning_report

# Sync sheet only
python scripts/python/main.py --mode sync_only

# EOD WhatsApp summary
python scripts/python/main.py --mode eod_report

# Reconciliation check
python scripts/python/main.py --mode reconcile
```

### 5. Import workflows into n8n

```bash
chmod +x scripts/*.sh
./scripts/import-all-workflows.sh
```

---

## n8n Workflow Inventory

### Finance Pipelines

| File | Schedule | What it does |
|---|---|---|
| `finance/daily-pl-morning-report.json` | 06:30 Mon–Fri | Sync sheet → DB → Slack P&L report |
| `finance/sheet-sync-only.json` | Hourly | Re-sync last 7 days silently |
| `finance/eod-whatsapp-summary.json` | 21:00 daily | WhatsApp EOD summary to Mike |
| `finance/weekly-reconciliation.json` | Mon 08:00 | Sheet vs DB row-count audit |

### Shared Infrastructure

| File | Schedule | What it does |
|---|---|---|
| `shared/backup-to-github.json` | 02:00 daily | Export all workflows → push to this repo |
| `shared/global-error-handler.json` | On error | Catch unhandled failures → Slack + WhatsApp |

---

## Backup & Version Control

### Automated daily backup

The `shared/backup-to-github.json` workflow runs at **02:00 AM** every night.
It uses the n8n REST API + GitHub API to export every active workflow as a `.json` file and commit it to this repository.

No manual action required once the workflow is imported and activated.

### Manual backup (emergency)

```bash
# Export every workflow from n8n and push to GitHub
./scripts/backup-workflows-to-git.sh
```

### Manual export only (no git push)

```bash
# Dumps all workflow JSONs into n8n/workflows/ by tag/folder
./scripts/export-all-workflows.sh
```

---

## Restore from GitHub

Full restore runbook: [`docs/disaster-recovery.md`](docs/disaster-recovery.md)

**TL;DR — restore everything in 3 commands:**

```bash
git pull origin main
./scripts/restore-workflows-from-git.sh
psql "$POSTGRES_URL" -f database/schema.sql
```

---

## n8n Source Control (Enterprise / Cloud Teams)

If your n8n instance has **Source Control** enabled (n8n ≥ 1.x Teams / Enterprise):

1. Go to **Settings → Source Control**
2. Connect to this repository
3. Branch: `main` (production) or `staging` for testing
4. Push/pull directly from the n8n UI

For n8n Community or n8n Cloud Starter, use the shell scripts instead.

---

## Environment Variables

See [`.env.example`](.env.example) for the full list with explanations.

Required groups:
- `GOOGLE_*` — Sheets API service account
- `POSTGRES_URL` — database connection string
- `SLACK_*` — bot token + channel
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` — AI models
- `WHATSAPP_*` — Meta Cloud API credentials
- `N8N_BASE_URL` / `N8N_API_KEY` — for the backup workflow
- `GITHUB_TOKEN` / `GITHUB_REPO` — for automated git push

---

## Adding a New Workflow

1. Build the workflow in n8n
2. Tag it with the correct folder name: `finance`, `product-research`, `creative`, `whatsapp`, or `shared`
3. Run `./scripts/export-all-workflows.sh` — it lands in the correct subfolder automatically
4. `git add n8n/workflows/ && git commit -m "feat: add <workflow-name>"`
5. Push → GitHub Actions validates the JSON

---

## Deployment Targets

| Target | Status | Notes |
|---|---|---|
| n8n Cloud | Active (now) | Import workflows via UI or CLI |
| Mac Mini (self-hosted) | Planned | Run `./scripts/import-all-workflows.sh` after setup |

Migration from Cloud → Mac Mini: pull this repo, run schema + import script, update `.env`.

---

## Support

- Architecture details: [`docs/architecture.md`](docs/architecture.md)
- Disaster recovery: [`docs/disaster-recovery.md`](docs/disaster-recovery.md)
