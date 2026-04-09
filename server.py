"""
Minimal static file server for Cloud Run / Railway / any container host.

Serves the contents of public/ on the PORT environment variable (default 8080).
Exposes /run to trigger a pipeline run — protected by a secret token so only
you or Cloud Scheduler can call it.
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
            self.send_response(202)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Pipeline triggered\n")
            threading.Thread(target=self._trigger_pipeline, daemon=True).start()
        else:
            self.send_error(404)

    @staticmethod
    def _trigger_pipeline():
        try:
            from src.main import run
            run()
            log.info("Pipeline run completed via /run endpoint")
        except Exception:
            log.exception("Pipeline run failed via /run endpoint")

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
