import os
import json
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from dotenv import load_dotenv

from email_scraper import BrightdataClient, SupabaseClient, logger


class Stage2Service:
    def __init__(self):
        load_dotenv()
        self._stop = threading.Event()
        self.stats = {
            "last_run_started": None,
            "last_run_finished": None,
            "processed": 0,
            "saved": 0,
            "skipped": 0,
            "failed": 0,
            "invalid": 0,
        }
        api_key = (os.getenv("BRIGHTDATA_API_KEY") or "").strip()
        brightdata_url = os.getenv("BRIGHTDATA_URL") or ""
        supabase_url = os.getenv("SUPABASE_URL") or ""
        supabase_key = os.getenv("SUPABASE_KEY") or ""
        if not api_key or not brightdata_url or not supabase_url or not supabase_key:
            raise RuntimeError("Missing environment variables for Stage2Service")
        self.brightdata = BrightdataClient(api_key, brightdata_url)
        self.supabase = SupabaseClient(supabase_url, supabase_key)

    def run_once(self):
        self.stats.update({
            "last_run_started": time.time(),
            "processed": 0,
            "saved": 0,
            "skipped": 0,
            "failed": 0,
            "invalid": 0,
        })
        snapshots = self.supabase.get_unprocessed_snapshots() or []
        for s in snapshots:
            if self._stop.is_set():
                break
            snapshot_id = s.get("snapshot_id")
            try:
                data, is_running, is_valid, error_reason = self.brightdata.get_snapshot_data(snapshot_id)
                self.stats["processed"] += 1
                if not is_valid:
                    self.stats["invalid"] += 1
                    logger.warning(f"Stage2 invalid snapshot {snapshot_id}: {error_reason}")
                    # leave unprocessed for retry later
                    continue
                if not data:
                    self.stats["skipped"] += 1
                    logger.info(f"Stage2 no data for {snapshot_id}")
                    continue
                ok, err = self.supabase.save_response(snapshot_id, data)
                if ok:
                    self.supabase.mark_as_processed(snapshot_id)
                    self.stats["saved"] += 1
                    logger.info(f"Stage2 saved response for {snapshot_id}")
                elif err == "duplicate":
                    self.supabase.mark_as_processed(snapshot_id)
                    self.stats["skipped"] += 1
                    logger.info(f"Stage2 duplicate response for {snapshot_id}")
                else:
                    self.stats["failed"] += 1
                    logger.error(f"Stage2 failed saving {snapshot_id}")
            except Exception as e:
                self.stats["failed"] += 1
                logger.exception(f"Stage2 error {snapshot_id}: {e}")
            time.sleep(0.2)
        self.stats["last_run_finished"] = time.time()

    def loop(self, interval_seconds: int = 30):
        logger.info("Stage2 server loop started")
        while not self._stop.is_set():
            self.run_once()
            for _ in range(interval_seconds):
                if self._stop.is_set():
                    break
                time.sleep(1)
        logger.info("Stage2 server loop stopped")

    def stop(self):
        self._stop.set()


class Stage2Handler(BaseHTTPRequestHandler):
    service: Stage2Service = None  # injected

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
                "stats": Stage2Handler.service.stats,
                "stop_requested": Stage2Handler.service._stop.is_set(),
            })
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/run-once":
            threading.Thread(target=Stage2Handler.service.run_once, daemon=True).start()
            self._json(202, {"message": "run_once_started"})
        elif path == "/stop":
            Stage2Handler.service.stop()
            self._json(200, {"message": "stopping"})
        else:
            self._json(404, {"error": "not_found"})


def main(host: str = "0.0.0.0", port: int = 9002, interval: int = 30):
    service = Stage2Service()
    Stage2Handler.service = service
    server = HTTPServer((host, port), Stage2Handler)
    loop_thread = threading.Thread(target=service.loop, args=(interval,), daemon=True)
    loop_thread.start()
    logger.info(f"Stage2 HTTP server on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
        server.server_close()


if __name__ == "__main__":
    main()
