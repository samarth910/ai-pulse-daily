"""
URL canonicalization, registrable-domain extraction, and deduplication.

Pure functions — no network, no API keys. Testable in isolation.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import tldextract

# Tracking / analytics params that add no editorial value
_STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "fbclid", "gclid", "igshid", "si", "feature",
}


def canonical_url(raw: str) -> str:
    """Normalize a URL: lowercase host, strip tracking params, drop fragment."""
    parsed = urlparse(raw.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    qs = parse_qs(parsed.query, keep_blank_values=False)
    clean_qs = {k: v for k, v in qs.items() if k.lower() not in _STRIP_PARAMS}
    cleaned = urlunparse((
        parsed.scheme.lower(),
        host + (f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""),
        parsed.path.rstrip("/") or "/",
        parsed.params,
        urlencode(clean_qs, doseq=True),
        "",  # drop fragment
    ))
    return cleaned


def registrable_domain(url: str) -> str:
    """
    Return the registrable domain (eTLD+1) for a URL.

    Examples:
        https://blog.openai.com/foo → openai.com
        https://news.ycombinator.com → ycombinator.com
        https://old.reddit.com/r/ML  → reddit.com
    """
    ext = tldextract.extract(url)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return (ext.domain or "unknown").lower()


def dedupe_records(records: list[dict]) -> list[dict]:
    """
    Remove duplicate records by canonical URL.
    First occurrence wins; order is preserved.
    """
    seen: set[str] = set()
    unique: list[dict] = []
    for rec in records:
        canon = canonical_url(rec.get("url", ""))
        if canon in seen:
            continue
        seen.add(canon)
        rec["canonical_url"] = canon
        rec["domain"] = registrable_domain(canon)
        unique.append(rec)
    return unique
