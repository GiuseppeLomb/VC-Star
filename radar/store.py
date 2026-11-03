"""Persistence: docs/data/news.json, docs/data/health.json and data/seen.json."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from .classify import OFICIAL
from .util import iso, parse_iso

MAX_ITEMS = 500
OFFICIAL_KEEP_DAYS = 90
SEEN_DAYS = 30
HEARTBEAT = timedelta(minutes=30)


def load_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def write_if_changed(path: Path, obj) -> bool:
    path = Path(path)
    text = dump(obj)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


# --------------------------------------------------------------------------- news
def select_items(items: list[dict], now, limit: int = MAX_ITEMS) -> list[dict]:
    """The `limit` most recent items, sorted by published desc.

    Recent OFICIAL items (90 days) are always kept, even beyond the limit, so a
    flood of rumours can never push an official announcement out of the app.
    """
    items = sorted(items, key=lambda i: i.get("published") or "", reverse=True)
    cutoff = iso(now - timedelta(days=OFFICIAL_KEEP_DAYS))
    pinned = [i for i in items if i.get("tag") == OFICIAL and (i.get("published") or "") >= cutoff]
    pinned_ids = {i["id"] for i in pinned}
    rest = [i for i in items if i["id"] not in pinned_ids]
    room = max(0, limit - len(pinned))
    chosen = pinned + rest[:room]
    return sorted(chosen, key=lambda i: i.get("published") or "", reverse=True)


def news_document(items: list[dict], now) -> dict:
    return {"generated_at": iso(now), "count": len(items), "items": items}


def save_news(path: Path, items: list[dict], now, previous: dict | None) -> bool:
    """Writes only if the items changed (generated_at alone is not a change)."""
    if previous is not None and previous.get("items") == items:
        return False
    return write_if_changed(path, news_document(items, now))


# --------------------------------------------------------------------------- seen
def empty_seen() -> dict:
    return {"version": 1, "push_ready": False, "cache": {}, "items": {}}


def prune_seen(seen: dict, now) -> None:
    cutoff = iso(now - timedelta(days=SEEN_DAYS))
    seen["items"] = {k: v for k, v in seen.get("items", {}).items() if (v.get("first_seen") or "") >= cutoff}


# --------------------------------------------------------------------------- health
def update_health(previous: dict, results, now) -> dict:
    """results: list of FetchResult. Keeps last success / error and failure streaks."""
    prev_sources = (previous or {}).get("sources") or {}
    sources = {}
    for r in results:
        s = r.source
        old = prev_sources.get(s.id) or {}
        entry = {
            "name": s.name,
            "tier": s.tier,
            "enabled": True,
            "url": r.resolved_url or s.url,
            "last_success": old.get("last_success"),
            "last_error": old.get("last_error"),
            "error": old.get("error"),
            "consecutive_failures": int(old.get("consecutive_failures") or 0),
            "last_count": old.get("last_count", 0),
        }
        if r.error:
            entry["last_error"] = iso(now)
            entry["error"] = r.error
            entry["consecutive_failures"] += 1
        else:
            entry["last_success"] = iso(now)
            entry["consecutive_failures"] = 0
            entry["error"] = None
            entry["last_count"] = len(r.items)
        sources[s.id] = entry
    return {"generated_at": iso(now), "sources": sources}


def add_disabled(health: dict, disabled_sources) -> None:
    for s in disabled_sources:
        health["sources"][s.id] = {
            "name": s.name, "tier": s.tier, "enabled": False, "url": s.url,
            "last_success": None, "last_error": None, "error": None,
            "consecutive_failures": 0, "last_count": 0,
        }


def _health_signature(doc: dict) -> dict:
    """The parts of health.json whose change is worth a commit (not timestamps)."""
    return {
        sid: (e.get("enabled"), bool(e.get("error")), e.get("url"), e.get("consecutive_failures", 0) >= 3)
        for sid, e in (doc.get("sources") or {}).items()
    }


def save_health(path: Path, new: dict, previous: dict | None, now, force: bool = False) -> bool:
    """Heartbeat every 30 min, or immediately when a source changes state."""
    if previous and not force:
        last = parse_iso(previous.get("generated_at"))
        same = _health_signature(previous) == _health_signature(new)
        if same and last and now - last < HEARTBEAT:
            return False
    return write_if_changed(path, new)
