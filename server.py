"""
Minimal static file server for Cloud Run / Railway / any container host.

Serves the contents of public/ on the PORT environment variable (default 8080).
Exposes two trigger endpoints:
  POST /run      — protected by X-Run-Token (for Cloud Scheduler)
  POST /run-now  — unauthenticated (for the UI "Run Now" button)
Both are guarded by a lock to prevent concurrent pipeline runs.
"""

from __future__ import annotations

import hmac
import logging
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("server")

PORT = int(os.environ.get("PORT", "8080"))
PUBLIC_DIR = Path(__file__).parent / "public"
RUN_SECRET = os.environ.get("RUN_SECRET", "")

_run_lock = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def do_POST(self):
        if self.path == "/run":
            token = self.headers.get("X-Run-Token", "")
            if not RUN_SECRET or not hmac.compare_digest(token, RUN_SECRET):
                self.send_error(403, "Forbidden — invalid or missing X-Run-Token")
                log.warning("Rejected /run request — bad token from %s", self.client_address[0])
                return
            self._start_pipeline()

        elif self.path == "/run-now":
            self._start_pipeline()

        else:
            self.send_error(404)

    def _start_pipeline(self):
        if not _run_lock.acquire(blocking=False):
            self.send_response(429)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"A pipeline run is already in progress\n")
            return

        self.send_response(202)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Pipeline triggered\n")
        threading.Thread(target=self._run_pipeline, daemon=True).start()

    @staticmethod
    def _run_pipeline():
        try:
            from src.main import run
            run()
            log.info("Pipeline run completed")
        except Exception:
            log.exception("Pipeline run failed")
        finally:
            _run_lock.release()

    def log_message(self, format, *args):
        log.info(format, *args)


def main():
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    if not (PUBLIC_DIR / "index.html").exists():
        log.info("No index.html found — running initial pipeline")
        try:
            from src.main import run
            run()
        except Exception:
            log.exception("Initial pipeline failed; serving whatever is in public/")

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    log.info("Serving %s on port %d", PUBLIC_DIR, PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
