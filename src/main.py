"""
Orchestrator — the single entrypoint for the Daily AI/Tech Pulse pipeline.

Pipeline:
    ingest → normalize/dedupe → cluster → independence gate
    → curate (LLM + memory) → validate → render → persist state

Contract: ALWAYS produces a valid HTML page, even on total API failure
(the "quiet day" degraded output).
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from src import config
from src.cluster import cluster_records
from src.curate import curate
from src.gates import apply_independence_gate
from src.ingest import collect_all
from src.normalize import dedupe_records
from src.render import render
from src.state import append_archive, load_recent_headlines, save_history_snapshot

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pulse")


def _dry_run_items() -> list[dict]:
    """Sample items so you can test rendering without API keys."""
    return [
        {
            "headline": "Claude Opus 4.6 Ships with 1M Context and Adaptive Thinking",
            "why_it_matters": "First frontier model to offer million-token context at standard pricing — changes how long-horizon agent tasks are built.",
            "links": [
                {"url": "https://anthropic.com/news/claude-opus-4-6", "label": "Anthropic Blog"},
                {"url": "https://news.ycombinator.com/item?id=00000", "label": "HN Discussion"},
            ],
            "impact_score": 9,
            "category": "model_release",
        },
        {
            "headline": "Exa Launches Deep-Reasoning Search for AI Agents",
            "why_it_matters": "Multi-step reasoning over live web data at query time — unlocks research agents that actually cite sources.",
            "links": [
                {"url": "https://exa.ai/blog/deep-reasoning", "label": "Exa Blog"},
                {"url": "https://reddit.com/r/MachineLearning/abc", "label": "r/MachineLearning"},
            ],
            "impact_score": 8,
            "category": "tool_launch",
        },
        {
            "headline": "Mistral Raises $1.2B Series C at $15B Valuation",
            "why_it_matters": "Largest European AI funding round — signals open-weight models remain a credible counterweight to US frontier labs.",
            "links": [
                {"url": "https://techcrunch.com/2026/04/mistral-series-c", "label": "TechCrunch"},
                {"url": "https://twitter.com/MistralAI/status/00000", "label": "X/Twitter"},
            ],
            "impact_score": 7,
            "category": "funding",
        },
    ]


def run() -> None:
    """Execute the full pipeline."""
    started = datetime.now(timezone.utc)
    log.info("═══ Daily AI Pulse — run started at %s UTC ═══", started.strftime("%Y-%m-%d %H:%M"))

    # ── DRY RUN shortcut ─────────────────────────────────────────────────
    if config.DRY_RUN:
        log.info("DRY_RUN=1 → using sample data, skipping API calls")
        items = _dry_run_items()
        render(items, source_count=0)
        log.info("DRY_RUN complete — check %s/index.html", config.OUTPUT_DIR)
        return

    # ── Stage 1: Ingest ──────────────────────────────────────────────────
    raw = collect_all()
    if not raw:
        log.warning("All collectors returned 0 records — producing quiet-day page")
        render([], source_count=0)
        return

    # ── Stage 2: Normalize & dedupe ──────────────────────────────────────
    unique = dedupe_records(raw)
    log.info("After dedupe: %d unique records (from %d raw)", len(unique), len(raw))

    # ── Stage 3: Cluster into candidate events ───────────────────────────
    events = cluster_records(unique)
    log.info("Clustered into %d candidate events", len(events))

    # ── Stage 4: Independence gate ───────────────────────────────────────
    passed, rejected = apply_independence_gate(events)
    if not passed:
        log.warning("No events passed the independence gate — producing quiet-day page")
        render([], source_count=len(unique))
        return

    # ── Stage 5: Load memory for anti-stale ──────────────────────────────
    recent_headlines = load_recent_headlines()

    # ── Stage 6: LLM curation ────────────────────────────────────────────
    items = curate(passed, recent_headlines)
    if not items:
        log.warning("Curator returned 0 items — producing quiet-day page")
        render([], source_count=len(unique))
        return

    # ── Stage 7: Render ──────────────────────────────────────────────────
    render(items, source_count=len(unique))

    # ── Stage 8: Persist state ───────────────────────────────────────────
    append_archive(items)
    save_history_snapshot(items)

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    log.info("═══ Pipeline complete — %d items in %.1fs ═══", len(items), elapsed)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Interrupted")
        sys.exit(130)
    except Exception:
        log.exception("Fatal pipeline error — producing quiet-day page as fallback")
        try:
            render([], source_count=0)
        except Exception:
            log.exception("Even the fallback render failed")
        sys.exit(1)
