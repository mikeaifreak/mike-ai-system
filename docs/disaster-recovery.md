# Disaster Recovery Runbook

Complete restore procedure for the Mike AI System after data loss, server failure, or migration to a new machine.

**Target RTO:** < 2 hours from start to live traffic  
**Target RPO:** < 24 hours (last nightly backup)

---

## What's Backed Up Where

| Asset | Backup location | Frequency |
|---|---|---|
| n8n workflow JSONs | This GitHub repo (`n8n/workflows/`) | Daily at 02:00 AM |
| PostgreSQL schema | `database/schema.sql` in this repo | On change (via git) |
| Python source code | `scripts/python/` in this repo | On change (via git) |
| Environment variables | 1Password / secret manager (NOT git) | Manual |
| PostgreSQL data (P&L rows) | Supabase / managed DB backup | Per DB provider |

**What is NOT in git:** `.env` files, real credentials, PostgreSQL row data.

---

## Scenario 1 — Full Machine Loss (new Mac Mini or new cloud server)

### Step 1: Provision the machine

```bash
# Install n8n
npm install -g n8n

# Install Python 3.12+
# Install PostgreSQL client tools
# Install git
```

### Step 2: Clone the repo

```bash
git clone git@github.com:YOUR_ORG/mike-ai-system.git
cd mike-ai-system
```

### Step 3: Restore environment variables

Pull credentials from 1Password / secret manager and create `.env`:

```bash
cp .env.example .env
# Fill in every value — refer to .env.example comments
nano .env
```

### Step 4: Restore the database

```bash
# Apply schema (creates all tables, views, triggers)
psql "$POSTGRES_URL" -f database/schema.sql

# If you have a data dump:
pg_restore -d "$POSTGRES_URL" /path/to/backup.dump
# OR for SQL dump:
psql "$POSTGRES_URL" < /path/to/backup.sql
```

### Step 5: Install Python dependencies

```bash
cd scripts/python
pip install -r requirements.txt
cd ../..
```

### Step 6: Smoke-test the Python pipeline

```bash
python scripts/python/main.py --mode sync_only
# Expected: no errors, rows synced from Google Sheet
```

### Step 7: Start n8n

```bash
# Self-hosted with env file:
n8n start

# Or with Docker:
docker run -d --name n8n \
  --env-file .env \
  -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  n8nio/n8n
```

### Step 8: Restore all workflows

```bash
chmod +x scripts/*.sh
./scripts/restore-workflows-from-git.sh
# This: (1) git pulls latest, (2) imports every JSON into n8n via API
```

### Step 9: Verify in n8n UI

- Open n8n at `http://localhost:5678`
- Check all workflows are present and **active**
- Manually trigger `Finance — Daily P&L Morning Report` → confirm it succeeds
- Check the Slack channel for the test report

### Step 10: Re-activate cron schedules

Workflows imported via API are **inactive by default** as a safety measure.
In the n8n UI, activate:

- [ ] `Finance — Daily P&L Morning Report`
- [ ] `Finance — Hourly Sheet Sync (Silent)`
- [ ] `Finance — EOD WhatsApp Summary`
- [ ] `Finance — Weekly Reconciliation Audit`
- [ ] `Shared — Backup All Workflows to GitHub`
- [ ] `Shared — Global Error Handler`

```bash
# Or activate all via API:
N8N_BASE_URL=http://localhost:5678
N8N_API_KEY=your-key

# List all workflow IDs and activate each
curl -s -H "X-N8N-API-KEY: $N8N_API_KEY" \
  "$N8N_BASE_URL/api/v1/workflows?limit=250" | \
  python3 -c "
import sys, json
for wf in json.load(sys.stdin)['data']:
    print(wf['id'], wf['name'])
"
```

---

## Scenario 2 — n8n Data Loss Only (workflows deleted)

The machine and database are fine, only n8n's internal workflow store was wiped.

```bash
cd mike-ai-system
git pull origin main
./scripts/restore-workflows-from-git.sh
# Then manually activate workflows in UI (see Step 10 above)
```

Total time: ~5 minutes.

---

## Scenario 3 — Database Corruption / Data Loss

Python code and n8n are fine, but PostgreSQL data is gone.

```bash
# 1. Recreate schema
psql "$POSTGRES_URL" -f database/schema.sql

# 2. Re-sync all historical data from Google Sheet
python scripts/python/main.py --mode sync_only
# This re-fetches all 1005 rows and upserts them

# 3. Run reconciliation to confirm
python scripts/python/main.py --mode reconcile
```

---

## Scenario 4 — Accidental Workflow Deletion (single workflow)

```bash
# Restore one specific folder
./scripts/restore-workflows-from-git.sh --folder finance

# Or restore a specific file manually via API
curl -X POST \
  -H "X-N8N-API-KEY: $N8N_API_KEY" \
  -H "Content-Type: application/json" \
  -d @n8n/workflows/finance/daily-pl-morning-report.json \
  "$N8N_BASE_URL/api/v1/workflows"
```

---

## Scenario 5 — Rollback a Workflow Change

```bash
# Find the last known good commit
git log --oneline n8n/workflows/finance/daily-pl-morning-report.json

# Restore that version
git show <COMMIT_SHA>:n8n/workflows/finance/daily-pl-morning-report.json > /tmp/rollback.json

# Import it (will UPDATE the existing workflow)
WF_ID="fin-morning-report-001"
curl -X PATCH \
  -H "X-N8N-API-KEY: $N8N_API_KEY" \
  -H "Content-Type: application/json" \
  -d @/tmp/rollback.json \
  "$N8N_BASE_URL/api/v1/workflows/$WF_ID"
```

---

## Migration: n8n Cloud → Mac Mini Self-Hosted

1. On Mac Mini: install n8n, clone repo, create `.env` (update `N8N_BASE_URL`)
2. `psql "$POSTGRES_URL" -f database/schema.sql`
3. `pip install -r scripts/python/requirements.txt`
4. `./scripts/restore-workflows-from-git.sh`
5. In old n8n Cloud: deactivate all cron workflows
6. In new Mac Mini n8n: activate all workflows
7. Monitor Slack for one full cycle (morning report the next day)
8. Decommission n8n Cloud instance

---

## Verification Checklist After Any Restore

- [ ] `psql "$POSTGRES_URL" -c "SELECT COUNT(*) FROM daily_pl"` — shows expected row count
- [ ] `python scripts/python/main.py --mode reconcile` — shows 0 mismatches
- [ ] n8n UI shows all workflows as active
- [ ] Manually trigger morning report — Slack message appears in correct channel
- [ ] Manually trigger EOD summary — WhatsApp message received by Mike
- [ ] `shared/backup-to-github.json` runs at 02:00 AM and commits to GitHub
