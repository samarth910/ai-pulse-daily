"""
State persistence — the anti-stale backbone.

Manages three files:
  data/archive.jsonl   One JSON object per line for every item ever published.
  data/history.json    Rolling window of recent event keys / headlines for
                       injection into the curator prompt.
  data/runs_index.json List of all pipeline runs (for homepage rendering).

First-run safe: missing or empty files are bootstrapped silently.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import config

log = logging.getLogger(__name__)


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


# ── Archive (append-only ledger) ─────────────────────────────────────────────

def load_archive() -> list[dict]:
    """Read every line of archive.jsonl and return as a list of dicts."""
    path = config.ARCHIVE_PATH
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("Skipping corrupt archive line: %s", line[:80])
    return entries


def append_archive(items: list[dict]) -> None:
    """Append curated items to archive.jsonl."""
    path = config.ARCHIVE_PATH
    _ensure_dir(path)
    with open(path, "a", encoding="utf-8") as f:
        for item in items:
            item["_archived_at"] = datetime.now(timezone.utc).isoformat()
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    log.info("Appended %d items to archive", len(items))


# ── History (rolling window for memory injection) ────────────────────────────

def load_recent_headlines() -> list[str]:
    """
    Return headlines published within the MEMORY_WINDOW_DAYS window.
    Used to inject into the curator prompt so the LLM knows what is stale.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.MEMORY_WINDOW_DAYS)
    archive = load_archive()
    headlines: list[str] = []
    for entry in archive:
        ts_str = entry.get("_archived_at") or entry.get("published") or ""
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts >= cutoff:
                headline = entry.get("headline", "")
                if headline:
                    headlines.append(headline)
        except (ValueError, TypeError):
            pass
    log.info("Loaded %d recent headlines for memory window", len(headlines))
    return headlines


def save_history_snapshot(items: list[dict]) -> None:
    """
    Write a human-readable history.json with just the latest run's output
    plus the rolling window.  Useful for debugging and manual inspection.
    """
    path = config.HISTORY_PATH
    _ensure_dir(path)
    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": config.MEMORY_WINDOW_DAYS,
        "recent_headlines": load_recent_headlines(),
        "latest_run_items": items,
    }
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Saved history snapshot to %s", path)


# ── Runs index (list of all pipeline runs for the homepage) ──────────────────

RUNS_INDEX_PATH = config.DATA_DIR / "runs_index.json"


def load_runs_index() -> list[dict]:
    """Load the list of all runs. Returns [] on first run."""
    if not RUNS_INDEX_PATH.exists():
        return []
    try:
        data = json.loads(RUNS_INDEX_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read runs index: %s", exc)
    return []


def save_run_to_index(run_id: str, items: list[dict], source_count: int) -> list[dict]:
    """
    Append a run entry to runs_index.json and return the full updated index.
    Each entry stores just enough metadata for the homepage cards.
    """
    _ensure_dir(RUNS_INDEX_PATH)
    index = load_runs_index()

    top_headlines = [item.get("headline", "") for item in items[:3]]
    entry = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "item_count": len(items),
        "source_count": source_count,
        "top_headlines": top_headlines,
    }
    index.insert(0, entry)

    RUNS_INDEX_PATH.write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Added run %s to index (%d total runs)", run_id, len(index))
    return index
