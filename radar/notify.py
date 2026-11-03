"""Push notifications via ntfy.sh (free, no account). Optional Telegram mirror."""
from __future__ import annotations

import logging
import os
from urllib.parse import quote
from dataclasses import dataclass, field
from datetime import timedelta

import httpx

from .classify import CREDIVEL, LEAKER, OFICIAL, Rules, mentions_gta6
from .util import parse_iso

log = logging.getLogger("radar.notify")

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
TOPIC_LABELS = {
    "rp": "RP", "servidores": "servidores", "creator": "criadores", "online": "Online",
    "pc": "PC", "trailer": "trailer", "data": "data",
}


NO_TRANSLATE = ("youtube.com", "youtu.be", "twitch.tv")


def pt_url(item: dict) -> str:
    """Link that opens the article already translated to Portuguese (Google Translate).

    Portuguese articles and videos open directly.
    """
    url = item.get("url") or ""
    domain = (item.get("domain") or "").lower()
    if (not url.startswith("http") or item.get("lang") == "pt" or domain.endswith((".pt", ".br"))
            or any(domain == d or domain.endswith("." + d) for d in NO_TRANSLATE)):
        return url
    return "https://translate.google.com/translate?sl=auto&tl=pt&hl=pt-PT&u=" + quote(url, safe="")


def pages_url() -> str:
    explicit = os.environ.get("RADAR_PAGES_URL")
    if explicit:
        return explicit
    repo = os.environ.get("GITHUB_REPOSITORY", "GiuseppeLomb/VC-Star")
    owner, _, name = repo.partition("/")
    return f"https://{owner.lower()}.github.io/{name}/"


# --------------------------------------------------------------------------- rules
def push_priority(item: dict, rules: Rules, source=None) -> int | None:
    """5 = OFICIAL + urgent topic, 4 = OFICIAL, 3 = CREDIVEL with high score, None = no push.

    A source with `push_requires_gta6: true` (e.g. Cfx.re, whose posts always say
    "FiveM") only pushes items that actually mention GTA 6.
    """
    cfg = rules.notify
    tag = item.get("tag")
    topics = set(item.get("topics") or [])
    text = f"{item.get('title', '')} {item.get('excerpt', '')}"
    if source is not None and source.opt("push_requires_gta6") and not mentions_gta6(text, rules):
        return None
    if tag == OFICIAL:
        if topics & set(cfg.get("urgent_topics") or []):
            return 5
        if cfg.get("official_requires_match", True) and not topics and not mentions_gta6(text, rules):
            return None
        return 4
    if tag == CREDIVEL and int(item.get("score") or 0) >= int(cfg.get("credible_min_score", 60)):
        return 3
    if tag == LEAKER and int(item.get("score") or 0) >= int(cfg.get("leaker_min_score", 80)):
        return 3
    return None  # RUMOR never pushes


@dataclass
class Message:
    title: str
    body: str
    priority: int
    tags: list[str]
    click: str
    item_ids: list[str] = field(default_factory=list)


def item_message(item: dict, priority: int) -> Message:
    title = item["title"]
    if priority == 5:
        head, tags = f"🚨 OFICIAL: {title}", ["rotating_light"]
    elif priority == 4:
        head, tags = f"🟢 OFICIAL: {title}", ["green_circle"]
    elif item.get("tag") == LEAKER:
        head, tags = f"🟠 LEAKER: {title}", ["orange_circle"]
    else:
        head, tags = f"🟡 CREDÍVEL: {title}", ["yellow_circle"]
    topics = ", ".join(TOPIC_LABELS.get(t, t) for t in item.get("topics") or [])
    meta = " · ".join(x for x in (item.get("source_name"), topics, f"score {item.get('score', 0)}") if x)
    excerpt = (item.get("excerpt") or "")[:200]
    body = meta + (f"\n{excerpt}" if excerpt else "")
    return Message(head[:250], body, priority, tags, pt_url(item), [item["id"]])


def plan_messages(candidates: list[tuple[dict, int]], max_per_run: int = 10) -> list[Message]:
    """At most `max_per_run` pushes. If there are more, the last one is a single summary."""
    ordered = sorted(candidates, key=lambda c: (-c[1], _neg_time(c[0])))  # priority, then newest
    if len(ordered) <= max_per_run:
        return [item_message(it, p) for it, p in ordered]
    head = ordered[: max_per_run - 1]
    rest = ordered[max_per_run - 1:]
    msgs = [item_message(it, p) for it, p in head]
    msgs.append(Message(
        title=f"📡 {len(rest)} novidades — abre o Radar",
        body="Há mais notícias importantes do que o limite de pushes. Vê tudo na app.",
        priority=max(p for _, p in rest),
        tags=["satellite"],
        click=pages_url(),
        item_ids=[it["id"] for it, _ in rest],
    ))
    return msgs


def _neg_time(item: dict) -> float:
    dt = parse_iso(item.get("published"))
    return -dt.timestamp() if dt else 0.0


def is_fresh(item: dict, now, max_age_hours: int) -> bool:
    dt = parse_iso(item.get("published"))
    return dt is None or now - dt <= timedelta(hours=max_age_hours)


# --------------------------------------------------------------------------- transport
class Notifier:
    """ntfy (phone push) + optional Discord webhook (#radar-gta6) + optional Telegram."""

    DISCORD_COLORS = {5: 0xFF2BD6, 4: 0x3DFFA0, 3: 0xFFD84D}

    def __init__(self, topic: str | None = None, telegram_token: str | None = None,
                 telegram_chat: str | None = None, client: httpx.Client | None = None,
                 discord_webhook: str | None = None):
        self.topic = (topic or "").strip() or None
        self.discord_webhook = (discord_webhook or "").strip() or None
        self.telegram_token = telegram_token or None
        self.telegram_chat = telegram_chat or None
        self.client = client or httpx.Client(timeout=15)
        self.sent: list[Message] = []

    @classmethod
    def from_env(cls) -> "Notifier":
        return cls(os.environ.get("NTFY_TOPIC"), os.environ.get("TELEGRAM_BOT_TOKEN"),
                   os.environ.get("TELEGRAM_CHAT_ID"), discord_webhook=os.environ.get("DISCORD_WEBHOOK_RADAR"))

    @property
    def enabled(self) -> bool:
        return bool(self.topic or self.discord_webhook)

    def send(self, msg: Message) -> bool:
        """True if at least one channel (ntfy or Discord) accepted the message."""
        if not self.enabled:
            return False
        ok = False
        if self.topic:
            ok = self._post("ntfy", NTFY_SERVER + "/", {
                "topic": self.topic,
                "title": msg.title,
                "message": msg.body,
                "priority": msg.priority,
                "tags": msg.tags,
                "click": msg.click,
                "actions": [{"action": "view", "label": "Abrir VC STAR", "url": pages_url(), "clear": False}],
            })
        if self.discord_webhook:
            urgent = msg.priority >= 5
            ok = self._post("discord", self.discord_webhook, {
                "username": "VC STAR Radar",
                "content": "@here 🚨 anúncio oficial importante" if urgent else None,
                "allowed_mentions": {"parse": ["everyone"] if urgent else []},
                "embeds": [{
                    "title": msg.title[:256],
                    "url": msg.click if msg.click.startswith("http") else None,
                    "description": msg.body[:2000],
                    "color": self.DISCORD_COLORS.get(msg.priority, 0x8B5CF6),
                }],
            }) or ok
        if ok:
            self.sent.append(msg)
        self._telegram(msg)
        return ok

    def _post(self, name: str, url: str, payload: dict) -> bool:
        for attempt in range(2):
            try:
                r = self.client.post(url, json=payload)
                if r.status_code < 300:
                    return True
                log.warning("%s respondeu %s: %s", name, r.status_code, r.text[:200])
            except httpx.HTTPError as exc:
                log.warning("%s falhou (%s): %s", name, attempt + 1, type(exc).__name__)
        return False

    def _telegram(self, msg: Message) -> None:
        if not (self.telegram_token and self.telegram_chat):
            return
        try:
            self.client.post(
                f"https://api.telegram.org/bot{self.telegram_token}/sendMessage",
                json={"chat_id": self.telegram_chat, "text": f"{msg.title}\n{msg.body}\n{msg.click}",
                      "disable_web_page_preview": False},
            )
        except httpx.HTTPError as exc:
            log.warning("telegram falhou: %s", type(exc).__name__)


class DryRunNotifier(Notifier):
    """Records what would be sent; never touches the network."""

    def __init__(self, topic: str | None = "dry-run"):
        self.topic = topic
        self.discord_webhook = None
        self.telegram_token = self.telegram_chat = None
        self.client = None
        self.sent = []

    def send(self, msg: Message) -> bool:  # noqa: D401
        self.sent.append(msg)
        return True
