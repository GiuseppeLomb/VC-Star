"""Parsers and auto-discovery, exercised offline with httpx.MockTransport (synthetic responses)."""
import asyncio
import json

import httpx

from conftest import make_source
from radar.fetch import fetch_source
from radar.sources import find_persisted_hash, load_sources, parse_rss, walk_posts

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>GTA 6 roleplay servers - IGN</title><link>https://news.google.com/rss/articles/AU_yqLabc?oc=5</link>
<pubDate>Fri, 20 Nov 2026 10:00:00 GMT</pubDate><source url="https://www.ign.com">IGN</source></item>
</channel></rss>"""

YT_FEED = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Rockstar Games</title>
<author><name>Rockstar Games</name></author>
<entry><title>Grand Theft Auto VI Trailer 3</title><link rel="alternate" href="https://www.youtube.com/watch?v=x"/>
<published>2026-11-20T10:00:00+00:00</published></entry></feed>"""

H1 = "a" * 64
H2 = "b" * 64


def run_source(source, handler, cache=None):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_source(client, source, cache if cache is not None else {})
    return asyncio.run(go())


def test_real_config_is_valid():
    sources = load_sources("config/sources.yml")
    ids = [s.id for s in sources]
    assert len(ids) == len(set(ids))
    assert {"rockstar_newswire", "cfx_announcements", "rockstar_youtube", "gnews_pt"} <= set(ids)


def test_parse_rss_keeps_google_source():
    items, _ = parse_rss(RSS)
    assert items[0]["source_title"] == "IGN" and items[0]["source_url"] == "https://www.ign.com"
    assert items[0]["published"].isoformat().startswith("2026-11-20T10:00")


def test_youtube_handle_is_resolved_and_verified():
    good, bad = "UC" + "G" * 22, "UC" + "B" * 22

    def handler(req):
        if req.url.path == "/@RockstarGames":
            html = f'<link rel="canonical" href="https://www.youtube.com/channel/{good}"> "channelId":"{bad}"'
            return httpx.Response(200, text=html)
        if req.url.params.get("channel_id") == good:
            return httpx.Response(200, content=YT_FEED)
        return httpx.Response(200, content=YT_FEED.replace(b"Rockstar Games", b"Someone Else"))

    src = make_source(id="yt", tier="official", url="", extra={"resolver": "youtube_handle", "handle": "RockstarGames",
                                                              "expect_author": "Rockstar Games"})
    cache = {}
    res = run_source(src, handler, cache)
    assert res.error is None and res.resolved_url.endswith(good)
    assert cache["youtube:RockstarGames"].endswith(good)
    assert res.items[0]["title"] == "Grand Theft Auto VI Trailer 3"


def test_discourse_category_is_resolved():
    cats = {"category_list": {"categories": [
        {"id": 1, "slug": "general", "name": "General", "subcategory_list": []},
        {"id": 37, "slug": "cfx-news", "name": "News", "subcategory_list": [
            {"id": 81, "slug": "announcements", "name": "Announcements"}]}]}}

    def handler(req):
        if req.url.path == "/categories.json":
            return httpx.Response(200, json=cats)
        if req.url.path == "/c/announcements/81.rss":
            return httpx.Response(200, content=RSS)
        return httpx.Response(404)

    src = make_source(id="cfx", tier="official", url="https://forum.cfx.re/c/announcements.rss",
                      extra={"resolver": "discourse_category", "base_url": "https://forum.cfx.re", "category": "announcements"})
    res = run_source(src, handler)
    assert res.error is None and res.resolved_url == "https://forum.cfx.re/c/announcements/81.rss"
    assert len(res.items) == 1


def test_rockstar_newswire_discovers_persisted_query():
    page = '<html><script src="/assets/app.js"></script></html>'
    js = f'x={{op:"OtherQuery",hash:"{H2}"}};y={{op:"NewswireList",hash:"{H1}"}}'
    posts = {"data": {"posts": {"results": [
        {"id": 1, "title": "GTA VI Online: Private Servers", "url": "/newswire/article/1/gta-vi-online", "created": "2026-11-20T10:00:00Z"},
        {"id": 2, "title": "Red Dead Online bonuses", "url": "/newswire/article/2/rdo", "created": "2026-11-19T10:00:00Z"}]}}}
    seen_hashes = []

    def handler(req):
        if req.url.path == "/newswire":
            return httpx.Response(200, text=page)
        if req.url.path == "/assets/app.js":
            return httpx.Response(200, text=js)
        if req.url.host == "graph.rockstargames.com":
            ext = json.loads(req.url.params["extensions"])
            seen_hashes.append(ext["persistedQuery"]["sha256Hash"])
            return httpx.Response(200, json=posts)
        return httpx.Response(404)

    src = make_source(id="rs", type="json", tier="official", url="https://www.rockstargames.com/newswire",
                      extra={"parser": "rockstar_newswire", "link_pattern": "/newswire/article/"})
    cache = {}
    res = run_source(src, handler, cache)
    assert res.error is None, res.error
    assert seen_hashes == [H1] and cache["rockstar:NewswireList"] == H1
    assert [i["url"] for i in res.items] == ["https://www.rockstargames.com/newswire/article/1/gta-vi-online",
                                             "https://www.rockstargames.com/newswire/article/2/rdo"]


def test_failing_source_reports_error_instead_of_raising():
    src = make_source(id="r", url="https://www.reddit.com/r/GTA6/new/.rss", retries=0)
    res = run_source(src, lambda req: httpx.Response(403))
    assert res.items == [] and "HTTP 403" in res.error


def test_html_that_is_not_a_feed_is_an_error():
    src = make_source(id="r", url="https://example.com/feed", retries=0)
    res = run_source(src, lambda req: httpx.Response(200, text="<html><body>blocked</body></html>"))
    assert res.items == [] and res.error


def test_helpers():
    assert find_persisted_hash(f'"{H2}" ... NewswireList:"{H1}"', "NewswireList") == H1
    found = walk_posts({"a": [{"title": "X post", "url": "/newswire/article/9/x"}, {"title": "nav", "url": "/games"}]},
                       "https://www.rockstargames.com", "/newswire/article/")
    assert len(found) == 1


def test_bing_publisher_name_is_used():
    bing = b"""<?xml version="1.0"?><rss version="2.0" xmlns:News="https://www.bing.com/news/search?q=x&amp;format=rss">
<channel><title>Bing</title><item><title>GTA 6 roleplay depth outlined</title>
<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;url=https%3a%2f%2fwww.insider-gaming.com%2fgta-6-rp%2f</link>
<News:Source>Insider Gaming</News:Source></item></channel></rss>"""
    items, _ = parse_rss(bing)
    assert items[0]["source_title"] == "Insider Gaming"


def test_reddit_429_waits_retry_after_then_succeeds(monkeypatch):
    import radar.fetch as fetch
    waits = []

    async def fake_sleep(sec):
        waits.append(sec)
    monkeypatch.setattr(fetch.asyncio, "sleep", fake_sleep)
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"x-ratelimit-reset": "12"})
        return httpx.Response(200, content=RSS)

    src = make_source(id="reddit_rp", url="https://www.reddit.com/r/FiveM+gtaonline/new/.rss",
                      retries=2, extra={"start_delay": 20})
    res = run_source(src, handler)
    assert res.error is None and len(res.items) == 1
    assert waits == [20.0, 12.0]
