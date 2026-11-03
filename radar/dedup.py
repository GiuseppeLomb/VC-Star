"""Deduplication: first by id (normalised URL), then by title similarity."""
from __future__ import annotations

import re
from datetime import timedelta

from rapidfuzz import fuzz

from .classify import TAG_RANK
from .util import parse_iso

SIMILARITY = 88
WINDOW = timedelta(hours=72)
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def _norm_title(title: str) -> str:
    return " ".join(_NON_WORD.sub(" ", (title or "").lower()).split())


def similar_titles(a: str, b: str, threshold: int = SIMILARITY) -> bool:
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return False
    ta, tb = na.split(), nb.split()
    short, long_ = sorted((len(ta), len(tb)))
    # token_set_ratio scores 100 when one title is a subset of the other;
    # guard against very short titles swallowing long, different ones.
    if short < 4 or short / long_ < 0.5:
        return na == nb
    return fuzz.token_set_ratio(na, nb) >= threshold


def _keeper_key(item: dict):
    """Highest tier first, then the oldest publication."""
    return (-TAG_RANK.get(item.get("tag"), 0), item.get("published") or "", item.get("fetched") or "")


def _merge_into(keeper: dict, dup: dict) -> None:
    also = list(keeper.get("also_on") or [])
    for dom in [dup.get("domain"), *(dup.get("also_on") or [])]:
        if dom and dom != keeper.get("domain") and dom not in also:
            also.append(dom)
    keeper["also_on"] = also


def dedup(items: list[dict], threshold: int = SIMILARITY, window: timedelta = WINDOW) -> list[dict]:
    ordered = sorted(items, key=_keeper_key)

    # 1) same id -> keep the best one
    by_id: dict[str, dict] = {}
    for it in ordered:
        if it["id"] in by_id:
            _merge_into(by_id[it["id"]], it)
        else:
            by_id[it["id"]] = it

    # 2) near-identical titles within the time window
    kept: list[dict] = []
    for it in by_id.values():
        when = parse_iso(it.get("published"))
        for k in kept:
            kwhen = parse_iso(k.get("published"))
            if when and kwhen and abs(when - kwhen) > window:
                continue
            if similar_titles(it["title"], k["title"], threshold):
                _merge_into(k, it)
                break
        else:
            kept.append(it)
    return kept
