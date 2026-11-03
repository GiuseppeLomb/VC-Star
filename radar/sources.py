"""Source definitions (config/sources.yml) and response parsers."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import feedparser
import yaml
from bs4 import BeautifulSoup

from .util import clean_text, parse_iso, struct_to_dt

TIERS = ("official", "credible", "community")
TYPES = ("rss", "html", "json")
RELEVANCE = ("gta6", "topic", "always")


@dataclass
class Source:
    id: str
    name: str
    type: str
    url: str
    tier: str
    enabled: bool = True
    timeout: float = 15
    retries: int = 1
    max_items: int = 60
    lang: str = "en"
    relevance: str = "gta6"
    user_agent: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def opt(self, key: str, default=None):
        return self.extra.get(key, default)


class ConfigError(ValueError):
    pass


def load_sources(path: str | Path) -> list[Source]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    defaults = data.get("defaults") or {}
    seen_ids: set[str] = set()
    out: list[Source] = []
    known = set(Source.__dataclass_fields__) - {"extra"}
    for raw in data.get("sources") or []:
        merged = {**defaults, **raw}
        sid = str(merged.get("id") or "").strip()
        if not sid:
            raise ConfigError(f"Fonte sem id: {raw}")
        if sid in seen_ids:
            raise ConfigError(f"id repetido: {sid}")
        seen_ids.add(sid)
        if merged.get("type") not in TYPES:
            raise ConfigError(f"{sid}: type tem de ser um de {TYPES}")
        if merged.get("tier") not in TIERS:
            raise ConfigError(f"{sid}: tier tem de ser um de {TIERS}")
        if merged.get("relevance", "gta6") not in RELEVANCE:
            raise ConfigError(f"{sid}: relevance tem de ser um de {RELEVANCE}")
        kwargs = {k: merged[k] for k in known if k in merged and merged[k] is not None}
        kwargs["id"] = sid
        kwargs["name"] = str(merged.get("name") or sid)
        kwargs["url"] = str(merged.get("url") or "")
        kwargs["enabled"] = bool(merged.get("enabled", True))
        extra = {k: v for k, v in merged.items() if k not in known}
        out.append(Source(**kwargs, extra=extra))
    return out


# --------------------------------------------------------------------------- parsers
def _raw(title, url, published=None, summary="", author="", source_title=None, source_url=None):
    return {
        "title": title or "",
        "url": url or "",
        "published": published,
        "summary": summary or "",
        "author": author or "",
        "source_title": source_title,
        "source_url": source_url,
    }


def parse_rss(content: bytes, base_url: str = "") -> tuple[list[dict], dict]:
    """Returns (items, feed_meta). Raises ValueError if it is not a feed."""
    parsed = feedparser.parse(content)
    if not parsed.entries and not parsed.get("version"):
        # e.g. a Cloudflare/consent/"blocked" HTML page served with HTTP 200
        snippet = content[:80].decode("utf-8", "replace").replace("\n", " ") if isinstance(content, bytes) else ""
        raise ValueError(f"resposta não é um feed RSS/Atom ({snippet!r})"[:200])
    meta = {
        "title": parsed.feed.get("title", ""),
        "author": (parsed.feed.get("author_detail") or {}).get("name") or parsed.feed.get("author", ""),
    }
    items = []
    for e in parsed.entries:
        src = e.get("source") or {}
        summary = e.get("summary") or e.get("description") or ""
        if not summary and e.get("media_description"):
            summary = e.get("media_description")
        link = e.get("link") or ""
        if link and base_url:
            link = urljoin(base_url, link)
        items.append(_raw(
            title=e.get("title"),
            url=link,
            published=struct_to_dt(e.get("published_parsed") or e.get("updated_parsed")),
            summary=summary,
            author=e.get("author", ""),
            source_title=src.get("title"),
            source_url=src.get("href") or src.get("url"),
        ))
    return items, meta


def parse_html_links(text: str, base_url: str, link_pattern: str) -> list[dict]:
    """Generic HTML parser: every <a> whose href matches link_pattern."""
    soup = BeautifulSoup(text, "html.parser")
    rx = re.compile(link_pattern)
    seen, items = set(), []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if not rx.search(href) or href in seen:
            continue
        title = clean_text(a.get("title") or a.get("aria-label") or a.get_text(" "))
        if len(title) < 8:
            continue
        seen.add(href)
        items.append(_raw(title, href))
    return items


_DATE_KEYS = ("created", "created_at", "date", "published", "published_at", "publishDate", "posted", "updated")


def walk_posts(obj: Any, base_url: str, link_pattern: str) -> list[dict]:
    """Find {title, url} dicts anywhere inside a JSON document."""
    rx = re.compile(link_pattern) if link_pattern else None
    found: dict[str, dict] = {}

    def visit(node):
        if isinstance(node, dict):
            title = node.get("title") or node.get("name")
            url = node.get("url") or node.get("link") or node.get("href")
            if isinstance(title, str) and isinstance(url, str):
                full = urljoin(base_url, url)
                if (rx is None or rx.search(full)) and full not in found:
                    published = None
                    for k in _DATE_KEYS:
                        v = node.get(k)
                        if isinstance(v, str):
                            published = parse_iso(v) or parse_iso(v.replace(" ", "T"))
                        elif isinstance(v, (int, float)) and v > 10**9:
                            from datetime import datetime, timezone
                            published = datetime.fromtimestamp(v / (1000 if v > 10**12 else 1), tz=timezone.utc)
                        if published:
                            break
                    summary = node.get("subtitle") or node.get("description") or node.get("excerpt") or ""
                    found[full] = _raw(clean_text(title), full, published, summary if isinstance(summary, str) else "")
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    visit(obj)
    return list(found.values())


def embedded_json_blobs(html_text: str) -> list[Any]:
    """JSON blobs embedded in a page (Next.js data, ld+json, window.__STATE__ = {...})."""
    blobs = []
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup.find_all("script"):
        body = tag.string or tag.get_text() or ""
        body = body.strip()
        if not body:
            continue
        candidates = []
        if tag.get("type") in ("application/json", "application/ld+json") or tag.get("id") == "__NEXT_DATA__":
            candidates.append(body)
        else:
            m = re.search(r"=\s*(\{.*\})\s*;?\s*$", body, re.DOTALL)
            if m and len(m.group(1)) < 5_000_000:
                candidates.append(m.group(1))
        for c in candidates:
            try:
                blobs.append(json.loads(c))
            except ValueError:
                continue
    return blobs


def find_persisted_hash(text: str, operation: str) -> str | None:
    """Look for `<operation> ... <64 hex>` or `<64 hex> ... <operation>` in a JS bundle."""
    best: tuple[int, str] | None = None
    for op in re.finditer(r"\b" + re.escape(operation) + r"\b", text):
        start = max(0, op.start() - 600)
        window = text[start: op.end() + 600]
        for m in re.finditer(r"(?<![0-9a-f])([0-9a-f]{64})(?![0-9a-f])", window):
            dist = abs((start + m.start()) - op.start())
            if best is None or dist < best[0]:
                best = (dist, m.group(1))
    return best[1] if best else None
