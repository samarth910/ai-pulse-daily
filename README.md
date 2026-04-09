# Daily AI/Tech Pulse

A batch pipeline that runs once per day, ingests AI/tech signals from the open web, clusters them into events, enforces independent multi-source corroboration, uses an LLM for curation and copy, and publishes a static digest (HTML + JSON).

**Target output:** 10–15 high-signal items per run.

---

## Quick start

### 1. Clone and install

```bash
git clone <your-repo-url>
cd Some_new_vibe_coded_project
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — add your EXA_API_KEY and ANTHROPIC_API_KEY
```

### 3. Run (dry run — no API keys needed)

```bash
DRY_RUN=1 python -m src.main
# On Windows PowerShell:
# $env:DRY_RUN="1"; python -m src.main
```

Open `public/index.html` in your browser.

### 4. Run (live)

```bash
python -m src.main
```

---

## How it works

```
Exa + HN + Reddit → normalize/dedupe → cluster into events → independence gate (≥2 domains)
→ LLM curator (Anthropic + memory of last 14 days) → validate JSON → render HTML + JSON
```

Every stage is a separate module in `src/`. See `CLAUDE.md` for engineering contracts and `docs/ARCHITECTURE.md` for the full deep-dive.

---

## Triangulation rule

Each digest item must have **≥2 URLs on distinct registrable domains** with independent editorial origin. Single-source items are rejected before the LLM ever sees them.

---

## Anti-stale memory

The last 14 days of published headlines are loaded from `data/archive.jsonl` and injected into the LLM prompt. If today's candidate is substantially the same event, the model is instructed to reject it.

---

## Deployment

### GitHub Actions (recommended)

The workflow at `.github/workflows/daily.yml` runs at **00:05 UTC daily** and on manual dispatch. Add these secrets to your repo:

- `EXA_API_KEY`
- `ANTHROPIC_API_KEY`

It commits generated files to `public/` and `data/` automatically.

### Google Cloud Run (recommended for production)

Full step-by-step guide: **[docs/GCP_DEPLOY.md](docs/GCP_DEPLOY.md)**

Quick summary:
1. Create a GCP project, enable Cloud Run + Cloud Build + Secret Manager APIs.
2. Store API keys in Secret Manager (`gcloud secrets create ...`).
3. Build and deploy: `gcloud builds submit` → `gcloud run deploy`.
4. Set up daily runs with Cloud Scheduler hitting `POST /run`.
5. **Cost: $0/month** on free tier.

### Railway (alternative)

1. Push this repo to GitHub.
2. Create a new project on [Railway](https://railway.com) → **Deploy from GitHub**.
3. Add environment variables: `EXA_API_KEY`, `ANTHROPIC_API_KEY`, `RUN_SECRET`.
4. Railway will auto-detect `railway.json` and start the static server on port 8080.
5. To trigger a run: `POST /run` with header `X-Run-Token: <your-secret>`.
6. For scheduled runs, add a **Railway Cron** service that runs `python -m src.main` at `5 0 * * *`.

---

## Configuration

All tunables live in `src/config.py` and read from environment variables. See `.env.example` for the full list.

| Variable | Default | What it controls |
|----------|---------|-----------------|
| `EXA_API_KEY` | *(required)* | Exa search API key |
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic Claude API key |
| `CURATOR_MODEL` | `claude-sonnet-4-6-20250217` | Which Claude model to use |
| `SEARCH_WINDOW_HOURS` | `36` | How far back to search |
| `MEMORY_WINDOW_DAYS` | `14` | How many days of headlines to inject as memory |
| `MAX_DIGEST_ITEMS` | `15` | Max items in the daily digest |
| `MIN_DOMAINS` | `2` | Minimum distinct domains for triangulation |
| `DRY_RUN` | `0` | Set to `1` to skip APIs and use sample data |
| `RUN_SECRET` | *(empty)* | Token to protect POST /run endpoint |

---

## Project structure

```
.
├── CLAUDE.md                     # Engineering contracts (for AI agents)
├── README.md                     # This file (for humans)
├── requirements.txt
├── .env.example
├── server.py                     # Static server (Cloud Run / Railway)
├── Dockerfile                    # Container image for Cloud Run
├── cloudbuild.yaml               # GCP Cloud Build pipeline
├── railway.json / railway.toml   # Railway deploy config
├── Procfile                      # Railway process definition
├── src/
│   ├── __init__.py
│   ├── config.py                 # All tunables
│   ├── ingest.py                 # Exa + HN + Reddit collectors
│   ├── normalize.py              # URL canonicalization + dedupe
│   ├── cluster.py                # Title-similarity event grouping
│   ├── gates.py                  # Independence gate (≥2 domains)
│   ├── state.py                  # Archive + history persistence
│   ├── curate.py                 # Anthropic LLM + memory + validation
│   ├── render.py                 # Jinja2 HTML + JSON output
│   └── main.py                   # Orchestrator
├── data/                         # Runtime state (archive.jsonl, history.json)
├── public/                       # Generated site (index.html, digest.json)
├── docs/                         # Architecture documentation
└── .github/workflows/daily.yml   # Scheduled CI
```
