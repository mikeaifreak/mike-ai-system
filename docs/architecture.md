# System Architecture

## Overview

The Mike AI System is a modular pipeline that pulls financial data from Google Sheets, stores it in PostgreSQL, detects anomalies, and reports via Slack and WhatsApp.

```
Google Sheets (P&L)
       │
       │  sheets_parser.py
       ▼
PostgreSQL (daily_pl, weekly_summary, monthly_summary)
       │
       ├──▶ slack_reporter.py ──▶ Slack #finance channel
       │
       └──▶ whatsapp_alerts.py ──▶ WhatsApp (Mike)

n8n Orchestration Layer
  ├── Cron triggers → Execute Command → Python scripts
  ├── Error handler → Slack + WhatsApp alerts
  └── Backup workflow → GitHub API → this repo
```

---

## Data Flow: Morning Report (06:30 AM Mon–Fri)

```
n8n Schedule Trigger
  └── Execute Command: python main.py --mode morning_report
        ├── sheets_parser.fetch_pl_data()
        │     └── Google Sheets API → raw rows list
        ├── pl_processor.process_and_store(rows)
        │     ├── Upsert into daily_pl (ON CONFLICT DO UPDATE)
        │     ├── Recalculate weekly_summary + monthly_summary
        │     ├── Detect anomalies (ROAS < 1.5, refund% > 10%, negative margin)
        │     └── Log to agent_runs table
        └── slack_reporter.send_daily_report()
              ├── Query daily_pl for yesterday
              ├── Query mtd_summary view
              ├── Build Slack Block Kit message
              └── Post to #finance channel
```

---

## Data Flow: EOD Summary (21:00 daily)

```
n8n Schedule Trigger
  └── python main.py --mode eod_report
        └── whatsapp_alerts.send_eod_summary()
              ├── Query daily_pl for today
              ├── Format plain-text summary
              └── POST to WhatsApp Business Cloud API v18.0
```

---

## Data Flow: Nightly Backup (02:00 AM)

```
n8n Schedule Trigger
  └── GET /api/v1/workflows?limit=250  (n8n REST API)
        └── For each workflow:
              ├── GET github.com/repos/.../contents/{filePath}  → current SHA
              ├── Base64-encode workflow JSON
              └── PUT github.com/repos/.../contents/{filePath}  → upsert file
        └── Slack: "X workflows backed up"
```

---

## Database Schema Summary

| Table | Purpose |
|---|---|
| `daily_pl` | One row per day — all 15 P&L metrics from the sheet |
| `weekly_summary` | Auto-aggregated per ISO week — recalculated on every sync |
| `monthly_summary` | Auto-aggregated per calendar month |
| `reconciliation_log` | Audit trail of every sheet vs DB comparison run |
| `alerts_log` | Every Slack + WhatsApp message sent (delivered / failed) |
| `agent_runs` | Every pipeline execution — duration, rows, tokens, errors |
| `shopify_orders` | Stub table — reserved for System 2 Shopify integration |

**Views:**
- `latest_7_days` — last 7 rows of `daily_pl` (used by WhatsApp AI agent queries)
- `mtd_summary` — month-to-date aggregates (used in daily Slack report)

---

## Anomaly Detection Thresholds

| Metric | Threshold | Alert type |
|---|---|---|
| `roas` | < 1.5 | Low ROAS warning |
| `refund_pct` | > 10% | High refund rate warning |
| `profit_pct` | < 0 | Negative margin alert |

All thresholds are overridable via environment variables (`THRESHOLD_ROAS_LOW`, `THRESHOLD_REFUND_PCT_HIGH`).

---

## AI Models

| Model | Used for |
|---|---|
| Claude Sonnet (`claude-sonnet-4-6`) | Reasoning, anomaly explanation, WhatsApp Q&A (System 2) |
| GPT-4o | Bulk data parsing, classification (System 2 product research) |

---

## n8n Workflow Tags → Folder Mapping

| Tag on workflow | Saved to folder |
|---|---|
| `finance` | `n8n/workflows/finance/` |
| `product-research` | `n8n/workflows/product-research/` |
| `creative` | `n8n/workflows/creative/` |
| `whatsapp` | `n8n/workflows/whatsapp/` |
| `shared` | `n8n/workflows/shared/` |
| *(untagged)* | `n8n/workflows/shared/` |

---

## Deployment Environments

| Environment | n8n host | Python host | Database |
|---|---|---|---|
| Production (now) | n8n Cloud | n8n Cloud Execute Command | Supabase / managed PG |
| Production (planned) | Mac Mini self-hosted | Mac Mini | Supabase / managed PG |
| Staging | Local Docker | Local | Local PG |

---

## 7-Day Reprocessing Window

Every sync re-processes the last `REPROCESS_WINDOW_DAYS` (default: 7) days of data, regardless of whether the rows already exist in the database. This ensures that late supplier invoices — which may arrive days after the transaction date — are captured without manual intervention. Older historical rows are only written once (on first sync).

---

## Error Handling Strategy

1. Every Python function wraps its body in `try/except` and logs to `agent_runs` on failure
2. n8n workflows check the `exitCode` of Execute Command nodes and branch to Slack alerts on failure
3. All workflows declare `shared-global-error-handler-001` as their `errorWorkflow`
4. The global error handler sends Slack + WhatsApp alerts and logs to `agent_runs`
5. The `alerts_log` table captures every outbound notification including delivery status

---

## Future Systems

| System | Description | Status |
|---|---|---|
| System 2 — Product Research | Automated supplier/product discovery using AI | Planned |
| System 3 — Creative | Ad creative generation and testing pipeline | Planned |
| WhatsApp AI Agent | Natural-language queries against P&L data | Planned |
| Shopify Integration | Real-time order sync into `shopify_orders` table | Stub ready |
