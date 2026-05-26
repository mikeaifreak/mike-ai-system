# HOW TO DEPLOY — Mike AI Mission Control
**Single source of truth for running this system on Mike's Mac Mini.**

---

## PHASE 1 — MAC MINI SETUP (one time only)

### Step 1: Install Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the on-screen prompts. When done, run the two `eval` commands it prints to add Homebrew to your PATH.

---

### Step 2: Install Docker Desktop

```bash
brew install --cask docker
```

Then open **Docker Desktop** from Applications and wait for the whale icon in the menu bar to stop animating. Docker must be running before any `docker-compose` command will work.

---

### Step 3: Install Git

```bash
brew install git
```

---

### Step 4: Install Tailscale (permanent remote access)

```bash
brew install --cask tailscale
```

Open **Tailscale** from Applications → sign in with Mike's Google account → approve the device. This gives you SSH access to Mike's Mac from anywhere without port forwarding.

---

## PHASE 2 — PROJECT SETUP (one time only)

### Step 5: Clone the repository

```bash
cd ~
git clone https://github.com/mikeaifreak/mike-ai-system.git
cd mike-ai-system
```

---

### Step 6: Create the .env file

```bash
cp .env.example .env
nano .env
```

Fill in every value:

```env
# PostgreSQL
POSTGRES_DB=mike_finance
POSTGRES_USER=mike_admin
POSTGRES_PASSWORD=[strong password — at least 20 random chars]
POSTGRES_URL=postgresql://mike_admin:[password]@postgres:5432/mike_finance

# AI models
ANTHROPIC_API_KEY=[Mike's Claude API key from console.anthropic.com]
OPENAI_API_KEY=[Mike's OpenAI API key from platform.openai.com]

# Slack
SLACK_BOT_TOKEN=[Bot token from Slack app — starts with xoxb-]
SLACK_CHANNEL_ID=[#finance-reports channel ID]
SLACK_REPORTS_CHANNEL=[#finance-reports channel ID]
SLACK_ALERTS_CHANNEL=[#alerts channel ID]
SLACK_INVOICES_CHANNEL=[#supplier-invoices channel ID]

# Google Sheets
GOOGLE_SHEET_ID=[spreadsheet ID from the URL]
GOOGLE_SERVICE_ACCOUNT_JSON=[full JSON string of service account key file]

# WhatsApp Business Cloud API (Meta)
WHATSAPP_ACCESS_TOKEN=[permanent token from Meta Business dashboard]
WHATSAPP_PHONE_NUMBER_ID=[phone number ID from Meta dashboard]
WHATSAPP_RECIPIENT_NUMBER=[Mike's WhatsApp number with country code, e.g. 31612345678]

# Shopify
SHOPIFY_STORE_URL=[yourstore.myshopify.com]
SHOPIFY_API_TOKEN=[Admin API access token]

# Dashboard auth
JWT_SECRET=[generate with: openssl rand -hex 32]
DASHBOARD_USERNAME=mike
DASHBOARD_PASSWORD=[strong password]

# Scheduler timezone
SCHEDULER_TIMEZONE=Europe/Amsterdam
```

Save and close: `Ctrl+X` → `Y` → `Enter`

---

## PHASE 3 — LAUNCH (one time only)

### Step 7: Build and start all services

```bash
cd ~/mike-ai-system
docker-compose up --build -d
```

This builds 4 Docker images and starts all containers. First build takes 3–5 minutes.

---

### Step 8: Verify all services are running

```bash
docker-compose ps
```

Expected output — all four services must show `Up`:

```
NAME                             STATUS
mike-ai-system-postgres-1        Up (healthy)
mike-ai-system-scheduler-1       Up
mike-ai-system-dashboard-backend-1   Up
mike-ai-system-dashboard-frontend-1  Up
```

---

### Step 9: Confirm database tables were created

```bash
docker exec -it mike-ai-system-postgres-1 psql -U mike_admin -d mike_finance -c "\dt"
```

Expected — 7 tables listed:

```
 Schema |        Name          | Type  |   Owner
--------+----------------------+-------+-----------
 public | agent_runs           | table | mike_admin
 public | alerts_log           | table | mike_admin
 public | daily_pl             | table | mike_admin
 public | monthly_summary      | table | mike_admin
 public | reconciliation_log   | table | mike_admin
 public | shopify_orders       | table | mike_admin
 public | weekly_summary       | table | mike_admin
```

---

### Step 10: Run first manual sync

```bash
docker exec mike-ai-system-scheduler-1 python main.py --mode sync_only
```

Expected: logs show rows fetched from Google Sheets and stored to DB. No errors.

---

### Step 11: Run first manual morning report

```bash
docker exec mike-ai-system-scheduler-1 python main.py --mode morning_report
```

Expected: Slack receives the P&L daily report in `#finance-reports`.

---

### Step 12: Open the Mission Control dashboard

Open a browser on Mike's Mac and go to:

```
http://localhost:3000
```

Log in with `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` from `.env`.

---

### Step 13: Check scheduler is running

```bash
docker-compose logs scheduler | head -40
```

You should see the startup table listing all 5 jobs with their next run times.

---

## PHASE 4 — REMOTE ACCESS SETUP (one time only)

### Step 14: Install Cloudflare Tunnel

```bash
brew install cloudflared
cloudflared tunnel login
cloudflared tunnel create mike-ai
```

Note the tunnel ID printed — you need it in the next command.

---

### Step 15: Route the tunnel to the dashboard

```bash
cloudflared tunnel route dns mike-ai dashboard.mikeai.com
```

> Replace `dashboard.mikeai.com` with whatever domain Mike owns and has pointed at Cloudflare.

---

### Step 16: Create the Cloudflare Tunnel config file

```bash
mkdir -p ~/.cloudflared
nano ~/.cloudflared/config.yml
```

Paste this (replace `[TUNNEL-ID]` with the ID from Step 14):

```yaml
tunnel: [TUNNEL-ID]
credentials-file: /Users/mike/.cloudflared/[TUNNEL-ID].json
ingress:
  - hostname: dashboard.mikeai.com
    service: http://localhost:3000
  - service: http_status:404
```

Save and close: `Ctrl+X` → `Y` → `Enter`

---

### Step 17: Test the tunnel manually

```bash
cloudflared tunnel run mike-ai
```

Open `https://dashboard.mikeai.com` in a browser. If it loads, stop with `Ctrl+C` and move to Step 18.

---

### Step 18: Make the tunnel start on every reboot

```bash
sudo cloudflared service install
sudo launchctl start com.cloudflare.cloudflared
```

---

### Step 19: Prevent Mac Mini from sleeping

**System Settings → Battery →**
- Turn off **"Put hard disks to sleep when possible"**
- Turn on **"Prevent automatic sleeping when display is off"**

**System Settings → General → Sharing →**
- Enable **Remote Login** (enables SSH via Tailscale)

---

## PHASE 5 — DAILY OPERATIONS (fully automatic)

Once the system is running, it manages itself:

| Time (Amsterdam) | Action |
|---|---|
| 06:50 | Syncs P&L data from Google Sheet |
| 07:00 | Sends daily report to Mike's Slack |
| Every 30 min | Reads + logs supplier invoices from Slack |
| 21:00 | Sends EOD summary to Mike's WhatsApp |
| 00:00 | Runs nightly sheet-vs-DB reconciliation |

**Mike's dashboard:** `https://dashboard.mikeai.com`  
**NOVA AI chat** is available inside the dashboard 24/7.

If a job fails, the scheduler sends an alert to `#alerts` on Slack automatically.

---

## USEFUL COMMANDS FOR ONGOING MAINTENANCE

```bash
# Live logs from the scheduler
docker-compose logs -f scheduler

# Live logs from the API backend
docker-compose logs -f dashboard-backend

# Restart everything (e.g. after .env change)
docker-compose restart

# Full stop
docker-compose down

# Full stop + rebuild (after a git pull with code changes)
docker-compose up --build -d

# Manual pipeline runs
docker exec mike-ai-system-scheduler-1 python main.py --mode sync_only
docker exec mike-ai-system-scheduler-1 python main.py --mode morning_report
docker exec mike-ai-system-scheduler-1 python main.py --mode eod_report
docker exec mike-ai-system-scheduler-1 python main.py --mode reconcile
docker exec mike-ai-system-scheduler-1 python main.py --mode read_invoices

# Query the database directly
docker exec -it mike-ai-system-postgres-1 psql -U mike_admin -d mike_finance

# Check recent agent runs
docker exec -it mike-ai-system-postgres-1 psql -U mike_admin -d mike_finance \
  -c "SELECT agent_name, status, duration_ms, started_at FROM agent_runs ORDER BY started_at DESC LIMIT 20;"

# Pull latest code and redeploy
cd ~/mike-ai-system && git pull && docker-compose up --build -d
```

---

## AFTER A MAC MINI REBOOT

Everything restarts automatically because all services use `restart: always` in docker-compose. You do not need to do anything — Docker Desktop launches on login, and all containers come back up on their own.

To confirm after a reboot:

```bash
docker-compose ps
```
