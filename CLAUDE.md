# CLAUDE.md — Daily AI/Tech Pulse

Instructions for AI assistants (Claude Code, Cursor, etc.) working in this repository. Read this before making changes.

---

## What this project is

A **batch pipeline** (not a realtime app) that runs on a schedule, ingests AI/tech signals from the open web, **clusters** them into events, enforces **independent multi-source** corroboration, uses an LLM for **curation and copy**, and publishes a **static digest** (HTML + JSON). Target output: **10–15 high-signal items per run**.

---

## Engineering contracts (non-negotiable)

1. **Deterministic first** — Normalize URLs, dedupe, domain checks, and JSON schema validation are code. The LLM judges and writes; it does not replace counting or structural rules.
2. **Triangulation is defined** — Each digest item needs **≥2 URLs** on **distinct registrable domains** with **independent editorial origin** (not the same press release syndicated twice). HN/Reddit/tech press can satisfy “second source” per project policy; do not hard-require “Twitter + Reddit” for every item.
3. **Memory against stale news** — Load **last 7–14 days** of published headlines/event keys from repo state (`archive` / `history`). The model does not know what we shipped yesterday unless we inject it.
4. **Timezone** — Schedules are documented in **UTC** unless explicitly overridden; “midnight” is never ambiguous in docs.
5. **Fail visible** — On API failure, emit a **degraded but valid** artifact (e.g. “quiet day” page) and log errors; avoid silent empty commits.

---

## Architecture (one pipeline)

```
Sources → normalize/dedupe → event buckets → independence gate → curator LLM (+ memory) → validate → render → publish
```

**State** lives in-repo (e.g. `data/archive.jsonl`, `data/history.json`) or equivalent—versioned, no hidden server memory.

---

## Stack (when implemented)

- **Language:** Python 3.11+
- **Search:** Exa (semantic, date-bounded queries). Supplement with HN (Algolia API), subreddit RSS—avoid brittle `site:twitter.com`-only strategies as the primary ingest.
- **LLM:** Anthropic API — use **Sonnet-class** for bulk structuring/scoring; **Opus-class** only if needed for final polish (cap cost per run).
- **Output:** Static `index.html` + `digest.json`; optional `feed.xml`.
- **Automation:** GitHub Actions (cron + `workflow_dispatch`), or equivalent.

---

## Directory layout (target)

```
.
├── CLAUDE.md
├── README.md              # human onboarding (user-facing)
├── requirements.txt
├── .env.example
├── src/
│   ├── ingest.py          # collectors → raw records
│   ├── normalize.py       # URL canonicalization, dedupe
│   ├── cluster.py         # event fingerprints / merges
│   ├── gates.py           # domain / independence checks
│   ├── curate.py          # LLM + memory injection
│   ├── render.py          # HTML / JSON
│   └── main.py            # orchestration
├── data/                  # generated state (committed or gitignored per policy)
├── public/ or docs/       # published static site
└── .github/workflows/     # scheduled job
```

Adjust names as you implement; keep **one obvious entrypoint** (`main.py`).

---

## Conventions

- **Structured output** from the LLM: JSON matching a schema; validate in code after every call.
- **No secrets in repo** — use CI secrets / local `.env` (gitignored).
- **Idempotent runs** — same inputs + same state should not duplicate published events without an explicit “update” rule.
- **Influencer hooks:** YouTube via **official API + video IDs** in state. Instagram/Reels automation is **non-blocking for MVP** (manual seed or v2).

---

## What not to do

- Do not dump 100+ raw URLs into a **single** LLM call for dedupe + triangulation + ranking.
- Do not use URL path segments alone as stable IDs (`split('/')[-1]`); use normalized URL + platform IDs (e.g. YouTube video id).
- Do not treat “two links” as satisfied by **tweet quoting one article** unless product policy explicitly allows that tier—call it out in copy if you do.

---

## When editing

- Prefer **small, testable modules** over one monolithic script as soon as the second integration lands.
- Any change to **triangulation rules** or **memory window** must update **this file** and the **README** so humans and agents stay aligned.

---

## References

- Anthropic: structured outputs, model IDs — see current [Claude docs](https://docs.anthropic.com).
- Exa: use current Search API; check [Exa docs](https://docs.exa.ai) for deprecations.
