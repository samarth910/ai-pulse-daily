"""
Event clustering — group normalized records into candidate "events."

Strategy (v1): token-overlap fingerprinting on titles.  Two records belong to
the same event if they share enough meaningful words.  This is deliberately
simple; a future version can add embeddings or an LLM grouping pass.
"""

from __future__ import annotations

import re
from collections import defaultdict

_STOP = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
    "and", "or", "but", "not", "no", "so", "if", "it", "its", "this",
    "that", "has", "have", "had", "do", "does", "did", "will", "would",
    "can", "could", "may", "might", "shall", "should", "about", "just",
    "how", "what", "when", "where", "who", "why", "new", "top", "best",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Lowercase alpha-numeric tokens, stop-words removed."""
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP and len(t) > 2}


def _similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


_MERGE_THRESHOLD = 0.35  # two titles with ≥35% token overlap → same event


def cluster_records(records: list[dict]) -> list[dict]:
    """
    Return a list of event dicts, each containing:

        {
            "event_key":  str,          # representative title (longest)
            "records":    list[dict],    # all records in this cluster
            "domains":    set[str],      # distinct registrable domains
            "sources":    set[str],      # collector names (exa, hn, reddit …)
        }
    """
    if not records:
        return []

    token_cache: list[tuple[int, set[str]]] = []
    for i, rec in enumerate(records):
        token_cache.append((i, _tokenize(rec.get("title", ""))))

    # Union-Find for clustering
    parent: dict[int, int] = {i: i for i in range(len(records))}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(len(token_cache)):
        idx_i, tok_i = token_cache[i]
        for j in range(i + 1, len(token_cache)):
            idx_j, tok_j = token_cache[j]
            if _similarity(tok_i, tok_j) >= _MERGE_THRESHOLD:
                union(idx_i, idx_j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(records)):
        groups[find(i)].append(i)

    events: list[dict] = []
    for indices in groups.values():
        cluster_recs = [records[i] for i in indices]
        representative = max(cluster_recs, key=lambda r: len(r.get("title", "")))
        events.append({
            "event_key": representative.get("title", "untitled"),
            "records": cluster_recs,
            "domains": {r.get("domain", "") for r in cluster_recs} - {""},
            "sources": {r.get("source", "") for r in cluster_recs} - {""},
        })

    events.sort(key=lambda e: len(e["records"]), reverse=True)
    return events
