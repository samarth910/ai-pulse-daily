"""
Independence gate — enforce triangulation before anything reaches the LLM.

Uses a two-tier approach:
  Tier 1 (strong): events with ≥ MIN_DOMAINS distinct domains (fully corroborated)
  Tier 2 (backfill): highest-record single-domain events, if Tier 1 alone
         wouldn't give the LLM enough candidates for MIN_DIGEST_ITEMS.

The LLM is still the final quality filter — Tier 2 just ensures it has
enough material to produce a full digest.
"""

from __future__ import annotations

import logging

from src import config

log = logging.getLogger(__name__)

MIN_CANDIDATES_FOR_LLM = 30


def apply_independence_gate(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Split events into (passed, rejected).

    Guarantees at least MIN_CANDIDATES_FOR_LLM events pass (if available)
    so the LLM has enough material to curate 10-15 items.
    """
    strong: list[dict] = []
    single: list[dict] = []

    for event in events:
        n_domains = len(event.get("domains", set()))
        if n_domains >= config.MIN_DOMAINS:
            strong.append(event)
        else:
            single.append(event)

    passed = list(strong)

    if len(passed) < MIN_CANDIDATES_FOR_LLM and single:
        single.sort(key=lambda e: len(e.get("records", [])), reverse=True)
        backfill_needed = MIN_CANDIDATES_FOR_LLM - len(passed)
        backfill = single[:backfill_needed]
        passed.extend(backfill)
        single = single[backfill_needed:]
        log.info("Gate backfill: added %d single-domain events (had %d strong)",
                 len(backfill), len(strong))

    log.info(
        "Independence gate: %d passed (%d strong + %d backfill), %d rejected",
        len(passed), len(strong), len(passed) - len(strong), len(single),
    )
    return passed, single
