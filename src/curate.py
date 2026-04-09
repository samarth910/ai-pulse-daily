"""
LLM curation — the "taste" layer.

Takes pre-gated event clusters + memory (recent headlines) and asks the model
to score, rank, and write copy for the top items.  Enforces structured JSON
output and validates the response in code.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from src import config

log = logging.getLogger(__name__)

# ── Output schema ────────────────────────────────────────────────────────────

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "headline":       {"type": "string", "description": "Punchy headline, max 15 words"},
        "why_it_matters": {"type": "string", "description": "One sentence on impact, max 30 words"},
        "links":          {"type": "array", "items": {"type": "object", "properties": {
            "url":   {"type": "string"},
            "label": {"type": "string", "description": "e.g. 'Official Blog', 'HN Discussion'"},
        }, "required": ["url", "label"]}},
        "impact_score":   {"type": "number", "description": "1-10, 10 = paradigm shift"},
        "category":       {"type": "string", "enum": [
            "model_release", "tool_launch", "research", "funding",
            "acquisition", "open_source", "policy", "other",
        ]},
    },
    "required": ["headline", "why_it_matters", "links", "impact_score", "category"],
}

DIGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": ITEM_SCHEMA},
    },
    "required": ["items"],
}


# ── System prompt ────────────────────────────────────────────────────────────

_SYSTEM = """\
You are the curator for "Daily AI/Tech Pulse," a brutally selective daily digest.

ROLE: Read the candidate events below, score each, and return ONLY the top \
{max_items} as structured JSON.

SCORING RUBRIC (each 1-10):
- Novelty: Is this genuinely new, not a rehash of last week?
- Impact: Does it change how people build or use AI/tech?
- Traction: Evidence of real-world discussion across multiple sources?

HARD RULES:
1. Each item MUST reference at least two links on distinct domains.
2. STALE CHECK — these headlines were already published in the last \
{window} days.  If a candidate is substantially the same event, REJECT it:

{memory_block}

3. Do NOT include minor library patches, vague "AI will change everything" \
op-eds, or incremental benchmark improvements nobody will remember next week.
4. Cap output at {max_items} items, ranked by impact_score descending.
5. Write headlines that a busy engineer would click on.  No clickbait.

Return ONLY valid JSON matching the schema.  No markdown, no commentary.\
"""


# ── Build the user message from events ───────────────────────────────────────

def _format_events_for_prompt(events: list[dict]) -> str:
    lines: list[str] = []
    for i, ev in enumerate(events, 1):
        domains = ", ".join(sorted(ev.get("domains", set())))
        sources = ", ".join(sorted(ev.get("sources", set())))
        urls = [r.get("url", "") for r in ev.get("records", [])][:5]
        snippet = (ev.get("records", [{}])[0].get("snippet", "") or "")[:200]
        lines.append(
            f"### Event {i}\n"
            f"Title: {ev.get('event_key', '')}\n"
            f"Domains: {domains}\n"
            f"Sources: {sources}\n"
            f"Sample URLs:\n" + "\n".join(f"  - {u}" for u in urls) + "\n"
            f"Snippet: {snippet}\n"
        )
    return "\n".join(lines)


# ── Call the model ───────────────────────────────────────────────────────────

def curate(events: list[dict], recent_headlines: list[str]) -> list[dict]:
    """
    Send gated events + memory to Anthropic and return validated digest items.

    Returns an empty list (never raises) so the pipeline can fall through to
    the degraded-output path.
    """
    if not config.ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY not set — skipping curation")
        return []

    if not events:
        log.info("No events to curate")
        return []

    memory_block = "\n".join(f"  - {h}" for h in recent_headlines) if recent_headlines else "  (none — first run)"

    system = _SYSTEM.format(
        max_items=config.MAX_DIGEST_ITEMS,
        window=config.MEMORY_WINDOW_DAYS,
        memory_block=memory_block,
    )

    user_msg = (
        "Here are the candidate events that passed the independence gate.\n"
        "Pick the best, score them, and write the digest.\n\n"
        + _format_events_for_prompt(events)
    )

    try:
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=config.CURATOR_MODEL,
            max_tokens=config.MAX_CURATOR_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:
        log.error("Anthropic API call failed: %s", exc)
        return []

    raw_text = response.content[0].text if response.content else ""
    return _parse_and_validate(raw_text)


def _parse_and_validate(raw: str) -> list[dict]:
    """Parse the model's JSON response and validate each item."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Curator returned invalid JSON: %s — %s", exc, raw[:200])
        return []

    items: list[Any]
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and "items" in data:
        items = data["items"]
    else:
        log.error("Unexpected JSON shape from curator: %s", type(data))
        return []

    validated: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get("headline") or not item.get("links"):
            continue
        if not isinstance(item.get("links"), list) or len(item["links"]) < 1:
            continue
        item.setdefault("impact_score", 5)
        item.setdefault("category", "other")
        item.setdefault("why_it_matters", "")
        validated.append(item)

    validated.sort(key=lambda x: x.get("impact_score", 0), reverse=True)
    validated = validated[: config.MAX_DIGEST_ITEMS]
    log.info("Curator returned %d validated items", len(validated))
    return validated
