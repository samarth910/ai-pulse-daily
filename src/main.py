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
from src.render import render, render_homepage
from src.state import (
    append_archive,
    load_recent_headlines,
    load_runs_index,
    save_history_snapshot,
    save_run_to_index,
)

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pulse")


def _make_run_id() -> str:
    """Timestamp-based run ID safe for filesystem paths."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")


def _dry_run_items() -> list[dict]:
    """Sample items so you can test rendering without API keys."""
    return [
        {
            "headline": "Claude Opus 4.6 Ships with 1M Context and Adaptive Thinking",
            "summary": (
                "Anthropic released Claude Opus 4.6, the first frontier model to offer "
                "a one-million-token context window at standard pricing. The release also "
                "introduces an adaptive thinking mode that adjusts reasoning depth per query."
            ),
            "executive_brief": (
                "Anthropic has launched Claude Opus 4.6, marking a significant step forward "
                "in large language model capabilities. The headline feature is a one-million-token "
                "context window — roughly 750,000 words — available at the same per-token pricing as "
                "the previous 200K-context Opus model. This is the largest context window offered at "
                "standard pricing by any frontier lab.\n\n"
                "The release also introduces Adaptive Thinking, a system-level feature that lets the "
                "model dynamically adjust how deeply it reasons about a query. Simple factual lookups "
                "get fast, shallow passes; complex multi-step problems trigger extended chain-of-thought "
                "reasoning. Anthropic claims this cuts median latency by 40% on mixed workloads while "
                "maintaining accuracy on hard benchmarks.\n\n"
                "For practitioners building AI agents, the implications are immediate. Long-horizon tasks "
                "that required chunking and retrieval pipelines — entire codebases, legal discovery, "
                "multi-document research — can now fit in a single context window. This simplifies "
                "architecture significantly but raises questions about cost management at scale.\n\n"
                "The competitive landscape shifts too. OpenAI's GPT-5 offers 256K context; Google's Gemini "
                "2.0 reaches 2M but at premium pricing. Anthropic is staking out the middle ground: very "
                "large context, standard pricing, with quality that competes on the hardest benchmarks.\n\n"
                "Bottom line: if you're building agents or processing long documents, this changes your "
                "architecture calculus today. Evaluate whether your RAG pipeline is still necessary or "
                "whether direct long-context inference is now more cost-effective for your workload."
            ),
            "links": [
                {"url": "https://anthropic.com/news/claude-opus-4-6", "label": "Anthropic Blog"},
                {"url": "https://news.ycombinator.com/item?id=00000", "label": "HN Discussion"},
            ],
            "impact_score": 9,
            "category": "model_release",
        },
        {
            "headline": "Exa Launches Deep-Reasoning Search for AI Agents",
            "summary": (
                "Exa introduced a deep-reasoning search API that performs multi-step reasoning "
                "over live web data at query time. The feature is designed to power AI agents "
                "that need to cite real, verifiable sources."
            ),
            "executive_brief": (
                "Exa, the neural search startup, has shipped a deep-reasoning search mode for its "
                "API. Unlike traditional search that returns a flat list of links, deep-reasoning search "
                "performs multi-step inference over live web pages: it reads content, evaluates relevance, "
                "cross-references claims, and returns synthesized answers with source citations.\n\n"
                "The target users are developers building AI agents that need grounded, factual outputs. "
                "Current approaches (RAG over pre-indexed chunks, or naive web search + summarization) "
                "often produce hallucinated citations or miss nuance across multiple sources. Exa's approach "
                "pushes the reasoning step into the search layer itself.\n\n"
                "Early benchmarks show the system outperforming Google Custom Search + GPT-4 pipelines on "
                "multi-hop factual questions by a significant margin. Pricing is consumption-based and "
                "roughly 3-5x more expensive than standard Exa search, but the reduced need for "
                "post-processing may offset this for many use cases.\n\n"
                "The broader implication: search is becoming an active reasoning step rather than a passive "
                "retrieval step. This narrows the gap between 'search engine' and 'research assistant.' "
                "For agent builders, it means you may be able to replace complex multi-tool pipelines "
                "with a single API call. Worth evaluating if your agent does any form of web research."
            ),
            "links": [
                {"url": "https://exa.ai/blog/deep-reasoning", "label": "Exa Blog"},
                {"url": "https://reddit.com/r/MachineLearning/abc", "label": "r/MachineLearning"},
            ],
            "impact_score": 8,
            "category": "tool_launch",
        },
        {
            "headline": "Mistral Raises $1.2B Series C at $15B Valuation",
            "summary": (
                "French AI lab Mistral closed a $1.2 billion Series C round, reaching a $15 billion "
                "valuation. The round was led by General Catalyst with participation from existing "
                "investors including Andreessen Horowitz and Lightspeed."
            ),
            "executive_brief": (
                "Mistral AI, the Paris-based AI lab founded by former DeepMind and Meta researchers, "
                "has closed a $1.2 billion Series C funding round at a $15 billion post-money valuation. "
                "General Catalyst led the round, with Andreessen Horowitz, Lightspeed Venture Partners, "
                "and several European sovereign funds participating.\n\n"
                "This is the largest funding round for a European AI company and puts Mistral firmly in "
                "the same financial league as Anthropic and Cohere, though still well behind OpenAI. The "
                "company says the funds will be used to scale training infrastructure, expand enterprise "
                "sales, and continue developing open-weight models alongside their commercial API.\n\n"
                "Mistral's strategic significance goes beyond the dollar amount. The company has positioned "
                "itself as the European champion of open-weight AI — its Mixtral and Mistral Large models "
                "are widely used in the open-source community and increasingly by European enterprises "
                "concerned about data sovereignty and reliance on US providers.\n\n"
                "For the industry, this signals that the open-weight approach remains fundable at scale. "
                "Investors are betting that not all customers want to depend on closed APIs from OpenAI "
                "or Google, and that regulatory trends in the EU will favor companies with European roots "
                "and transparent model practices.\n\n"
                "Watch for: how Mistral deploys this capital relative to its open-weight commitments, and "
                "whether the EU AI Act's requirements create a structural advantage for European-headquartered "
                "labs in the enterprise market."
            ),
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
    run_id = _make_run_id()
    log.info("═══ Daily AI Pulse — run %s started at %s UTC ═══", run_id, started.strftime("%Y-%m-%d %H:%M"))

    # ── DRY RUN shortcut ─────────────────────────────────────────────────
    if config.DRY_RUN:
        log.info("DRY_RUN=1 → using sample data, skipping API calls")
        items = _dry_run_items()
        runs_index = save_run_to_index(run_id, items, source_count=0)
        render(items, run_id=run_id, source_count=0, runs_index=runs_index)
        log.info("DRY_RUN complete — check %s/index.html", config.OUTPUT_DIR)
        return

    # ── Stage 1: Ingest ──────────────────────────────────────────────────
    raw = collect_all()
    if not raw:
        log.warning("All collectors returned 0 records — producing quiet-day page")
        runs_index = save_run_to_index(run_id, [], source_count=0)
        render([], run_id=run_id, source_count=0, runs_index=runs_index)
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
        runs_index = save_run_to_index(run_id, [], source_count=len(unique))
        render([], run_id=run_id, source_count=len(unique), runs_index=runs_index)
        return

    # ── Stage 5: Load memory for anti-stale ──────────────────────────────
    recent_headlines = load_recent_headlines()

    # ── Stage 6: LLM curation ────────────────────────────────────────────
    items = curate(passed, recent_headlines)
    if not items:
        log.warning("Curator returned 0 items — producing quiet-day page")
        runs_index = save_run_to_index(run_id, [], source_count=len(unique))
        render([], run_id=run_id, source_count=len(unique), runs_index=runs_index)
        return

    # ── Stage 7: Persist state ───────────────────────────────────────────
    append_archive(items)
    save_history_snapshot(items)
    runs_index = save_run_to_index(run_id, items, source_count=len(unique))

    # ── Stage 8: Render ──────────────────────────────────────────────────
    render(items, run_id=run_id, source_count=len(unique), runs_index=runs_index)

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
            run_id = _make_run_id()
            runs_index = save_run_to_index(run_id, [], source_count=0)
            render([], run_id=run_id, source_count=0, runs_index=runs_index)
        except Exception:
            log.exception("Even the fallback render failed")
        sys.exit(1)
