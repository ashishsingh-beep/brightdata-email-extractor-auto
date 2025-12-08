## Bright Data Email Extractor (Auto)

Streamlit app that sends search queries to Bright Data, stores snapshot metadata in Supabase, retrieves results, extracts emails, and provides export/view capabilities.

### Overview
- Stage 0: Filter queries (remove CSV duplicates and already-seen queries in DB)
- Stage 1: Upload & process queries (create Bright Data snapshots; store in `snapshot_table`)
- Stage 2: Retrieve data (poll Bright Data, save responses in `response_table`)
- Stage 3: Extract emails (regex over JSON, save to `email_table`)
- Stage 4: View emails (filter by date and export CSV)

### Prerequisites
- Python 3.12 or 3.13 (Windows)
- Supabase project with the required tables
- Bright Data dataset trigger URL and API key

### Quick Start (Windows PowerShell)
```powershell
# 1) Create virtual environment
python -m venv .venv

# 2) Activate it (PowerShell)
.\.venv\Scripts\Activate.ps1

# 3) Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4) Create .env in project root
@"
BRIGHTDATA_URL=https://api.brightdata.com/datasets/v3/trigger?dataset_id=YOUR_DATASET_ID
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_KEY=YOUR_SERVICE_ROLE_OR_ANON_KEY
"@ | Out-File -Encoding UTF8 .env

# 5) Run the Streamlit app (always via venv Python)
python -m streamlit run app.py
```

### Environment Variables (.env)
- `BRIGHTDATA_URL`: Bright Data dataset trigger URL (v3). The app derives snapshot fetch URL from this.
- `SUPABASE_URL`: Supabase project URL
- `SUPABASE_KEY`: Supabase service role or anon key that can read/write the required tables

Optional (used by `email_scraper.py` CLI example):
- `BRIGHTDATA_API_KEY`: Bright Data API key (in the UI, you can also paste it in the sidebar)

Example file: see `.env.example` in the repo.

### Supabase Schema
Your project should have these tables/columns (names used by the app):
- `snapshot_table`
	- `snapshot_id` (text, primary/unique)
	- `processed` (boolean, default false)
	- `query` (text[] array; see `database_migration.sql`)
	- `created_at` (timestamp with time zone, default now())
- `response_table`
	- `snapshot_id` (text, primary/unique)
	- `response` (jsonb)
	- `is_email_extracted` (boolean, default false)
	- `created_at` (timestamp with time zone, default now())
- `email_table`
	- `email` (text, primary/unique)
	- `created_at` (timestamp with time zone, default now())

Run `database_migration.sql` to add the `query` column and index to `snapshot_table`.

### How It Works (Stages)
- Stage 0 — Filter Queries: upload CSV, de-duplicate within CSV and against `snapshot_table.query`, download filtered CSV.
- Stage 1 — Upload & Process: send queries in batches (default 2) to Bright Data; save `snapshot_id`+`query[]` to `snapshot_table`.
- Stage 2 — Retrieve Data: poll, then fetch each unprocessed snapshot’s JSON; save in `response_table`; mark snapshot `processed=true`.
- Stage 3 — Extract Emails: scan `response_table.response` with regex, save unique emails to `email_table`; mark row `is_email_extracted=true`.
- Stage 4 — View Emails: filter by date range and export CSV.

Automation: When you choose “Automated (Stage 1 → 2 → 3)” in Stage 1, the app uploads queries, waits/polls, retrieves data, and extracts emails in one flow.

### Troubleshooting
- Always activate the venv before running Streamlit. Mixing global/site-packages can cause import or type errors.
- Ensure your `.env` is at the project root and readable.
- Verify Supabase keys have insert/select/update permissions on the three tables.
- Bright Data: make sure the dataset is valid and the trigger URL is correct.

### 24/7 Worker (Windows)
- A headless worker `worker.py` runs Stage 2 + Stage 3 in one loop.
- NEW: Two standalone servers to run stages separately:
	- `stage2_server.py`: continuously retrieves Bright Data snapshots and saves responses.
	- `stage3_server.py`: continuously extracts emails from saved responses.
- Each server exposes simple HTTP endpoints:
	- `GET /health` — returns current stats.
	- `POST /run-once` — triggers a single pass immediately.
	- `POST /stop` — requests graceful shutdown.
- Requirements: set `BRIGHTDATA_API_KEY`, `BRIGHTDATA_URL`, `SUPABASE_URL`, `SUPABASE_KEY` in `.env`.

#### Run locally (PowerShell)
```powershell
# Stage 2 server (port 9002)
& ".\.venv\Scripts\python.exe" "stage2_server.py"

# Stage 3 server (port 9003)
& ".\.venv\Scripts\python.exe" "stage3_server.py"

# Check health in another terminal
Invoke-WebRequest -UseBasicParsing http://localhost:9002/health
Invoke-WebRequest -UseBasicParsing http://localhost:9003/health

# Trigger one pass
Invoke-RestMethod -Method Post -Uri http://localhost:9002/run-once
Invoke-RestMethod -Method Post -Uri http://localhost:9003/run-once

# Stop servers
Invoke-RestMethod -Method Post -Uri http://localhost:9002/stop
Invoke-RestMethod -Method Post -Uri http://localhost:9003/stop
```

#### Windows Services (NSSM)
- Install NSSM and create two services:
	- `nssm install Stage2Server "C:\Users\Admin\brightdata-email-extractor-auto\.venv\Scripts\python.exe" "C:\Users\Admin\brightdata-email-extractor-auto\stage2_server.py"`
	- `nssm install Stage3Server "C:\Users\Admin\brightdata-email-extractor-auto\.venv\Scripts\python.exe" "C:\Users\Admin\brightdata-email-extractor-auto\stage3_server.py"`
- Set startup type to Automatic; configure stdout/stderr log files.
- Ensure service working directory is the repo root so `.env` loads.

#### Notes
- Stage 2 and Stage 3 only communicate via Supabase tables—no direct coupling.
- Stage 2 leaves "running" snapshots unprocessed for retry; uses NDJSON fallback on 422.
- Stage 3 marks `is_email_extracted=true` even if zero emails found to avoid reprocessing.

### Useful Commands (PowerShell)
```powershell
# Activate venv
.\.venv\Scripts\Activate.ps1

# Run the app
python -m streamlit run app.py
python worker.py

# Run separate servers
python stage2_server.py
python stage3_server.py

# Freeze dependencies
pip freeze > requirements.lock.txt

# Deactivate venv
Deactivate
```
