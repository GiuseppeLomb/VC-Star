"""GTA6 RP Radar pipeline: collect -> normalise -> classify -> dedup -> store -> notify.

    python -m radar.main             # real run (used by GitHub Actions)
    python -m radar.main --dry-run   # shows counts and would-be pushes; writes/sends nothing
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Callable

from . import store
from .classify import OFICIAL, build_item, classify, load_rules
from .dedup import dedup
from .fetch import FetchResult, run_fetch
from .notify import (
    DryRunNotifier,
    Message,
    Notifier,
    is_fresh,
    pages_url,
    plan_messages,
    push_priority,
)
from .sources import ConfigError, load_sources
from .util import iso, parse_iso, utcnow

ROOT = Path(__file__).resolve().parent.parent
PENDING_WINDOW = timedelta(hours=6)


class Paths:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.sources = self.root / "config" / "sources.yml"
        self.keywords = self.root / "config" / "keywords.yml"
        self.credible = self.root / "config" / "credible.yml"
        self.seen = self.root / "data" / "seen.json"
        self.news = self.root / "docs" / "data" / "news.json"
        self.health = self.root / "docs" / "data" / "health.json"


def run(root: Path = ROOT, *, dry_run: bool = False,
        fetcher: Callable[[list, dict], list[FetchResult]] = run_fetch,
        notifier: Notifier | None = None, now=None, only: set[str] | None = None,
        out: Callable[[str], None] = print) -> dict:
    paths = Paths(root)
    now = now or utcnow()
    sources = load_sources(paths.sources)
    rules = load_rules(paths.keywords, paths.credible)
    if notifier is None:
        notifier = DryRunNotifier() if dry_run else Notifier.from_env()

    seen = store.load_json(paths.seen, None) or store.empty_seen()
    seen.setdefault("items", {})
    seen.setdefault("cache", {})
    news_prev = store.load_json(paths.news, None)
    health_prev = store.load_json(paths.health, None)
    existing = list((news_prev or {}).get("items") or [])
    # "First run" lasts until something was actually indexed (all sources may fail at first).
    first_run = not seen.get("initialized_at")

    active = [s for s in sources if s.enabled and (not only or s.id in only)]
    disabled = [s for s in sources if not s.enabled]
    results = fetcher(active, seen["cache"])

    # ---- normalise + classify new raw items
    src_by_id = {s.id: s for s in sources}
    fresh_items: list[dict] = []
    report = []
    for r in results:
        kept = 0
        for raw in r.items:
            item = build_item(raw, r.source, now)
            if item is None:
                continue
            item = classify(item, r.source, rules)
            if item is None:
                continue
            item["priority"] = push_priority(item, rules, r.source)
            kept += 1
            fresh_items.append(item)
        report.append((r, kept))

    # ---- re-apply current rules to stored items (edits to the YAML take effect)
    rescored = []
    for it in existing:
        src = src_by_id.get(it.get("source_id"))
        if src is None:
            rescored.append(it)
            continue
        again = classify(dict(it), src, rules)
        if again is not None:
            again["priority"] = push_priority(again, rules, src)
            rescored.append(again)

    existing_ids = {it["id"] for it in existing}
    combined = dedup(rescored + fresh_items)
    selected = store.select_items(combined, now)
    new_items = [it for it in selected if it["id"] not in existing_ids and it["id"] not in seen["items"]]

    # ---- seen state + notification candidates
    max_age = int(rules.notify.get("max_age_hours", 48))
    for it in new_items:
        prio = it.get("priority")
        seen["items"][it["id"]] = {
            "t": it["title"][:140],
            "first_seen": iso(now),
            "p": prio,
            "pending": bool(prio) and is_fresh(it, now, max_age),
        }

    sent: list[Message] = []
    note = ""
    if first_run:
        for v in seen["items"].values():
            v["pending"] = False
        if selected:
            seen["initialized_at"] = iso(now)
        note = "1.ª execução: histórico marcado como visto, sem pushes."
        if notifier.enabled and not seen.get("push_ready"):
            sent += _bootstrap(notifier, len(selected), seen)
    elif not notifier.enabled:
        waiting = sum(1 for v in seen["items"].values() if v.get("pending"))
        note = f"Sem canal de push (NTFY_TOPIC / DISCORD_WEBHOOK_RADAR): {waiting} push(es) em espera."
    elif not seen.get("push_ready"):
        for v in seen["items"].values():
            v["pending"] = False
        note = "Tópico ntfy configurado agora: push de teste enviado, histórico silenciado."
        sent += _bootstrap(notifier, len(selected), seen)
    else:
        by_id = {it["id"]: it for it in selected}
        candidates = []
        for iid, v in seen["items"].items():
            if not v.get("pending"):
                continue
            it = by_id.get(iid)
            first_seen = parse_iso(v.get("first_seen"))
            if it is None or not is_fresh(it, now, max_age) or (first_seen and now - first_seen > PENDING_WINDOW):
                v["pending"] = False  # expired or deduplicated away
                continue
            candidates.append((it, int(v.get("p") or 0)))
        for msg in plan_messages(candidates, int(rules.notify.get("max_per_run", 10))):
            if notifier.send(msg):
                sent.append(msg)
                for iid in msg.item_ids:
                    if iid in seen["items"]:
                        seen["items"][iid]["pending"] = False
                        seen["items"][iid]["notified"] = iso(now)

    store.prune_seen(seen, now)

    # ---- health
    health = store.update_health(health_prev or {}, results, now)
    store.add_disabled(health, disabled)
    if only and health_prev:
        for sid, entry in (health_prev.get("sources") or {}).items():
            health["sources"].setdefault(sid, entry)

    officials = sum(1 for it in new_items if it["tag"] == OFICIAL)
    commit_message = f"radar: +{len(new_items)} itens ({officials} oficiais)"

    changed = {"news": False, "seen": False, "health": False}
    if not dry_run:
        changed["news"] = store.save_news(paths.news, selected, now, news_prev)
        changed["seen"] = store.write_if_changed(paths.seen, seen)
        changed["health"] = store.save_health(paths.health, health, health_prev, now, force=changed["news"])
        if not new_items and (changed["health"] or changed["seen"]) and not changed["news"]:
            commit_message = "radar: heartbeat"

    _print_report(out, report, new_items, sent, note, dry_run, selected, rules)
    _github_output(commit_message)
    return {
        "first_run": first_run,
        "new": new_items,
        "selected": selected,
        "sent": sent,
        "changed": changed,
        "commit_message": commit_message,
        "health": health,
        "seen": seen,
    }


def _bootstrap(notifier: Notifier, count: int, seen: dict) -> list[Message]:
    msg = Message(
        title=f"✅ Radar ativo — {count} itens indexados",
        body="A partir de agora recebes aqui os anúncios importantes sobre GTA 6 RP / Online.",
        priority=3, tags=["white_check_mark"], click=pages_url(),
    )
    if notifier.send(msg):
        seen["push_ready"] = True
        return [msg]
    return []


def _print_report(out, report, new_items, sent, note, dry_run, selected, rules) -> None:
    out("")
    out(f"{'fonte':<22} {'estado':<6} {'lidos':>5} {'aceites':>7}  detalhe")
    out("-" * 78)
    for r, kept in report:
        state = "ERRO" if r.error else "ok"
        detail = r.error or (r.resolved_url or "")
        out(f"{r.source.id:<22} {state:<6} {len(r.items):>5} {kept:>7}  {detail[:60]}")
    out("-" * 78)
    out(f"itens no radar: {len(selected)} | novos nesta execução: {len(new_items)}")
    if note:
        out(note)
    label = "SERIA ENVIADO" if dry_run else "enviado"
    for m in sent:
        out(f"  push p{m.priority} [{label}]: {m.title}")
    if dry_run:
        hot = [(it.get("priority"), it) for it in selected]
        hot = [(p, it) for p, it in hot if p]
        hot.sort(key=lambda x: (-x[0], x[1].get("published") or ""))
        if hot:
            out("itens que dariam push se fossem novos:")
            for p, it in hot[:15]:
                out(f"  p{p} {it['tag']:<8} {it['score']:>3}  {it['title'][:90]}")
    out("")


def _github_output(commit_message: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"commit_message={commit_message}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GTA6 RP Radar")
    parser.add_argument("--dry-run", action="store_true", help="não grava nem envia nada")
    parser.add_argument("--only", help="ids de fontes separados por vírgulas")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        run(Path(args.root), dry_run=args.dry_run,
            only=set(args.only.split(",")) if args.only else None)
    except ConfigError as exc:
        print(f"Erro de configuração: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
