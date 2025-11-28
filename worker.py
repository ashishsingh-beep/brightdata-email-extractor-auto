import os
import time
import logging
import sys
from typing import Optional, Dict, List
from dotenv import load_dotenv

from email_scraper import BrightdataClient, SupabaseClient


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )


def validate_env() -> tuple[bool, str]:
    required = {
        "BRIGHTDATA_URL": os.getenv("BRIGHTDATA_URL"),
        "SUPABASE_URL": os.getenv("SUPABASE_URL"),
        "SUPABASE_KEY": os.getenv("SUPABASE_KEY"),
        "BRIGHTDATA_API_KEY": os.getenv("BRIGHTDATA_API_KEY"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        return False, f"Missing env vars: {', '.join(missing)}"
    return True, "ok"


def extract_emails_from_text(text: str) -> List[str]:
    import re
    pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    emails = re.findall(pattern, text)
    return list(set(emails))


def extract_emails_from_json(json_data) -> List[str]:
    import json
    data_str = json.dumps(json_data)
    return extract_emails_from_text(data_str)


def process_stage2(bright: BrightdataClient, supa: SupabaseClient) -> Dict[str, int]:
    snapshots = supa.get_unprocessed_snapshots()
    total = len(snapshots) if snapshots else 0
    successful = 0
    failed = 0
    skipped = 0

    if total == 0:
        return {"total": 0, "successful": 0, "failed": 0, "skipped": 0}

    for snap in snapshots:
        snapshot_id = snap.get("snapshot_id")
        if not snapshot_id:
            failed += 1
            continue

        try:
            data, is_running, is_valid, error_reason = bright.get_snapshot_data(snapshot_id)

            if not is_valid and is_running:
                skipped += 1
                logging.info(f"Stage2 skip (running): {snapshot_id}")
                continue

            if data is None:
                failed += 1
                logging.warning(f"Stage2 no data: {snapshot_id} ({error_reason})")
                continue

            ok, err_type = supa.save_response(snapshot_id, data)
            if ok:
                supa.mark_as_processed(snapshot_id)
                successful += 1
                logging.info(f"Stage2 saved: {snapshot_id}")
            elif err_type == "duplicate":
                supa.mark_as_processed(snapshot_id)
                skipped += 1
                logging.info(f"Stage2 duplicate: {snapshot_id}")
            else:
                failed += 1
                logging.error(f"Stage2 save failed: {snapshot_id}")
        except Exception as e:
            failed += 1
            logging.exception(f"Stage2 error for {snapshot_id}: {e}")

        time.sleep(0.2)

    return {"total": total, "successful": successful, "failed": failed, "skipped": skipped}


def process_stage3(supa: SupabaseClient, batch_size: int = 20) -> Dict[str, int]:
    total_processed = 0
    total_successful = 0
    total_failed = 0
    total_emails = 0
    total_duplicates = 0

    while True:
        rows = supa.get_unextracted_responses(limit=batch_size, offset=0)
        if not rows:
            break

        for row in rows:
            snapshot_id = row.get("snapshot_id")
            response_data = row.get("response")
            if not snapshot_id or response_data is None:
                total_failed += 1
                total_processed += 1
                continue

            try:
                emails = extract_emails_from_json(response_data)
                if emails:
                    for email in emails:
                        ok, err = supa.save_email(email)
                        if ok:
                            total_emails += 1
                        elif err == "duplicate":
                            total_duplicates += 1

                if supa.mark_email_extracted(snapshot_id):
                    total_successful += 1
                else:
                    total_failed += 1

            except Exception as e:
                total_failed += 1
                logging.exception(f"Stage3 error for {snapshot_id}: {e}")

            total_processed += 1

        time.sleep(0.2)

    return {
        "total": total_processed,
        "successful": total_successful,
        "failed": total_failed,
        "emails": total_emails,
        "duplicate_emails": total_duplicates,
    }


def main():
    load_dotenv()
    setup_logging()

    ok, msg = validate_env()
    if not ok:
        logging.error(msg)
        sys.exit(1)

    api_key = os.getenv("BRIGHTDATA_API_KEY", "")
    brightdata_url = os.getenv("BRIGHTDATA_URL", "")
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_KEY", "")

    bright = BrightdataClient(api_key, brightdata_url)
    supa = SupabaseClient(supabase_url, supabase_key)

    idle_sleep = int(os.getenv("WORKER_IDLE_SLEEP", "30"))

    logging.info("Worker started: Stage 2 + Stage 3 loop")
    while True:
        s2 = process_stage2(bright, supa)
        s3 = process_stage3(supa)

        logging.info(
            f"Stage2 total={s2['total']} ok={s2['successful']} skip={s2['skipped']} fail={s2['failed']} | "
            f"Stage3 total={s3['total']} ok={s3['successful']} fail={s3['failed']} emails={s3['emails']} dup={s3['duplicate_emails']}"
        )

        if s2["total"] == 0 and s3["total"] == 0:
            time.sleep(idle_sleep)
        else:
            time.sleep(5)


if __name__ == "__main__":
    main()
