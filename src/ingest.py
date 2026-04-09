"""
Collectors — each function hits one source and returns list[dict] with a
uniform RawRecord shape:

    {
        "url":       str,
        "title":     str,
        "snippet":   str,
        "published": str | None,   # ISO-8601 or None
        "source":    str,          # e.g. "exa", "hn", "reddit"
    }

Collectors swallow their own errors and return [] on failure so one flaky
source never kills the whole run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from src import config

log = logging.getLogger(__name__)


# ── Exa semantic search ─────────────────────────────────────────────────────

def collect_exa() -> list[dict]:
    """Run multiple semantic queries via the Exa Search API."""
    if not config.EXA_API_KEY:
        log.warning("EXA_API_KEY not set — skipping Exa collector")
        return []

    try:
        from exa_py import Exa  # type: ignore[import-untyped]
        client = Exa(api_key=config.EXA_API_KEY)
    except Exception as exc:
        log.error("Exa client init failed: %s", exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.SEARCH_WINDOW_HOURS)
    start_date = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    records: list[dict] = []
    for query in config.EXA_QUERIES:
        try:
            resp = client.search_and_contents(
                query=query,
                num_results=config.EXA_RESULTS_PER_QUERY,
                start_published_date=start_date,
                text={"max_characters": 500},
            )
            for r in resp.results:
                records.append({
                    "url": r.url,
                    "title": r.title or "",
                    "snippet": getattr(r, "text", "") or "",
                    "published": getattr(r, "published_date", None),
                    "source": "exa",
                })
        except Exception as exc:
            log.error("Exa query failed (%s): %s", query[:40], exc)
    log.info("Exa collected %d raw records", len(records))
    return records


# ── Hacker News (Algolia API — free, no key) ────────────────────────────────

_HN_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"


def collect_hn() -> list[dict]:
    """Fetch recent HN stories matching AI-related terms.

    Algolia doesn't support boolean OR in the query param, so we run one
    request per search term and merge/dedupe by objectID.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.SEARCH_WINDOW_HOURS)
    cutoff_ts = int(cutoff.timestamp())

    seen_ids: set[str] = set()
    records: list[dict] = []

    for term in config.HN_QUERIES:
        try:
            resp = requests.get(
                _HN_SEARCH,
                params={
                    "query": term,
                    "tags": "story",
                    "numericFilters": f"created_at_i>{cutoff_ts}",
                    "hitsPerPage": config.HN_RESULTS_PER_QUERY,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("HN fetch failed for '%s': %s", term, exc)
            continue

        for hit in data.get("hits", []):
            oid = hit.get("objectID", "")
            if oid in seen_ids:
                continue
            seen_ids.add(oid)
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={oid}"
            records.append({
                "url": url,
                "title": hit.get("title", ""),
                "snippet": "",
                "published": hit.get("created_at"),
                "source": "hn",
            })

    log.info("HN collected %d raw records", len(records))
    return records


# ── Reddit RSS (no API key required) ────────────────────────────────────────

def collect_reddit() -> list[dict]:
    """Parse top-of-day RSS feeds from configured subreddits."""
    records: list[dict] = []
    headers = {"User-Agent": "DailyAIPulse/1.0"}

    for feed_url in config.REDDIT_FEEDS:
        try:
            resp = requests.get(feed_url, headers=headers, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
            for entry in feed.entries[:15]:
                records.append({
                    "url": entry.get("link", ""),
                    "title": entry.get("title", ""),
                    "snippet": entry.get("summary", "")[:500],
                    "published": entry.get("published"),
                    "source": "reddit",
                })
        except Exception as exc:
            log.error("Reddit RSS failed (%s): %s", feed_url, exc)
    log.info("Reddit collected %d raw records", len(records))
    return records


# ── Aggregate all collectors ─────────────────────────────────────────────────

def collect_all() -> list[dict]:
    """Run every collector and merge results into one list."""
    all_records: list[dict] = []
    for collector in [collect_exa, collect_hn, collect_reddit]:
        try:
            all_records.extend(collector())
        except Exception as exc:
            log.error("Collector %s crashed: %s", collector.__name__, exc)
    log.info("Total raw records from all collectors: %d", len(all_records))
    return all_records
