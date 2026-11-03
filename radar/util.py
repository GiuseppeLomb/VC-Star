"""Small helpers: URL normalisation, text cleaning and time handling."""
from __future__ import annotations

import base64
import calendar
import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

# Query parameters that never change the content of a page.
TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "igshid", "ref", "ref_src", "ref_url",
    "mc_cid", "mc_eid", "_ga", "ocid", "cmpid", "smid", "guccounter", "feature",
}
TRACKING_PREFIXES = ("utm_",)

EXCERPT_MAX = 280


# --------------------------------------------------------------------------- time
def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def struct_to_dt(st) -> datetime | None:
    """feedparser gives time.struct_time in UTC."""
    if not st:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc)
    except (OverflowError, ValueError, TypeError):
        return None


def clamp_published(dt: datetime | None, fetched: datetime) -> datetime:
    """Missing dates become the fetch time; dates in the future are clamped."""
    if dt is None or dt > fetched + timedelta(hours=1):
        return fetched
    return dt


# --------------------------------------------------------------------------- urls
def _unwrap_bing(url: str) -> str:
    parts = urlsplit(url)
    if parts.netloc.endswith("bing.com") and "apiclick" in parts.path:
        target = parse_qs(parts.query).get("url")
        if target:
            return target[0]
    return url


def decode_google_news(url: str) -> str | None:
    """Best-effort offline decode of a Google News article link.

    Old-style ids (CBMi...) embed the publisher URL in base64. Newer ids
    (AU_yqL...) need a network round-trip, so we give up and return None;
    the caller then keeps the Google link and uses the RSS <source> domain.
    """
    m = re.match(r"https?://news\.google\.com/(?:rss/)?articles/([^?/#]+)", url or "")
    if not m:
        return None
    token = m.group(1)
    token += "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(token)
    except (ValueError, TypeError):
        return None
    found = re.search(rb"https?://[\x21-\x7e]+", raw)
    if not found:
        return None
    candidate = found.group(0).decode("ascii", "ignore")
    if "news.google.com" in candidate:
        return None
    return candidate


def resolve_link(url: str) -> str:
    """Unwrap known redirectors (Bing, Google News old-style)."""
    if not url:
        return url
    url = _unwrap_bing(url.strip())
    decoded = decode_google_news(url)
    return decoded or url


def normalize_url(url: str) -> str:
    """Clean URL for display/storage: no tracking params, fragment or trailing slash."""
    if not url:
        return ""
    url = resolve_link(url)
    parts = urlsplit(url)
    scheme = (parts.scheme or "https").lower()
    if scheme == "http":
        scheme = "https"
    netloc = parts.netloc.lower()
    if netloc.endswith(":443") or netloc.endswith(":80"):
        netloc = netloc.rsplit(":", 1)[0]
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PREFIXES)
    ]
    if netloc == "news.google.com":
        query_pairs = []  # ?oc=5, hl=, gl= ... are presentation only
    query = urlencode(sorted(query_pairs))
    path = parts.path or ""
    if len(path) > 1:
        path = path.rstrip("/")
    if path == "/":
        path = ""
    return urlunsplit((scheme, netloc, path, query, ""))


def url_id(url: str) -> str:
    """sha1 of the normalised URL, ignoring scheme and a leading www."""
    norm = normalize_url(url)
    key = re.sub(r"^https?://(www\.)?", "", norm)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def domain_of(url: str) -> str:
    host = urlsplit(url or "").hostname or ""
    host = host.lower()
    for prefix in ("www.", "m.", "amp."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def domain_matches(domain: str, candidates) -> bool:
    domain = (domain or "").lower()
    for cand in candidates or ():
        cand = cand.lower().strip()
        if cand and (domain == cand or domain.endswith("." + cand)):
            return True
    return False


# --------------------------------------------------------------------------- text
_WS = re.compile(r"\s+")
_REDDIT_TAIL = re.compile(r"submitted by\s+/u/\S+.*$", re.IGNORECASE | re.DOTALL)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    if "<" in value and ">" in value:
        value = BeautifulSoup(value, "html.parser").get_text(" ")
    value = html.unescape(value)
    value = _REDDIT_TAIL.sub("", value)
    return _WS.sub(" ", value).strip()


def make_excerpt(text: str, limit: int = EXCERPT_MAX) -> str:
    text = clean_text(text)
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut[limit // 2:]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:-") + "…"


def strip_source_suffix(title: str, source_title: str | None) -> str:
    """Google News titles end with ' - Publisher'."""
    title = clean_text(title)
    if source_title and " - " in title:
        head, _, tail = title.rpartition(" - ")
        a, b = _alnum(tail), _alnum(source_title)
        if head and a and b and (a == b or a in b or b in a):
            return head.strip()
    return title


def _alnum(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())
