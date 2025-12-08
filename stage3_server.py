import os
import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from dotenv import load_dotenv

from email_scraper import SupabaseClient, logger


def extract_emails_from_text(text: str) -> list:
    import re
    pat = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    return list(set(re.findall(pat, text)))


def extract_emails_from_json(json_data) -> list:
    import json as _json
    s = _json.dumps(json_data)
    return extract_emails_from_text(s)


class Stage3Service:
    def __init__(self):
        load_dotenv()
        self._stop = threading.Event()
        self.stats = {
            "last_run_started": None,
            "last_run_finished": None,
            "rows_processed": 0,
            "emails_saved": 0,
            "duplicates": 0,
            "failed": 0,
        }
        supabase_url = os.getenv("SUPABASE_URL") or ""
        supabase_key = os.getenv("SUPABASE_KEY") or ""
        if not supabase_url or not supabase_key:
            raise RuntimeError("Missing environment variables for Stage3Service")
        self.supabase = SupabaseClient(supabase_url, supabase_key)

    def run_once(self, batch_size: int = 20):
        self.stats.update({
            "last_run_started": time.time(),
            "rows_processed": 0,
            "emails_saved": 0,
            "duplicates": 0,
            "failed": 0,
        })
        rows = self.supabase.get_unextracted_responses(limit=batch_size, offset=0) or []
        for row in rows:
            if self._stop.is_set():
                break
            snapshot_id = row.get("snapshot_id")
            response_data = row.get("response")
            try:
                emails = extract_emails_from_json(response_data) if response_data else []
                for email in emails:
                    ok, err = self.supabase.save_email(email)
                    if ok:
                        self.stats["emails_saved"] += 1
                    elif err == "duplicate":
                        self.stats["duplicates"] += 1
                    else:
                        self.stats["failed"] += 1
                        logger.error(f"Stage3 failed saving email {email}")
                if self.supabase.mark_email_extracted(snapshot_id):
                    self.stats["rows_processed"] += 1
                else:
                    self.stats["failed"] += 1
                    logger.error(f"Stage3 failed marking extracted for {snapshot_id}")
            except Exception as e:
                self.stats["failed"] += 1
                logger.exception(f"Stage3 error {snapshot_id}: {e}")
            time.sleep(0.1)
        self.stats["last_run_finished"] = time.time()

    def loop(self, interval_seconds: int = 30, batch_size: int = 20):
        logger.info("Stage3 server loop started")
        while not self._stop.is_set():
            self.run_once(batch_size=batch_size)
            for _ in range(interval_seconds):
                if self._stop.is_set():
                    break
                time.sleep(1)
        logger.info("Stage3 server loop stopped")

    def stop(self):
        self._stop.set()


class Stage3Handler(BaseHTTPRequestHandler):
    service: Stage3Service = None  # injected

    def _json(self, code: int, payload: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._json(200, {
                "status": "ok",
                "stats": Stage3Handler.service.stats,
                "stop_requested": Stage3Handler.service._stop.is_set(),
            })
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/run-once":
            threading.Thread(target=Stage3Handler.service.run_once, daemon=True).start()
            self._json(202, {"message": "run_once_started"})
        elif path == "/stop":
            Stage3Handler.service.stop()
            self._json(200, {"message": "stopping"})
        else:
            self._json(404, {"error": "not_found"})


def main(host: str = "0.0.0.0", port: int = 9003, interval: int = 30, batch_size: int = 20):
    service = Stage3Service()
    Stage3Handler.service = service
    server = HTTPServer((host, port), Stage3Handler)
    loop_thread = threading.Thread(target=service.loop, args=(interval, batch_size), daemon=True)
    loop_thread.start()
    logger.info(f"Stage3 HTTP server on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
        server.server_close()


if __name__ == "__main__":
    main()
