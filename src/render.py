"""
Render — produce the static site artifacts.

Outputs:
    public/index.html   Human-readable digest with Tailwind styling.
    public/digest.json   Machine-readable JSON for downstream consumers.

Includes a degraded "quiet day" page when the pipeline has no items.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Template

from src import config

log = logging.getLogger(__name__)

# ── Category badge colours ───────────────────────────────────────────────────

_BADGE = {
    "model_release": ("Model", "bg-purple-500/20 text-purple-300"),
    "tool_launch":   ("Tool",  "bg-blue-500/20 text-blue-300"),
    "research":      ("Research", "bg-green-500/20 text-green-300"),
    "funding":       ("Funding",  "bg-yellow-500/20 text-yellow-300"),
    "acquisition":   ("Acquisition", "bg-red-500/20 text-red-300"),
    "open_source":   ("Open Source", "bg-cyan-500/20 text-cyan-300"),
    "policy":        ("Policy", "bg-orange-500/20 text-orange-300"),
    "other":         ("Other",  "bg-gray-500/20 text-gray-300"),
}

# ── Jinja2 HTML template ────────────────────────────────────────────────────

_HTML_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Pulse — {{ date }}</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>
tailwind.config = {
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'system-ui', 'sans-serif'] },
    },
  },
}
</script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  body { font-family: 'Inter', system-ui, sans-serif; }
  .card:hover { transform: translateY(-2px); box-shadow: 0 8px 30px rgba(0,0,0,0.3); }
  .card { transition: transform 0.2s ease, box-shadow 0.2s ease; }
</style>
</head>
<body class="bg-gray-950 text-gray-100 min-h-screen">

  <!-- Header -->
  <header class="border-b border-gray-800">
    <div class="max-w-3xl mx-auto px-4 py-8">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-2xl font-bold tracking-tight">
            <span class="text-white">AI</span><span class="text-purple-400"> Pulse</span>
          </h1>
          <p class="text-sm text-gray-500 mt-1">The signal, not the noise</p>
        </div>
        <div class="text-right">
          <p class="text-sm font-medium text-gray-400">{{ date }}</p>
          <p class="text-xs text-gray-600">{{ item_count }} item{{ 's' if item_count != 1 else '' }} · updated {{ time }} UTC</p>
        </div>
      </div>
    </div>
  </header>

  <!-- Body -->
  <main class="max-w-3xl mx-auto px-4 py-8 space-y-4">
  {% if items %}
    {% for item in items %}
    <article class="card bg-gray-900 border border-gray-800 rounded-xl p-5">
      <div class="flex items-start justify-between gap-3 mb-2">
        <h2 class="text-lg font-semibold leading-snug text-gray-50">{{ item.headline }}</h2>
        <span class="shrink-0 text-xs font-medium px-2.5 py-1 rounded-full {{ item.badge_class }}">
          {{ item.badge_label }}
        </span>
      </div>
      <p class="text-sm text-gray-400 leading-relaxed mb-3">{{ item.why_it_matters }}</p>
      <div class="flex flex-wrap gap-3">
        {% for link in item.links %}
        <a href="{{ link.url }}" target="_blank" rel="noopener"
           class="text-xs font-medium text-purple-400 hover:text-purple-300 hover:underline">
          {{ link.label }} ↗
        </a>
        {% endfor %}
      </div>
      {% if item.impact_score %}
      <div class="mt-3 flex items-center gap-1.5">
        <span class="text-xs text-gray-600">Impact</span>
        <div class="flex gap-0.5">
          {% for i in range(10) %}
          <div class="w-2 h-2 rounded-full {{ 'bg-purple-500' if i < item.impact_score else 'bg-gray-800' }}"></div>
          {% endfor %}
        </div>
      </div>
      {% endif %}
    </article>
    {% endfor %}
  {% else %}
    <div class="text-center py-20">
      <p class="text-4xl mb-4">🌙</p>
      <h2 class="text-xl font-semibold text-gray-300">Quiet day</h2>
      <p class="text-sm text-gray-500 mt-2 max-w-md mx-auto">
        Nothing passed the triangulation bar today.
        Either the AI world took a breather, or our sources are temporarily unavailable.
        Check back tomorrow.
      </p>
    </div>
  {% endif %}
  </main>

  <!-- Footer -->
  <footer class="border-t border-gray-800 mt-12">
    <div class="max-w-3xl mx-auto px-4 py-6 text-center">
      <p class="text-xs text-gray-600">
        Built to cut through the noise · Triangulated from {{ source_count }} sources ·
        <a href="digest.json" class="text-purple-500 hover:underline">JSON feed</a>
      </p>
    </div>
  </footer>

</body>
</html>
""")


# ── Public API ───────────────────────────────────────────────────────────────

def render(items: list[dict], source_count: int = 0) -> None:
    """Generate index.html and digest.json in OUTPUT_DIR."""
    out = config.OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)

    enriched = []
    for item in items:
        cat = item.get("category", "other")
        label, cls = _BADGE.get(cat, _BADGE["other"])
        enriched.append({**item, "badge_label": label, "badge_class": cls})

    html = _HTML_TEMPLATE.render(
        date=now.strftime("%B %d, %Y"),
        time=now.strftime("%H:%M"),
        item_count=len(items),
        items=enriched,
        source_count=source_count,
    )
    (out / "index.html").write_text(html, encoding="utf-8")
    log.info("Wrote %s (%d items)", out / "index.html", len(items))

    digest = {
        "generated_at": now.isoformat(),
        "item_count": len(items),
        "items": items,
    }
    (out / "digest.json").write_text(
        json.dumps(digest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Wrote %s", out / "digest.json")
