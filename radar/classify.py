"""Provenance tags (OFICIAL / CREDIVEL / RUMOR), relevance filter, topics and score.

The tag says WHERE an item came from, never whether it is true.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from .sources import Source
from .util import (
    clamp_published,
    clean_text,
    domain_of,
    domain_matches,
    iso,
    make_excerpt,
    normalize_url,
    strip_source_suffix,
    url_id,
)

OFICIAL, CREDIVEL, RUMOR = "OFICIAL", "CREDIVEL", "RUMOR"
TAG_RANK = {OFICIAL: 3, CREDIVEL: 2, RUMOR: 1}


def term_regex(terms) -> re.Pattern | None:
    parts = []
    for term in terms or ():
        term = str(term).strip().lower()
        if not term:
            continue
        parts.append(re.escape(term).replace(r"\ ", r"[\s\-]+"))
    if not parts:
        return None
    parts.sort(key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)


@dataclass
class KeywordRule:
    topic: str | None
    weight: int
    rx: re.Pattern


@dataclass
class Rules:
    gta6: list[re.Pattern]
    keywords: list[KeywordRule]
    multipliers: dict[str, float]
    max_score: int
    discard: re.Pattern | None
    penalty_weight: int
    penalty: re.Pattern | None
    official_domains: list[str]
    credible_domains: list[str]
    insiders: re.Pattern | None
    notify: dict = field(default_factory=dict)


NOTIFY_DEFAULTS = {
    "urgent_topics": ["rp", "online", "servidores", "creator"],
    "credible_min_score": 60,
    "official_requires_match": True,
    "max_per_run": 10,
    "max_age_hours": 48,
}


def load_rules(keywords_path: str | Path, credible_path: str | Path) -> Rules:
    kw = yaml.safe_load(Path(keywords_path).read_text(encoding="utf-8")) or {}
    cr = yaml.safe_load(Path(credible_path).read_text(encoding="utf-8")) or {}
    keywords = []
    for entry in kw.get("keywords") or []:
        rx = term_regex(entry.get("terms"))
        if rx is not None:
            keywords.append(KeywordRule(entry.get("topic"), int(entry.get("weight", 0)), rx))
    exclude = kw.get("exclude") or {}
    penalty = exclude.get("penalty") or {}
    return Rules(
        gta6=[re.compile(p, re.IGNORECASE) for p in kw.get("gta6_patterns") or [r"\bgta[\s\-]?(6|vi)\b"]],
        keywords=keywords,
        multipliers={OFICIAL: 1.5, CREDIVEL: 1.2, RUMOR: 1.0, **(kw.get("multipliers") or {})},
        max_score=int(kw.get("max_score", 100)),
        discard=term_regex(exclude.get("discard")),
        penalty_weight=int(penalty.get("weight", -30)),
        penalty=term_regex(penalty.get("terms")),
        official_domains=list(cr.get("official_domains") or []),
        credible_domains=list(cr.get("domains") or []),
        insiders=term_regex(cr.get("insiders")),
        notify={**NOTIFY_DEFAULTS, **(kw.get("notify") or {})},
    )


# --------------------------------------------------------------------------- pieces
def mentions_gta6(text: str, rules: Rules) -> bool:
    return any(p.search(text or "") for p in rules.gta6)


def topics_and_points(text: str, rules: Rules) -> tuple[list[str], int]:
    topics: list[str] = []
    points = 0
    for rule in rules.keywords:
        if rule.rx.search(text):
            points += rule.weight
            if rule.topic and rule.topic not in topics:
                topics.append(rule.topic)
    if rules.penalty is not None and rules.penalty.search(text):
        points += rules.penalty_weight
    return topics, points


def tag_for(domain: str, source: Source, title: str, author: str, rules: Rules) -> str:
    if source.tier == "official" or domain_matches(domain, rules.official_domains):
        return OFICIAL
    if source.tier == "credible" or domain_matches(domain, rules.credible_domains):
        return CREDIVEL
    if rules.insiders is not None and rules.insiders.search(f"{title} {author}"):
        return CREDIVEL
    return RUMOR


def score_for(points: int, tag: str, rules: Rules) -> int:
    value = round(points * float(rules.multipliers.get(tag, 1.0)))
    return max(0, min(rules.max_score, value))


# --------------------------------------------------------------------------- pipeline step
def build_item(raw: dict, source: Source, fetched) -> dict | None:
    """Raw parser output -> normalised item (without tag/score yet)."""
    title = strip_source_suffix(raw.get("title") or "", raw.get("source_title"))
    if not title or not raw.get("url"):
        return None
    url = normalize_url(raw["url"])
    domain = domain_of(url)
    if domain in ("news.google.com", "bing.com") and raw.get("source_url"):
        domain = domain_of(raw["source_url"]) or domain
    excerpt = make_excerpt(raw.get("summary") or "")
    # Aggregators repeat "title + publisher" as description: useless as excerpt.
    if excerpt and len(excerpt) <= len(title) + 60 and fuzz.partial_ratio(title.lower(), excerpt.lower()) >= 90:
        excerpt = ""
    return {
        "id": url_id(url),
        "title": clean_text(title)[:300],
        "url": url,
        "source_id": source.id,
        "source_name": (raw.get("source_title") or source.name).strip()[:80],
        "domain": domain,
        "published": iso(clamp_published(raw.get("published"), fetched)),
        "fetched": iso(fetched),
        "excerpt": excerpt,
        "tag": RUMOR,
        "topics": [],
        "score": 0,
        "lang": source.lang,
        "also_on": [],
        "_author": raw.get("author") or "",
    }


def classify(item: dict, source: Source, rules: Rules) -> dict | None:
    """Apply filters, tag, topics and score. Returns None when the item is discarded."""
    text = f"{item['title']} {item.get('excerpt', '')}"
    if rules.discard is not None and rules.discard.search(text):
        return None
    title_filter = source.opt("title_filter")
    if title_filter and not re.search(title_filter, item["title"], re.IGNORECASE):
        return None
    topics, points = topics_and_points(text, rules)
    if source.relevance == "gta6" and not mentions_gta6(text, rules):
        return None
    if source.relevance == "topic" and not topics:
        return None
    tag = tag_for(item["domain"], source, item["title"], item.pop("_author", ""), rules)
    item.pop("_author", None)
    item["tag"] = tag
    item["topics"] = topics
    item["score"] = score_for(points, tag, rules)
    return item
