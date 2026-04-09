"""
Render — produce the static site artifacts.

Two-level output:
    public/index.html                   Homepage with run cards + "Run Now" button.
    public/runs/{run_id}/index.html     Detail page for a single run with executive briefs.
    public/runs/{run_id}/digest.json    Machine-readable JSON for that run.

Includes a degraded "quiet day" detail page when the pipeline has no items,
and a first-visit homepage when no runs exist yet.
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

# ── Shared HTML head (Tailwind + Inter font) ─────────────────────────────────

_HEAD = """\
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
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
"""

# ── Homepage template (run cards + Run Now) ──────────────────────────────────

_HOMEPAGE_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
""" + _HEAD + """\
<title>AI Pulse — Dashboard</title>
</head>
<body class="bg-gray-950 text-gray-100 min-h-screen">

  <header class="border-b border-gray-800">
    <div class="max-w-4xl mx-auto px-4 py-8">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="text-2xl font-bold tracking-tight">
            <span class="text-white">AI</span><span class="text-purple-400"> Pulse</span>
          </h1>
          <p class="text-sm text-gray-500 mt-1">The signal, not the noise</p>
        </div>
        <div class="flex items-center gap-4">
          <span id="run-status" class="text-xs text-gray-600 hidden"></span>
          <button id="run-btn" onclick="triggerRun()"
            class="px-5 py-2.5 bg-purple-600 hover:bg-purple-500 text-white text-sm font-semibold rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-purple-400 focus:ring-offset-2 focus:ring-offset-gray-950">
            Run Now
          </button>
        </div>
      </div>
    </div>
  </header>

  <main class="max-w-4xl mx-auto px-4 py-8">
  {% if runs %}
    <p class="text-sm text-gray-500 mb-6">{{ runs|length }} run{{ 's' if runs|length != 1 else '' }} so far</p>
    <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {% for run in runs %}
      <div class="card bg-gray-900 border border-gray-800 rounded-xl p-5 relative group" id="card-{{ run.run_id }}">
        <a href="runs/{{ run.run_id }}/" class="block">
          <p class="text-sm font-semibold text-gray-200">{{ run.display_date }}</p>
          <p class="text-xs text-gray-500 mt-0.5">{{ run.display_time }} UTC</p>
          <p class="text-xs text-purple-400 mt-2">{{ run.item_count }} item{{ 's' if run.item_count != 1 else '' }}</p>
          {% if run.top_headlines %}
          <ul class="mt-3 space-y-1">
            {% for h in run.top_headlines %}
            <li class="text-xs text-gray-400 leading-snug truncate">{{ h }}</li>
            {% endfor %}
          </ul>
          {% endif %}
        </a>
        <button onclick="event.stopPropagation(); deleteRun('{{ run.run_id }}')"
          class="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity text-gray-600 hover:text-red-400 p-1.5 rounded-lg hover:bg-red-500/10"
          title="Delete this run">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
        </button>
      </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="text-center py-20">
      <p class="text-4xl mb-4">🚀</p>
      <h2 class="text-xl font-semibold text-gray-300">No runs yet</h2>
      <p class="text-sm text-gray-500 mt-2 max-w-md mx-auto">
        Click <strong>Run Now</strong> above to generate your first AI Pulse digest.
      </p>
    </div>
  {% endif %}
  </main>

  <footer class="border-t border-gray-800 mt-12">
    <div class="max-w-4xl mx-auto px-4 py-6 text-center">
      <p class="text-xs text-gray-600">Built to cut through the noise</p>
    </div>
  </footer>

  <script>
  async function triggerRun() {
    const btn = document.getElementById('run-btn');
    const status = document.getElementById('run-status');
    btn.disabled = true;
    btn.textContent = 'Running...';
    btn.classList.add('opacity-50', 'cursor-not-allowed');
    status.textContent = 'Pipeline triggered - this takes 30-60s';
    status.classList.remove('hidden');
    try {
      const resp = await fetch('/run-now', { method: 'POST' });
      if (resp.ok) {
        status.textContent = 'Done! Reloading...';
        setTimeout(() => window.location.reload(), 3000);
      } else {
        const text = await resp.text();
        status.textContent = 'Error: ' + text;
        btn.disabled = false;
        btn.textContent = 'Run Now';
        btn.classList.remove('opacity-50', 'cursor-not-allowed');
      }
    } catch (e) {
      status.textContent = 'Network error: ' + e.message;
      btn.disabled = false;
      btn.textContent = 'Run Now';
      btn.classList.remove('opacity-50', 'cursor-not-allowed');
    }
  }

  async function deleteRun(runId) {
    if (!confirm('Delete this run? This cannot be undone.')) return;
    try {
      const resp = await fetch('/delete-run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: runId }),
      });
      if (resp.ok) {
        const card = document.getElementById('card-' + runId);
        if (card) card.remove();
      } else {
        alert('Failed to delete: ' + (await resp.text()));
      }
    } catch (e) {
      alert('Network error: ' + e.message);
    }
  }
  </script>

</body>
</html>
""")


# ── Run detail template (items with executive briefs) ────────────────────────

_RUN_DETAIL_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
""" + _HEAD + """\
<title>AI Pulse — {{ date }}</title>
</head>
<body class="bg-gray-950 text-gray-100 min-h-screen">

  <header class="border-b border-gray-800">
    <div class="max-w-3xl mx-auto px-4 py-8">
      <div class="flex items-center justify-between">
        <div>
          <a href="/" class="text-xs text-purple-400 hover:text-purple-300 mb-2 inline-block">&larr; All runs</a>
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

  <main class="max-w-3xl mx-auto px-4 py-8 space-y-6">
  {% if items %}
    {% for item in items %}
    <article class="card bg-gray-900 border border-gray-800 rounded-xl p-6">
      <div class="flex items-start justify-between gap-3 mb-3">
        <h2 class="text-xl font-bold leading-snug text-gray-50">{{ item.headline }}</h2>
        <span class="shrink-0 text-xs font-medium px-2.5 py-1 rounded-full {{ item.badge_class }}">
          {{ item.badge_label }}
        </span>
      </div>

      <p class="text-sm text-gray-300 leading-relaxed mb-4 font-medium">{{ item.summary }}</p>

      {% if item.executive_brief %}
      <div class="border-t border-gray-800 pt-4 mb-4">
        <button onclick="this.nextElementSibling.classList.toggle('hidden'); this.querySelector('span').textContent = this.nextElementSibling.classList.contains('hidden') ? 'Read brief ▸' : 'Collapse ▾'"
          class="text-xs font-semibold text-purple-400 hover:text-purple-300 mb-3 inline-block cursor-pointer">
          <span>Read brief ▸</span>
        </button>
        <div class="hidden prose-compact">
          {% for para in item.brief_paragraphs %}
          <p class="text-sm text-gray-400 leading-relaxed mb-3">{{ para }}</p>
          {% endfor %}
        </div>
      </div>
      {% endif %}

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

def render_run(items: list[dict], run_id: str, source_count: int = 0) -> None:
    """Generate a run's detail page and JSON under public/runs/{run_id}/."""
    run_dir = config.OUTPUT_DIR / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)

    enriched = []
    for item in items:
        cat = item.get("category", "other")
        label, cls = _BADGE.get(cat, _BADGE["other"])
        brief = item.get("executive_brief", "")
        brief_paragraphs = [p.strip() for p in brief.split("\n\n") if p.strip()] if brief else []
        if not brief_paragraphs and brief:
            brief_paragraphs = [p.strip() for p in brief.split("\n") if p.strip()]
        enriched.append({
            **item,
            "badge_label": label,
            "badge_class": cls,
            "brief_paragraphs": brief_paragraphs,
        })

    html = _RUN_DETAIL_TEMPLATE.render(
        date=now.strftime("%B %d, %Y"),
        time=now.strftime("%H:%M"),
        item_count=len(items),
        items=enriched,
        source_count=source_count,
    )
    (run_dir / "index.html").write_text(html, encoding="utf-8")
    log.info("Wrote %s (%d items)", run_dir / "index.html", len(items))

    digest = {
        "run_id": run_id,
        "generated_at": now.isoformat(),
        "item_count": len(items),
        "items": items,
    }
    (run_dir / "digest.json").write_text(
        json.dumps(digest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Wrote %s", run_dir / "digest.json")


def render_homepage(runs_index: list[dict]) -> None:
    """Generate the homepage with run cards."""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    enriched_runs = []
    for run in runs_index:
        ts_str = run.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            display_date = ts.strftime("%B %d, %Y")
            display_time = ts.strftime("%H:%M")
        except (ValueError, TypeError):
            display_date = run.get("run_id", "Unknown")
            display_time = ""
        enriched_runs.append({
            **run,
            "display_date": display_date,
            "display_time": display_time,
        })

    html = _HOMEPAGE_TEMPLATE.render(runs=enriched_runs)
    (config.OUTPUT_DIR / "index.html").write_text(html, encoding="utf-8")
    log.info("Wrote homepage with %d run cards", len(enriched_runs))


def render(items: list[dict], run_id: str, source_count: int = 0,
           runs_index: list[dict] | None = None) -> None:
    """
    Orchestrator called from main.py.
    Renders the run detail page and then re-renders the homepage.
    """
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    render_run(items, run_id, source_count)
    if runs_index is not None:
        render_homepage(runs_index)
