# Stages and Automation Guide

This document explains each stage at a high level and goes deep on Stage 2 and Stage 3, including validation, batching, idempotency, and error handling.

## Stage 0 — Filter Queries
- Input: CSV with a `Query` column (first column used)
- Flow:
  - Load queries and strip empties
  - Remove duplicates (case-insensitive)
  - Fetch all historical queries from `snapshot_table.query[]` in Supabase
  - Split into new vs. existing; allow download of a filtered CSV containing only new queries
- Output: Filtered list for Stage 1 (or a CSV download)

## Stage 1 — Upload & Process
- Batching: Default 2 queries per Bright Data request
- API: `POST` Bright Data trigger URL (`BRIGHTDATA_URL`)
- Response: JSON with `snapshot_id`
- DB Write: Save one row per snapshot in `snapshot_table` with `snapshot_id`, `processed=false`, and the batch `query[]` (the two queries)
- Outcome: `successful_snapshots`, `failed_batches`, `snapshot_query_map`

## Stage 2 — Retrieve Data (Deep Dive)
- Goal: Move data from Bright Data into `response_table` and mark `snapshot_table.processed=true`
- Input: `snapshot_table` rows where `processed=false`
- Steps in Automated Pipeline:
  1. Polling period after Stage 1: the app polls for up to 10 minutes (20 attempts × 30s) to allow Bright Data processing to complete. It tests readiness by attempting to fetch one snapshot and examining validity.
  2. For every unprocessed snapshot, call Bright Data Snapshot API:
     - Snapshot URL is derived from `BRIGHTDATA_URL`: replace `/trigger` with `/snapshot/{snapshot_id}?format=json`.
     - The client returns `(data, is_running, is_valid, error_reason)`.
  3. Validation rules (see `BrightdataClient.get_snapshot_data`):
     - Invalid if status is `running` inside JSON (keeps `processed=false` so it can be retried later)
     - Invalid if JSON contains `error` and the total payload size is < 2000 bytes (likely transport/error stub)
  4. Persisting valid responses:
     - Insert into `response_table` with `snapshot_id`, `response` JSON, `is_email_extracted=false`
     - If insert succeeds or is a duplicate, mark `snapshot_table.processed=true`
  5. Counters: `successful`, `failed`, `skipped`, `invalid_responses`
- Idempotency & Duplicates:
  - If `response_table` has a unique/PK on `snapshot_id`, duplicates are handled (reported as duplicate; `snapshot_table.processed` is still set to true)
- Retry Strategy:
  - Invalid responses are left with `processed=false` to be retried in a later run

## Stage 3 — Extract Emails (Deep Dive)
- Goal: Extract and persist emails from JSON responses in `response_table`
- Input: `response_table` rows where `is_email_extracted=false`
- Extraction:
  - Convert the JSON document to a string and run a regex: `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b`
  - De-duplicate within the batch in-memory; each address is inserted individually
- Batching & Progress:
  - Process in batches of 20 rows (config in code); fetch is always with `offset=0` since rows get marked extracted as they are processed
  - Live metrics: processed count, emails found, duplicates, and errors
- Persistence:
  - `email_table`: insert one row per unique email
  - Duplicates: if unique constraint triggers, counted as duplicate and skipped
  - After attempting all email inserts for a response row, set `is_email_extracted=true` for that `snapshot_id`
- Idempotency:
  - Because of the `email` unique constraint, re-runs won’t create duplicates
  - Marking `is_email_extracted=true` ensures each response row is only processed once

## Stage 4 — View Emails
- Date filters on `email_table.created_at`
- Displays a table and provides CSV export

## Automated Mode (Stage 1 → 2 → 3)
- Triggered in Stage 1 by selecting “Automated” mode
- Flow:
  1. Stage 1: Create snapshots and write to `snapshot_table`
  2. Poll: Wait up to ~10 minutes for Bright Data readiness (break early if valid data appears)
  3. Stage 2: Retrieve valid responses into `response_table` and mark snapshots processed
  4. Stage 3: Extract emails from the newly stored responses into `email_table`
- Summary metrics are displayed at the end

## Operational Tips
- Ensure Bright Data dataset is healthy; invalid/running snapshots will be retried later
- Verify DB permissions allow insert/update/select on all three tables
- If you need hands-off automation, you can run a nightly job that calls Stage 2 and Stage 3 via the UI or extract the logic into a small scheduler script

## Error Handling Summary
- Network/JSON errors while calling Bright Data are caught and counted as failures
- Database duplicates are explicitly handled and reported as `duplicate`
- Invalid/running snapshots are left unprocessed to be retried
