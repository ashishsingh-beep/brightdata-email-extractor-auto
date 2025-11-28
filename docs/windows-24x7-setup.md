# Run Stage 2 + Stage 3 24/7 on Windows (No UI changes)

This guide shows how to run a background worker continuously on Windows so Stage 2 (retrieve responses) and Stage 3 (extract emails) process automatically after Stage 1 uploads snapshots. UI remains unchanged.

## Prerequisites
- Python virtual environment created in project root: `.venv/`
- Dependencies installed: `pip install -r requirements.txt`
- `.env` present in project root with `BRIGHTDATA_URL`, `SUPABASE_URL`, `SUPABASE_KEY` (and optional `BRIGHTDATA_API_KEY`)
- Project path example used below: `C:\Users\Sane Alam\brightdata-email-extractor-auto`

## Option A — Windows Task Scheduler (Simple, periodic)
Runs the worker on a frequent schedule. Good for low load.

1) Open Task Scheduler
- Start Menu → Task Scheduler → Create Task

2) General
- Name: `brightdata-worker`
- Run whether user is logged on or not
- Run with highest privileges

3) Triggers
- New…
  - Begin the task: On a schedule → Daily
  - Repeat task every: 1 minute; for a duration of: Indefinitely
  - Enabled: Yes

4) Actions
- New… → Start a program
  - Program/script: `powershell.exe`
  - Add arguments (replace path if needed):
    ```
    -NoProfile -ExecutionPolicy Bypass -Command ". 'C:\\Users\\Sane Alam\\brightdata-email-extractor-auto\\.venv\\Scripts\\Activate.ps1'; cd 'C:\\Users\\Sane Alam\\brightdata-email-extractor-auto'; python worker.py >> .\\logs\\worker.log 2>&1"
    ```
  - Start in (optional): `C:\Users\Sane Alam\brightdata-email-extractor-auto`

5) Conditions/Settings
- Allow task to be run on demand
- If the task is already running, then the following rule applies: Stop the existing instance (or Do not start a new instance)

Create the folder `logs` in the project root for log output.

## Option B — NSSM Windows Service (Continuous, resilient)
Runs as a Windows Service that restarts automatically on failure.

1) Install NSSM
- Download from https://nssm.cc/download
- Extract and put `nssm.exe` on PATH or note its full path.

2) Install the service
Run PowerShell as Administrator:
```powershell
# Set variables
$project = "C:\\Users\\Sane Alam\\brightdata-email-extractor-auto"
$venvPy  = "$project\\.venv\\Scripts\\python.exe"
$worker  = "$project\\worker.py"
$logs    = "$project\\logs"

# Ensure logs directory exists
New-Item -ItemType Directory -Force -Path $logs | Out-Null

# Install the service
nssm install brightdata-worker $venvPy $worker

# Set working directory and I/O redirection
nssm set brightdata-worker AppDirectory $project
nssm set brightdata-worker AppStdout  "$logs\\worker.out.log"
nssm set brightdata-worker AppStderr  "$logs\\worker.err.log"

# Restart strategy
nssm set brightdata-worker Start SERVICE_AUTO_START
nssm set brightdata-worker AppStopMethodConsole 1500
nssm set brightdata-worker AppThrottle 5000

# Start service
nssm start brightdata-worker
```

3) Managing the service
```powershell
nssm restart brightdata-worker
nssm stop brightdata-worker
nssm remove brightdata-worker confirm
```

## Logging & Monitoring
- Logs are written to `.\\logs\\worker.out.log` and `.\\logs\\worker.err.log` (NSSM) or `logs\\worker.log` (Task Scheduler example).
- Rotate logs periodically or use a log rotation tool to avoid growth.

## Environment & Security
- The worker relies on `.env` in the project root. Keep it secured.
- Service account should have read/write permission to the project folder.

## Next Step
Once you approve, we will add a `worker.py` script that:
- Loops over unprocessed snapshots (Stage 2), fetches Bright Data snapshot JSON, saves to `response_table`, marks `processed=true`.
- Loops over unextracted responses (Stage 3), extracts emails, saves to `email_table`, marks `is_email_extracted=true`.
- Uses your `.venv` and `.env` with no UI changes.
