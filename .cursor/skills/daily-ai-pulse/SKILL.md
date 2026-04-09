---
name: daily-ai-pulse
description: >-
  Build and maintain the Daily AI/Tech Pulse batch pipeline. Use when editing
  ingest, normalize, cluster, gates, curate, render, state, or main modules,
  or when adding new collectors, changing triangulation rules, or modifying the
  HTML template.
---

# Daily AI/Tech Pulse

## Pipeline contract

```
Sources → normalize/dedupe → event buckets → independence gate → curator LLM (+ memory) → validate → render → publish
```

Every module maps to one stage. Do not merge stages into a single file.

## Module map

| File | Stage | Pure? | Key rule |
|------|-------|-------|----------|
| `src/config.py` | cross-cutting | yes | All tunables from env vars; no hardcoded secrets |
| `src/normalize.py` | normalize/dedupe | yes | Canonical URLs via `tldextract`; strip tracking params |
| `src/ingest.py` | sources | no (I/O) | Each collector returns `list[dict]` with same schema |
| `src/cluster.py` | event buckets | yes | Group by title similarity + shared entities |
| `src/gates.py` | independence gate | yes | ≥2 distinct registrable domains or reject |
| `src/state.py` | memory | no (I/O) | Load/save `data/archive.jsonl`; 14-day window |
| `src/curate.py` | curator LLM | no (API) | Anthropic structured output; inject memory; validate JSON |
| `src/render.py` | render | yes | Jinja2 HTML + `digest.json`; degraded "quiet day" page |
| `src/main.py` | orchestrator | no | Calls stages in order; catches failures; always produces output |

## Key conventions

- LLM does **judgment and copy**; code does **counting, validation, domain checks**.
- Triangulation = ≥2 URLs on distinct registrable domains with independent editorial origin.
- Anti-stale = inject last 14 days of published headlines into the curator prompt.
- On any API failure, emit a degraded page — never a silent empty commit.

## When editing

- Changes to triangulation rules or memory window → update `CLAUDE.md` and `README.md`.
- New collector → add to `ingest.py`, return same `RawRecord` schema.
- New env var → add to `src/config.py` defaults and `.env.example`.
