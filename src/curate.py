"""
LLM curation — the "taste" layer.

Takes pre-gated event clusters + memory (recent headlines) and asks the model
(via OpenRouter) to score, rank, and write executive-brief-quality copy for
the top items.  Enforces structured JSON output and validates in code.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from src import config

log = logging.getLogger(__name__)

# ── Output schema ────────────────────────────────────────────────────────────

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "Punchy headline, max 15 words",
        },
        "summary": {
            "type": "string",
            "description": "2-3 sentence crisp explanation of what happened (~50 words)",
        },
        "executive_brief": {
            "type": "string",
            "description": (
                "3-5 paragraph fully-synthesized executive brief (~200-300 words). "
                "Covers the 5Ws and 2Hs: What happened, Who is involved, Why it matters, "
                "Where this fits in the landscape, When it happened/timeline, "
                "How it impacts practitioners and the industry, How significant it is. "
                "Written so the reader never needs to search further."
            ),
        },
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "label": {"type": "string", "description": "e.g. 'Official Blog', 'HN Discussion'"},
                },
                "required": ["url", "label"],
            },
        },
        "impact_score": {"type": "number", "description": "1-10, 10 = paradigm shift"},
        "category": {
            "type": "string",
            "enum": [
                "model_release", "tool_launch", "research", "funding",
                "acquisition", "open_source", "policy", "other",
            ],
        },
    },
    "required": ["headline", "summary", "executive_brief", "links", "impact_score", "category"],
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
You are the curator for "Daily AI/Tech Pulse," a brutally selective daily digest \
aimed at busy tech executives and senior engineers.

ROLE: Read the candidate events below, score each, and return ONLY the top \
{max_items} as structured JSON. Every item must be a self-contained executive \
brief — the reader should NEVER need to click a link or search further to \
understand the full story.

SCORING RUBRIC (each 1-10):
- Novelty: Is this genuinely new, not a rehash of last week?
- Impact: Does it change how people build or use AI/tech?
- Traction: Evidence of real-world discussion across multiple sources?

FOR EACH ITEM YOU MUST PRODUCE:

1. **headline** — Punchy, max 15 words. An engineer would click this.

2. **summary** — 2-3 sentences (~50 words) explaining what this news IS. \
Think of it as the subheadline a reader sees before deciding to read more.

3. **executive_brief** — This is the core deliverable. Write 3-5 paragraphs \
(~{max_brief_words} words) that fully synthesize the story. Cover:
   - WHAT happened, stated plainly with specific facts and numbers
   - WHO is involved — companies, key people, organizations
   - WHY it matters for the AI/tech industry and broader ecosystem
   - HOW it impacts practitioners, builders, startups, and end users
   - WHAT QUESTIONS it raises — implications, risks, second-order effects
   - SO WHAT — the bottom line: what should the reader do or watch for?
   Write in clear, authoritative prose. No filler, no fluff. The reader is \
smart but time-constrained. After reading your brief they should be able to \
discuss this topic confidently in any meeting.

HARD RULES:
1. Each item MUST reference at least two links on distinct domains.
2. STALE CHECK — these headlines were already published in the last \
{window} days. If a candidate is substantially the same event, REJECT it:

{memory_block}

3. Do NOT include minor library patches, vague "AI will change everything" \
op-eds, or incremental benchmark improvements nobody will remember next week.
4. Cap output at {max_items} items, ranked by impact_score descending.
5. Write headlines that a busy engineer would click on. No clickbait.

Return ONLY valid JSON matching the schema. No markdown fences, no commentary.\
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
    Send gated events + memory to the LLM via OpenRouter and return validated
    digest items.

    Returns an empty list (never raises) so the pipeline can fall through to
    the degraded-output path.
    """
    if not config.OPENROUTER_API_KEY:
        log.warning("OPENROUTER_API_KEY not set — skipping curation")
        return []

    if not events:
        log.info("No events to curate")
        return []

    memory_block = "\n".join(f"  - {h}" for h in recent_headlines) if recent_headlines else "  (none — first run)"

    system = _SYSTEM.format(
        max_items=config.MAX_DIGEST_ITEMS,
        window=config.MEMORY_WINDOW_DAYS,
        memory_block=memory_block,
        max_brief_words=config.MAX_BRIEF_WORDS,
    )

    user_msg = (
        "Here are the candidate events that passed the independence gate.\n"
        "Pick the best, score them, and write the digest.\n\n"
        + _format_events_for_prompt(events)
    )

    try:
        client = OpenAI(
            base_url=config.OPENROUTER_BASE_URL,
            api_key=config.OPENROUTER_API_KEY,
        )
        response = client.chat.completions.create(
            model=config.CURATOR_MODEL,
            max_tokens=config.MAX_CURATOR_TOKENS,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            extra_headers={
                "HTTP-Referer": "https://ai-pulse-daily.run.app",
                "X-Title": "AI Pulse Daily",
            },
        )
    except Exception as exc:
        log.error("OpenRouter API call failed: %s", exc)
        return []

    raw_text = response.choices[0].message.content if response.choices else ""
    return _parse_and_validate(raw_text or "")


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
        item.setdefault("summary", "")
        item.setdefault("executive_brief", "")
        validated.append(item)

    validated.sort(key=lambda x: x.get("impact_score", 0), reverse=True)
    validated = validated[: config.MAX_DIGEST_ITEMS]
    log.info("Curator returned %d validated items", len(validated))
    return validated
