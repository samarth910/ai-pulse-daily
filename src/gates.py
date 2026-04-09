"""
Independence gate — enforce triangulation before anything reaches the LLM.

An event passes if it has URLs on ≥ MIN_DOMAINS distinct registrable domains.
This is the deterministic backbone of the "two-source" rule.
"""

from __future__ import annotations

import logging

from src import config

log = logging.getLogger(__name__)


def apply_independence_gate(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Split events into (passed, rejected).

    Each event dict must have a "domains" key (set[str]).
    """
    passed: list[dict] = []
    rejected: list[dict] = []

    for event in events:
        n_domains = len(event.get("domains", set()))
        if n_domains >= config.MIN_DOMAINS:
            passed.append(event)
        else:
            rejected.append(event)

    log.info(
        "Independence gate: %d passed, %d rejected (min_domains=%d)",
        len(passed), len(rejected), config.MIN_DOMAINS,
    )
    return passed, rejected
