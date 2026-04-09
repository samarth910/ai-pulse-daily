"""
Central configuration — every tunable reads from env vars with sane defaults.
Import this module instead of scattering os.getenv() across files.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / os.getenv("DATA_DIR", "data")
OUTPUT_DIR = ROOT_DIR / os.getenv("OUTPUT_DIR", "public")

ARCHIVE_PATH = DATA_DIR / "archive.jsonl"
HISTORY_PATH = DATA_DIR / "history.json"

# ── API keys (placeholders OK — checked at runtime) ─────────────────────────
EXA_API_KEY: str = os.getenv("EXA_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# ── LLM ──────────────────────────────────────────────────────────────────────
CURATOR_MODEL: str = os.getenv("CURATOR_MODEL", "claude-sonnet-4-6-20250217")
MAX_CURATOR_TOKENS: int = int(os.getenv("MAX_CURATOR_TOKENS", "4096"))

# ── Search ───────────────────────────────────────────────────────────────────
SEARCH_WINDOW_HOURS: int = int(os.getenv("SEARCH_WINDOW_HOURS", "36"))

EXA_QUERIES: list[str] = [
    "major new AI model release or breakthrough in the last 36 hours",
    "new AI tool or framework gaining mass traction this week",
    "significant AI startup funding round or acquisition announced today",
    "important new research paper or technique in machine learning",
    "notable AI product launch or major update shipped today",
]
EXA_RESULTS_PER_QUERY: int = int(os.getenv("EXA_RESULTS_PER_QUERY", "25"))

HN_QUERY: str = "AI OR LLM OR GPT OR Claude OR diffusion OR agent"
HN_RESULTS: int = int(os.getenv("HN_RESULTS", "30"))

REDDIT_FEEDS: list[str] = [
    "https://www.reddit.com/r/MachineLearning/top/.rss?t=day",
    "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day",
    "https://www.reddit.com/r/artificial/top/.rss?t=day",
]

# ── Pipeline thresholds ──────────────────────────────────────────────────────
MEMORY_WINDOW_DAYS: int = int(os.getenv("MEMORY_WINDOW_DAYS", "14"))
MIN_DOMAINS: int = int(os.getenv("MIN_DOMAINS", "2"))
MAX_DIGEST_ITEMS: int = int(os.getenv("MAX_DIGEST_ITEMS", "15"))
MIN_CLUSTER_SIZE: int = int(os.getenv("MIN_CLUSTER_SIZE", "1"))

# ── Runtime flags ────────────────────────────────────────────────────────────
DRY_RUN: bool = os.getenv("DRY_RUN", "0") == "1"
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
