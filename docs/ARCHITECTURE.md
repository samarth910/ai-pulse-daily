# Architecture — Daily AI/Tech Pulse

A comprehensive technical document covering what was built, why every decision
was made, how each component works, and the concepts you can learn from it.

**Audience:** An engineer (or learner) who wants to understand the system
end-to-end, not just run it.

---

## Table of Contents

1. [Problem Statement & Product Intent](#1-problem-statement--product-intent)
2. [Architecture Overview](#2-architecture-overview)
3. [Data Model](#3-data-model)
4. [Ingestion Layer](#4-ingestion-layer)
5. [Normalization & Deduplication](#5-normalization--deduplication)
6. [Clustering Engine](#6-clustering-engine)
7. [Independence Gate (Triangulation)](#7-independence-gate-triangulation)
8. [State & Memory System](#8-state--memory-system)
9. [LLM Curation Layer](#9-llm-curation-layer)
10. [Rendering & Output](#10-rendering--output)
11. [Orchestration & Failure Modes](#11-orchestration--failure-modes)
12. [Deployment & Operations](#12-deployment--operations)
13. [Cost Model & Scaling](#13-cost-model--scaling)
14. [Design Decisions Log](#14-design-decisions-log)

---

## 1. Problem Statement & Product Intent

### The problem

The AI/tech ecosystem generates hundreds of announcements per day — model
releases, tool launches, funding rounds, research papers, open-source drops,
policy moves. No single person can track all of it. Most "AI newsletters"
solve this by dumping 50+ links with minimal curation, which just moves the
overload from Twitter to your inbox.

### What we want instead

A **daily digest of 10–15 items** where every single item passes a
**triangulation test** (corroborated by at least two independent sources) and a
**freshness test** (not something we already published this week). The output
should feel like a **private intelligence briefing**, not a link dump.

### Why "triangulation" matters

The insight: **important news creates ripples across multiple, independent
platforms**. If OpenAI ships a new model, it appears on their blog, on Hacker
News, on Reddit, and in tech press — simultaneously and independently. A
random person's Medium post about "AI trends" does not get that multi-source
traction. By requiring ≥2 distinct domains with independent editorial origin,
we mechanically filter out ~80% of noise, hype, and SEO content.

### Why "memory" matters

Without memory, the system will happily resurface "GPT-5 launched" every day
for a month, because new blog posts keep appearing about it. We solve this by
injecting the last 14 days of our own published headlines into the LLM prompt,
and instructing it to reject anything substantially similar.

---

## 2. Architecture Overview

```
┌──────────────┐
│  Collectors   │  Exa (semantic search) + HN (Algolia) + Reddit (RSS)
└──────┬───────┘
       │ list[RawRecord]
       ▼
┌──────────────┐
│  Normalize    │  Canonical URLs, strip tracking params, extract domain
│  + Dedupe     │  Remove exact-URL duplicates (first occurrence wins)
└──────┬───────┘
       │ list[RawRecord] (unique)
       ▼
┌──────────────┐
│   Cluster     │  Token-overlap fingerprinting → Union-Find → event groups
└──────┬───────┘
       │ list[Event]
       ▼
┌──────────────┐
│    Gate       │  ≥2 distinct registrable domains? → pass / reject
└──────┬───────┘
       │ list[Event] (gated)
       ▼
┌──────────────┐
│   Curate      │  Anthropic API + memory injection + structured JSON output
│   (LLM)       │  Score, rank, write headlines & summaries
└──────┬───────┘
       │ list[DigestItem]
       ▼
┌──────────────┐
│   Validate    │  JSON schema check in code (not LLM)
└──────┬───────┘
       │ list[DigestItem] (validated)
       ▼
┌──────────────┐
│   Render      │  Jinja2 → index.html (Tailwind) + digest.json
└──────┬───────┘
       │ files on disk
       ▼
┌──────────────┐
│   Persist     │  Append to archive.jsonl, update history.json
└──────────────┘
```

**Key principle:** each box is one Python module. Data flows forward; no
module reaches back into a previous stage. This makes testing trivial — you
can unit-test `normalize.py` or `gates.py` with zero API keys.

---

## 3. Data Model

### RawRecord (output of collectors, input to normalize)

```python
{
    "url":       str,        # original URL as found
    "title":     str,
    "snippet":   str,        # first ~500 chars of content
    "published": str | None, # ISO-8601 datetime or None
    "source":    str,        # "exa", "hn", "reddit"
}
```

### RawRecord after normalization (added fields)

```python
{
    ...RawRecord,
    "canonical_url": str,    # cleaned, tracking-stripped URL
    "domain":        str,    # registrable domain (e.g. "openai.com")
}
```

### Event (output of clustering)

```python
{
    "event_key": str,        # representative title (longest in cluster)
    "records":   list[dict], # all RawRecords in this cluster
    "domains":   set[str],   # distinct registrable domains
    "sources":   set[str],   # collector names
}
```

### DigestItem (output of curation)

```python
{
    "headline":       str,
    "why_it_matters": str,
    "links":          list[{"url": str, "label": str}],
    "impact_score":   int,   # 1-10
    "category":       str,   # enum: model_release, tool_launch, etc.
}
```

### Why explicit schemas matter

The LLM returns prose-flavoured JSON. Without **validation in code** after
every call, a single malformed response breaks the entire pipeline. We parse
the JSON, check required fields, default missing optional fields, and only
pass validated items to the renderer. This is the "deterministic first"
contract: the LLM writes; code verifies.

---

## 4. Ingestion Layer

**File:** `src/ingest.py`

### Design: multiple collectors, same interface

Each collector is a function that returns `list[dict]` with the RawRecord
shape. They are called in parallel (conceptually — sequential in v1 for
simplicity) and their results are merged.

### Exa (semantic web search)

- **What it is:** An LLM-powered search engine that finds URLs by meaning,
  not just keywords. You give it a natural-language query like "major new AI
  model released today" and it returns relevant web pages.
- **Why we use it:** It finds primary sources (official blogs, papers) and
  discussion threads (Reddit, HN, X) that keyword search misses.
- **How we use it:** We run 5 semantic queries with different angles
  (breakthroughs, tools, funding, research, notable launches) with a 36-hour
  date window. `use_autoprompt=True` lets Exa rephrase the query for better
  results.
- **Failure mode:** If the API is down or the key is missing, the collector
  returns `[]` and logs a warning. The pipeline continues with other sources.

### Hacker News (Algolia API)

- **What it is:** HN's official search API, powered by Algolia. Free, no key,
  no rate limit for reasonable use.
- **Why we use it:** HN is the highest-signal developer discussion forum. If
  something gets 200+ points on HN, it's real traction.
- **How we use it:** `search_by_date` with tags=story, filtered to stories
  created after the cutoff timestamp.

### Reddit RSS

- **What it is:** Reddit exposes `.rss` feeds for any subreddit's sort views.
  No API key, no OAuth, just HTTP GET.
- **Why we use it:** Subreddits like r/MachineLearning, r/LocalLLaMA, and
  r/artificial are high-signal discussion communities.
- **How we use it:** We fetch the top-of-day RSS feed and parse it with
  `feedparser`.

### Why not X/Twitter?

The X API is expensive ($100+/month for basic access) and rate-limited. For
v1, we get Twitter-linked content indirectly through Exa (which indexes
tweets) and through HN/Reddit posts that link to tweets.

---

## 5. Normalization & Deduplication

**File:** `src/normalize.py`

### URL canonicalization

URLs are messy. The same page can appear as:

```
https://www.openai.com/blog/gpt5?utm_source=twitter&ref=hn
https://openai.com/blog/gpt5/
https://OPENAI.COM/blog/gpt5#comments
```

Our `canonical_url()` function:
1. Lowercases the scheme and host.
2. Strips `www.` prefix.
3. Removes tracking parameters (`utm_*`, `ref`, `fbclid`, etc.).
4. Drops the URL fragment (`#comments`).
5. Strips trailing slashes on paths.

This means all three URLs above become: `https://openai.com/blog/gpt5`

### Registrable domain extraction

We use `tldextract` (which maintains a public suffix list) to extract the
**registrable domain** — the domain you'd register with a registrar:

- `blog.openai.com` → `openai.com`
- `old.reddit.com` → `reddit.com`
- `news.ycombinator.com` → `ycombinator.com`

This is critical for the independence gate: `blog.openai.com` and
`api.openai.com` are the **same** editorial origin; `openai.com` and
`techcrunch.com` are **different**.

### Deduplication

Simple set-based dedupe by canonical URL. First occurrence wins; order is
preserved. This runs **before** clustering, so the clusterer never sees exact
duplicates.

---

## 6. Clustering Engine

**File:** `src/cluster.py`

### The problem

After deduplication, we might have 80 unique URLs. Many of them discuss the
**same event** (e.g., 5 articles + 3 Reddit posts about one model release).
We need to group them so the independence gate and the LLM see **events**, not
individual links.

### The algorithm: token-overlap + Union-Find

1. **Tokenize** each title: lowercase, extract alphanumeric tokens, remove
   stop words and short tokens.
2. **Pairwise Jaccard similarity**: for each pair of records, compute
   `|A ∩ B| / |A ∪ B|`. If similarity ≥ 0.35 (the merge threshold), they
   belong to the same event.
3. **Union-Find (disjoint set)** with path compression: efficiently merge
   records into clusters without O(n²) memory.

### Why this approach (and not embeddings)?

For 50–150 records per day, Jaccard on title tokens is:
- **Free** (no API calls, no embedding model).
- **Deterministic** (same input → same clusters).
- **Fast** (~10ms for 100 records).

Embeddings (e.g., Voyage, OpenAI text-embedding-3) would give better semantic
matching but add cost, latency, and a dependency. We add them in v1.1 **only
if** title-overlap clustering produces poor groupings in practice.

### What Union-Find is (concept)

Union-Find is a data structure that efficiently tracks which elements belong
to the same group. It supports two operations:
- `find(x)`: which group does x belong to?
- `union(x, y)`: merge the groups of x and y.

With **path compression** (make every node point directly to its root), both
operations run in nearly O(1) amortized time. We use it here to avoid
materializing an adjacency matrix for pairwise similarities.

---

## 7. Independence Gate (Triangulation)

**File:** `src/gates.py`

### What it does

For each event cluster, count the **distinct registrable domains** across all
URLs in the cluster. If the count is ≥ `MIN_DOMAINS` (default: 2), the event
passes. Otherwise, it's rejected.

### Why this is a separate module (not inside the LLM)

This is the "deterministic first" principle. Counting domains is arithmetic —
code does it perfectly every time. Asking an LLM to count domains in a 100-
link list is unreliable and wasteful.

### What "independent editorial origin" means

Two articles on `medium.com` by different authors are on the **same** domain.
They pass the domain check but arguably lack true independence (Medium hosts
anyone). For v1, we accept domain-level checks and rely on the LLM's judgment
for subtler independence assessment. A v2 enhancement would add a
`source_tier` system (official blogs > tier-1 press > forums > user-generated
content platforms).

### Rejected events are not lost

The gate returns both `(passed, rejected)` tuples. Rejected events are logged
for debugging. If every event gets rejected (slow news day), the pipeline
produces the "quiet day" degraded page instead of crashing.

---

## 8. State & Memory System

**File:** `src/state.py`

### archive.jsonl — the append-only ledger

Every item we ever publish gets appended as one JSON line to `data/archive.jsonl`.
The file grows indefinitely (at 15 items/day × ~500 bytes/item, that's
~2.7 MB/year — trivially small).

JSONL (JSON Lines) is chosen over a single JSON array because:
- **Append-only**: we never rewrite the file, only append.
- **Corruption-resistant**: a truncated last line doesn't invalidate earlier data.
- **Streamable**: we can process it line-by-line without loading everything.

### history.json — the debugging snapshot

After each run, we write a `history.json` with the current rolling window
of recent headlines plus the latest run's output. This is purely for **human
inspection** — if you want to see what the memory looks like, open this file.

### The 14-day rolling window

`load_recent_headlines()` reads the archive, filters to entries whose
`_archived_at` timestamp is within the last `MEMORY_WINDOW_DAYS` (default: 14),
and returns just the headline strings. These are injected into the LLM
system prompt as a bulleted list.

### First-run bootstrapping

If `archive.jsonl` doesn't exist (first run), the function returns an empty
list, and the LLM prompt gets `(none — first run)` as the memory block. No
crash, no special setup needed.

---

## 9. LLM Curation Layer

**File:** `src/curate.py`

### Why an LLM at all?

Code can cluster, count domains, and filter by date. But code cannot judge:
- Is this a **paradigm shift** or a **minor benchmark improvement**?
- Would a **busy engineer** find this worth reading?
- Is this headline **punchy** or **boring**?

The LLM's job is narrow and well-defined: given pre-filtered, pre-gated
events with memory context, **score them, rank them, and write copy**.

### The system prompt (design philosophy)

The prompt has three layers:
1. **Role and persona**: "brutally selective curator" — this sets the tone.
2. **Scoring rubric**: Novelty (1-10), Impact (1-10), Traction (1-10) —
   explicit, measurable, tunable.
3. **Hard rules**: minimum 2 links per item, stale check against memory,
   no minor patches or vague op-eds, cap at MAX_DIGEST_ITEMS.

### Structured JSON output

The model is instructed to return **only** a JSON object matching our schema.
We parse it in code (`json.loads`), handle markdown code fences the model
might wrap it in, validate required fields, default missing optional fields,
sort by impact_score, and cap at MAX_DIGEST_ITEMS.

### Why we validate in code, not trust the model

Even the best models occasionally:
- Return a field with wrong type (string instead of number).
- Omit a required field.
- Add extra commentary outside the JSON.
- Return an empty array.

Our `_parse_and_validate()` function handles all of these gracefully. Items
that fail validation are silently dropped; the pipeline continues with
whatever valid items remain.

### Model selection

We default to **Claude Sonnet 4.6** (`claude-sonnet-4-6-20250217`) because:
- It's **cheaper** than Opus ($3/$15 per million tokens vs. $5/$25).
- It's **fast** (~2-5 seconds for our workload).
- Its **judgment quality** is excellent for curation tasks.
- Opus can be swapped in via `CURATOR_MODEL` env var if Sonnet's taste
  disappoints — but measure before you upgrade.

---

## 10. Rendering & Output

**File:** `src/render.py`

### HTML generation

We use **Jinja2** templates (the same engine behind Flask/Django templates)
to generate a single `index.html`. The template is embedded in the Python
file as a string constant — no separate template files to manage in v1.

### Design choices

- **Tailwind CSS via CDN**: zero build step, no node_modules, dark mode by
  default. For a daily-generated static page, CDN loading is fine.
- **Dark mode**: easier on the eyes for a daily morning read.
- **Impact dots**: visual 1-10 score using filled/unfilled dots.
- **Category badges**: color-coded chips (purple for models, blue for tools,
  green for research, etc.) for scanability.
- **Card hover effect**: subtle lift + shadow on hover for interactivity.

### The "quiet day" page

When the pipeline has zero items (all collectors failed, nothing passed the
gate, or the LLM returned nothing), we render a special page with a moon
emoji, "Quiet day" heading, and a brief explanation. **The pipeline never
produces an empty or broken page.**

### digest.json

A machine-readable JSON file with the same data. This enables:
- Building an RSS feed later.
- Consuming the digest from another tool.
- Archiving structured data alongside the HTML.

---

## 11. Orchestration & Failure Modes

**File:** `src/main.py`

### The pipeline as code

`main.py` calls each stage in order. At every stage boundary, it checks for
empty results and falls through to the degraded page if needed.

### DRY_RUN mode

Set `DRY_RUN=1` to skip all API calls and render a page with sample data.
This lets you:
- Test the HTML template without any keys.
- Verify the deployment pipeline end-to-end.
- Demo the product before it's wired to live data.

### Failure cascade

```
All collectors return []      → quiet-day page
Nothing passes the gate       → quiet-day page
LLM returns invalid JSON      → quiet-day page
LLM returns 0 valid items     → quiet-day page
Uncaught exception in run()   → except block renders quiet-day page
Even the fallback fails       → log + exit(1)
```

The only scenario that produces **no output at all** is if file I/O itself
fails (disk full, permissions). Every API failure is caught and degrades
gracefully.

---

## 12. Deployment & Operations

### GitHub Actions (primary)

**File:** `.github/workflows/daily.yml`

The workflow:
1. Triggers at **00:05 UTC** daily (cron), or manually (workflow_dispatch).
2. Checks out the repo.
3. Installs Python 3.11 and pip dependencies.
4. Runs `python -m src.main` with secrets injected as env vars.
5. Commits changed files in `public/` and `data/` and pushes.

**Why 00:05, not 00:00?** GitHub Actions cron has a ±10 minute jitter. By
targeting 00:05 we avoid midnight edge cases where `date.today()` might still
return yesterday's date during the jitter window.

**Why commit from CI?** The state files (`archive.jsonl`, `history.json`) are
versioned in-repo. This gives us a full audit trail of every run — you can
`git log data/archive.jsonl` to see exactly when each item was published.

### Railway (secondary — live server)

**Files:** `railway.json`, `railway.toml`, `Procfile`, `server.py`

Railway deploys from GitHub and runs `server.py` — a minimal
`http.server`-based static file server that:
- Serves `public/` on the `PORT` environment variable.
- Exposes `POST /run` to trigger a pipeline run on demand.
- Runs an initial pipeline on first boot if no `index.html` exists.

**Why a server and not just static hosting?** Railway doesn't have native
static hosting. The server is 60 lines of stdlib Python — no framework, no
dependencies beyond what's already installed.

### Railway Cron (scheduled runs)

Railway supports cron services. Create a second service in your Railway
project with the command `python -m src.main` and schedule `5 0 * * *`.

---

## 13. Cost Model & Scaling

### Per-run costs (estimated)

| Component | Free tier | Typical usage | Cost/run |
|-----------|-----------|---------------|----------|
| GitHub Actions | 2000 min/month | ~2-3 min/run | $0.00 |
| Exa API | 1000 searches/month | 5 queries/run = 150/month | $0.00 (free tier) |
| Anthropic API | — | ~3000 input + ~2000 output tokens | ~$0.04 |
| Reddit RSS | unlimited | 3 feeds | $0.00 |
| HN Algolia | unlimited | 1 query | $0.00 |
| **Total** | | | **~$0.04/run = ~$1.20/month** |

### What costs could spike

- **Switching to Opus:** $5/$25 per million tokens instead of $3/$15. For our
  workload, Opus would cost ~$0.08/run instead of ~$0.04.
- **Adding embeddings:** Each embedding call (e.g., OpenAI text-embedding-3-small)
  costs ~$0.00002/record. At 100 records/day = $0.002/day. Negligible.
- **Increasing Exa queries:** Each query costs one search credit. At 5/day,
  we use 150/month of the 1000 free tier. Scaling to 20/day would require
  the paid plan (~$100/month).

### Scaling path

The architecture handles **10x more sources** without structural changes:
add a new collector function to `ingest.py`, return the same RawRecord shape.
The pipeline handles 500+ records per run — clustering and gating are O(n²)
on titles but n < 500 so it's sub-second.

---

## 14. Design Decisions Log

### Why Python (not TypeScript, Go, Rust)?

- The three APIs we call (Exa, Anthropic, HN) all have first-party Python SDKs.
- Jinja2 is the best templating engine for generating HTML from Python.
- GitHub Actions has native Python support with pip caching.
- The target audience (the developer using this) likely knows Python.

### Why static HTML (not React, Next.js, SvelteKit)?

- The output is a single page updated once per day. There is zero interactivity
  that requires client-side JavaScript (except Tailwind CDN).
- A static page loads instantly, costs nothing to host, and has no build step.
- Adding React would mean: node_modules, a build pipeline, a bundler config,
  and hydration — all for a page that changes once every 24 hours.

### Why Jinja2 template inline (not a separate .html file)?

- In v1, the template is ~80 lines. Putting it in a separate file means
  managing template paths, loading logic, and a templates directory. Inline
  is simpler until the template grows past ~200 lines.

### Why Union-Find for clustering (not just nested loops)?

- Nested loop comparison is O(n²) which is fine for n < 200. But Union-Find
  with path compression means the **merging** step is nearly O(1) per pair,
  and we get correct transitive closure for free (if A~B and B~C, then
  A, B, C are all in one cluster even if A and C aren't directly similar).

### Why JSONL for the archive (not SQLite, Postgres)?

- The archive is append-only and read-sequentially. JSONL is the simplest
  format that supports this. No driver, no schema migrations, no connection
  pooling.
- SQLite would be a fine upgrade if we add querying (e.g., "show me all
  funding items from the last month"). For now, grep works.

### Why Tailwind CDN (not installed Tailwind)?

- Zero build step. The CDN script is 90KB gzipped and supports all utilities.
- For a once-daily generated page viewed by 1-5 people, the CDN overhead
  is irrelevant. If this becomes a high-traffic site, we'd switch to
  a pre-built CSS file.

### Why no database?

- The system's "database" is two files: `archive.jsonl` (append-only) and
  `history.json` (overwritten each run). Both are committed to git.
- Git gives us: versioning, rollback, audit trail, and backup — for free.
- A database (Postgres, Redis, Supabase) adds: a server, credentials,
  connection management, migration tooling, and a monthly bill. We add one
  **only when** file-based state breaks (e.g., concurrent writers, complex
  queries, or > 100MB of data).

### Why two deployment targets (GitHub Actions + Railway)?

- **GitHub Actions** is the primary runner: free, reliable, version-controlled.
  It commits output to the repo, which can be served via GitHub Pages.
- **Railway** gives you a **live URL** (e.g., `your-app.up.railway.app`) with
  HTTPS, a persistent server, and an on-demand `/run` endpoint. It's the
  "production" face of the tool.
- Having both means: even if Railway goes down, the Actions workflow still
  generates the digest and commits it to the repo.
