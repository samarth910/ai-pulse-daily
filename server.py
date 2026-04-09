"""
Minimal static file server for Cloud Run / Railway / any container host.

Serves the contents of public/ on the PORT environment variable (default 8080).
Exposes endpoints:
  POST /run          — protected by X-Run-Token (for Cloud Scheduler)
  POST /run-now      — unauthenticated (for the UI "Run Now" button)
  POST /delete-run   — unauthenticated (for the UI "Delete" button)
Pipeline triggers are guarded by a lock to prevent concurrent runs.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import shutil
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("server")

PORT = int(os.environ.get("PORT", "8080"))
PUBLIC_DIR = Path(__file__).parent / "public"
DATA_DIR = Path(__file__).parent / "data"
RUN_SECRET = os.environ.get("RUN_SECRET", "")

_run_lock = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def do_POST(self):
        if self.path == "/run":
            token = self.headers.get("X-Run-Token", "")
            if not RUN_SECRET or not hmac.compare_digest(token, RUN_SECRET):
                self.send_error(403, "Forbidden - invalid or missing X-Run-Token")
                log.warning("Rejected /run request - bad token from %s", self.client_address[0])
                return
            self._start_pipeline()

        elif self.path == "/run-now":
            self._start_pipeline()

        elif self.path == "/delete-run":
            self._handle_delete_run()

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

    def _handle_delete_run(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        run_id = data.get("run_id", "")
        if not run_id or "/" in run_id or ".." in run_id:
            self.send_error(400, "Invalid run_id")
            return

        run_dir = PUBLIC_DIR / "runs" / run_id
        if run_dir.exists():
            shutil.rmtree(run_dir)
            log.info("Deleted run directory: %s", run_dir)

        idx_path = DATA_DIR / "runs_index.json"
        if idx_path.exists():
            try:
                index = json.loads(idx_path.read_text(encoding="utf-8"))
                index = [r for r in index if r.get("run_id") != run_id]
                idx_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
                log.info("Removed run %s from index (%d remaining)", run_id, len(index))
            except Exception as exc:
                log.error("Failed to update runs index: %s", exc)

        from src.render import render_homepage
        from src.state import load_runs_index
        render_homepage(load_runs_index())

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Run deleted\n")

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
        log.info("No index.html found - running initial pipeline")
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
