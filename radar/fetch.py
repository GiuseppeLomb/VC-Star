"""Async collection: every source runs isolated, with retries and a global deadline."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from .sources import (
    Source,
    embedded_json_blobs,
    find_persisted_hash,
    parse_html_links,
    parse_rss,
    walk_posts,
)

log = logging.getLogger("radar.fetch")

USER_AGENT = "gta6-rp-radar/1.0 (personal project; +https://github.com/GiuseppeLomb/VC-Star)"
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)
TOTAL_DEADLINE = 170  # seconds (~3 min budget for the whole collection)
RETRY_STATUS = {429, 500, 502, 503, 504}
PER_HOST = 1  # be polite: one request at a time per host (Google News/Reddit rate-limit bursts)
_host_sems: dict[tuple[int, str], asyncio.Semaphore] = {}


def _host_slot(url: str) -> asyncio.Semaphore:
    key = (id(asyncio.get_running_loop()), httpx.URL(url).host)
    if key not in _host_sems:
        _host_sems[key] = asyncio.Semaphore(PER_HOST)
    return _host_sems[key]


@dataclass
class FetchResult:
    source: Source
    items: list[dict] = field(default_factory=list)
    error: str | None = None
    resolved_url: str | None = None
    status: int | None = None


class FetchError(RuntimeError):
    pass


async def http_get(client: httpx.AsyncClient, source: Source, url: str, *, ua: str | None = None,
                   params: dict | None = None, headers: dict | None = None) -> httpx.Response:
    """GET with retries (exponential backoff) on network errors, 429 and 5xx."""
    agent = ua or (BROWSER_UA if source.user_agent == "browser" else (source.user_agent or USER_AGENT))
    hdrs = {"User-Agent": agent, "Accept-Language": "en-US,en;q=0.8,pt-PT;q=0.6"}
    if headers:
        hdrs.update(headers)
    attempts = 1 + max(0, int(source.retries))
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            async with _host_slot(url):
                resp = await client.get(url, params=params, headers=hdrs, timeout=source.timeout)
            if resp.status_code in RETRY_STATUS and attempt < attempts - 1:
                await asyncio.sleep(2 * (2 ** attempt))
                continue
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code} em {url[:120]}")
            return resp
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt < attempts - 1:
                await asyncio.sleep(2 * (2 ** attempt))
                continue
    raise FetchError(f"{type(last_exc).__name__}: {last_exc}"[:200] if last_exc else "falha desconhecida")


# --------------------------------------------------------------------------- resolvers
async def resolve_youtube(client, source: Source, cache: dict) -> str:
    """Find the channel_id from the @handle and confirm it by the feed author."""
    if source.opt("channel_id"):
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={source.opt('channel_id')}"
    key = f"youtube:{source.opt('handle')}"
    if cache.get(key):
        return cache[key]
    handle = source.opt("handle")
    if not handle:
        raise FetchError("youtube_handle sem 'handle'")
    resp = await http_get(client, source, f"https://www.youtube.com/@{handle}",
                          headers={"Cookie": "CONSENT=YES+1"})
    text = resp.text
    ids: list[str] = []
    for rx in (r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
               r'<meta itemprop="identifier" content="(UC[\w-]{22})"',
               r'"externalId":"(UC[\w-]{22})"',
               r'"channelId":"(UC[\w-]{22})"'):
        for cid in re.findall(rx, text):
            if cid not in ids:
                ids.append(cid)
    expected = (source.opt("expect_author") or "").lower()
    for cid in ids[:5]:
        feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
        try:
            fr = await http_get(client, source, feed_url)
            _, meta = parse_rss(fr.content)
        except Exception:  # noqa: BLE001 - try the next candidate
            continue
        author = (meta.get("author") or meta.get("title") or "").lower()
        if not expected or expected in author:
            cache[key] = feed_url
            return feed_url
    raise FetchError(f"não foi possível confirmar o channel_id de @{handle} (candidatos: {ids[:5]})")


async def resolve_discourse_category(client, source: Source, cache: dict) -> str:
    base = (source.opt("base_url") or "").rstrip("/")
    wanted = str(source.opt("category") or "announcements").lower()
    key = f"discourse:{base}:{wanted}"
    if cache.get(key):
        return cache[key]
    resp = await http_get(client, source, f"{base}/categories.json", params={"include_subcategories": "true"})
    cats = []
    for c in resp.json().get("category_list", {}).get("categories", []):
        cats.append(c)
        cats.extend(c.get("subcategory_list") or [])
    exact = [c for c in cats if str(c.get("slug", "")).lower() == wanted]
    fuzzy = [c for c in cats if wanted.rstrip("s") in (str(c.get("slug", "")) + " " + str(c.get("name", ""))).lower()]
    pick = (exact or fuzzy or [None])[0]
    if not pick:
        raise FetchError(f"categoria '{wanted}' não encontrada em {base}")
    url = f"{base}/c/{pick['slug']}/{pick['id']}.rss"
    cache[key] = url
    return url


async def fetch_rockstar_newswire(client, source: Source, cache: dict) -> tuple[list[dict], str]:
    """Rockstar Newswire is a JS app backed by a GraphQL API with persisted queries.

    Strategy: (1) links/JSON already present in the HTML, (2) discover the
    persisted-query hash for the list operation in the page's scripts and call
    the GraphQL endpoint, walking whatever JSON comes back for posts.
    """
    page_url = source.url
    pattern = source.opt("link_pattern", "/newswire/article/")
    page = await http_get(client, source, page_url)
    html_text = page.text

    items = parse_html_links(html_text, page_url, pattern)
    for blob in embedded_json_blobs(html_text):
        items.extend(walk_posts(blob, page_url, pattern))
    if len(items) >= 3:
        return _unique(items), page_url

    operation = source.opt("graphql_operation", "NewswireList")
    endpoint = source.opt("graphql_endpoint", "https://graph.rockstargames.com")
    key = f"rockstar:{operation}"
    candidates = [h for h in (source.opt("graphql_hash"), cache.get(key)) if h]
    if not candidates:
        found = find_persisted_hash(html_text, operation)
        if not found:
            scripts = re.findall(r'<script[^>]+src="([^"]+\.js[^"]*)"', html_text)
            for src in scripts[:25]:
                try:
                    js = await http_get(client, source, urljoin(page_url, src))
                except FetchError:
                    continue
                found = find_persisted_hash(js.text, operation)
                if found:
                    break
        if found:
            candidates.append(found)
    if not candidates:
        raise FetchError("Newswire: endpoint interno não encontrado (usa a fonte rockstar_gnews como reserva)")

    variables = source.opt("graphql_variables") or {
        "page": 1, "tagId": None, "metaUrl": "/newswire", "locale": "en_us",
    }
    last_err = ""
    for h in candidates:
        params = {
            "origin": "https://www.rockstargames.com",
            "operationName": operation,
            "variables": json.dumps(variables, separators=(",", ":")),
            "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": h}}, separators=(",", ":")),
        }
        try:
            resp = await http_get(client, source, endpoint, params=params)
            data = resp.json()
        except (FetchError, ValueError) as exc:
            last_err = str(exc)
            continue
        found_items = walk_posts(data, "https://www.rockstargames.com", pattern)
        if found_items:
            cache[key] = h
            return _unique(found_items), f"{endpoint} ({operation})"
        last_err = json.dumps(data.get("errors") if isinstance(data, dict) else data)[:160]
    cache.pop(key, None)
    raise FetchError(f"Newswire GraphQL sem posts: {last_err}")


def _unique(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        if it["url"] not in seen:
            seen.add(it["url"])
            out.append(it)
    return out


# --------------------------------------------------------------------------- main entry
async def fetch_source(client: httpx.AsyncClient, source: Source, cache: dict) -> FetchResult:
    result = FetchResult(source=source)
    try:
        if source.type == "json" and source.opt("parser") == "rockstar_newswire":
            items, used = await fetch_rockstar_newswire(client, source, cache)
            result.items, result.resolved_url = items, used
        else:
            url = source.url
            resolver = source.opt("resolver")
            if resolver == "youtube_handle":
                url = await resolve_youtube(client, source, cache)
            elif resolver == "discourse_category":
                try:
                    url = await resolve_discourse_category(client, source, cache)
                except (FetchError, ValueError, KeyError) as exc:
                    if not source.url:
                        raise
                    log.warning("%s: resolução falhou (%s), a usar url fixo", source.id, exc)
                    url = source.url
            if not url:
                raise FetchError("fonte sem url")
            result.resolved_url = url
            resp = await http_get(client, source, url)
            result.status = resp.status_code
            if source.type == "rss":
                result.items, _ = parse_rss(resp.content, base_url=url)
            elif source.type == "html":
                result.items = parse_html_links(resp.text, url, source.opt("link_pattern", "."))
            elif source.type == "json":
                result.items = walk_posts(resp.json(), url, source.opt("link_pattern", ""))
        result.items = result.items[: max(1, int(source.max_items))]
    except Exception as exc:  # noqa: BLE001 - one source must never stop the others
        result.error = (str(exc) or type(exc).__name__)[:240]
        result.items = []
        # A cached resolution may be stale: forget it so the next run rediscovers.
        for key in _resolver_keys(source):
            cache.pop(key, None)
    return result


def _resolver_keys(source: Source) -> list[str]:
    resolver = source.opt("resolver")
    if resolver == "youtube_handle":
        return [f"youtube:{source.opt('handle')}"]
    if resolver == "discourse_category":
        base = (source.opt("base_url") or "").rstrip("/")
        return [f"discourse:{base}:{str(source.opt('category') or 'announcements').lower()}"]
    return []


async def fetch_all(sources: list[Source], cache: dict, deadline: float = TOTAL_DEADLINE) -> list[FetchResult]:
    limits = httpx.Limits(max_connections=12, max_keepalive_connections=6)
    async with httpx.AsyncClient(follow_redirects=True, limits=limits, http2=False) as client:
        tasks = {asyncio.create_task(fetch_source(client, s, cache)): s for s in sources}
        done, pending = await asyncio.wait(tasks, timeout=deadline)
        results = [t.result() for t in done]
        for t in pending:
            t.cancel()
            results.append(FetchResult(source=tasks[t], error=f"excedeu o tempo total de {int(deadline)} s"))
    loop_id = id(asyncio.get_running_loop())
    for key in [k for k in _host_sems if k[0] == loop_id]:
        _host_sems.pop(key, None)
    order = {s.id: i for i, s in enumerate(sources)}
    return sorted(results, key=lambda r: order[r.source.id])


def run_fetch(sources: list[Source], cache: dict) -> list[FetchResult]:
    return asyncio.run(fetch_all(sources, cache))
