"""Discord como código: cargos, categorias, canais e permissões a partir de server.yml.

    python -m discord_setup.build --plan      # sem rede: o que seria criado num servidor vazio
    python -m discord_setup.build --dry-run   # lê o servidor real e mostra as diferenças (não altera nada)
    python -m discord_setup.build             # aplica

Precisa de DISCORD_BOT_TOKEN e DISCORD_GUILD_ID no ambiente (Secrets do GitHub).
Nunca apaga nada: o que existir no Discord e não estiver no YAML é só listado.
O token nunca é escrito nos logs.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

API = "https://discord.com/api/v10"
CONFIG = Path(__file__).resolve().parent / "server.yml"
USER_AGENT = "DiscordBot (https://github.com/GiuseppeLomb/VC-Star, 1.0)"

PERMISSIONS = {
    "create_instant_invite": 1 << 0, "kick_members": 1 << 1, "ban_members": 1 << 2,
    "administrator": 1 << 3, "manage_channels": 1 << 4, "manage_guild": 1 << 5,
    "add_reactions": 1 << 6, "view_audit_log": 1 << 7, "priority_speaker": 1 << 8,
    "stream": 1 << 9, "view_channel": 1 << 10, "send_messages": 1 << 11,
    "send_tts_messages": 1 << 12, "manage_messages": 1 << 13, "embed_links": 1 << 14,
    "attach_files": 1 << 15, "read_message_history": 1 << 16, "mention_everyone": 1 << 17,
    "use_external_emojis": 1 << 18, "connect": 1 << 20, "speak": 1 << 21,
    "mute_members": 1 << 22, "deafen_members": 1 << 23, "move_members": 1 << 24,
    "use_vad": 1 << 25, "change_nickname": 1 << 26, "manage_nicknames": 1 << 27,
    "manage_roles": 1 << 28, "manage_webhooks": 1 << 29, "manage_guild_expressions": 1 << 30,
    "use_application_commands": 1 << 31, "manage_events": 1 << 33, "manage_threads": 1 << 34,
    "create_public_threads": 1 << 35, "send_messages_in_threads": 1 << 38,
    "moderate_members": 1 << 40,
}
P = PERMISSIONS
CHANNEL_TYPES = {"text": 0, "voice": 2, "category": 4}
TEXT_VIEW = P["view_channel"] | P["read_message_history"]
TEXT_WRITE = (P["send_messages"] | P["send_messages_in_threads"] | P["create_public_threads"]
              | P["add_reactions"] | P["attach_files"] | P["embed_links"])
VOICE_VIEW = P["view_channel"] | P["connect"]
VOICE_WRITE = P["speak"] | P["stream"] | P["use_vad"]


class ConfigError(ValueError):
    pass


class DiscordError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- config
def load_config(path: str | Path = CONFIG) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    roles = cfg.get("roles") or []
    keys = [r.get("key") for r in roles]
    if not roles or None in keys or len(keys) != len(set(keys)):
        raise ConfigError("cada cargo precisa de uma 'key' única")
    names = [r.get("name") for r in roles]
    if None in names or len(names) != len(set(names)):
        raise ConfigError("cada cargo precisa de um 'name' único")
    for r in roles:
        for perm in r.get("permissions") or []:
            if perm not in PERMISSIONS:
                raise ConfigError(f"cargo {r['key']}: permissão desconhecida '{perm}'")
        if r.get("color") and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(r["color"])):
            raise ConfigError(f"cargo {r['key']}: cor tem de ser #RRGGBB")
    cfg["groups"] = cfg.get("groups") or {}
    for g, members in cfg["groups"].items():
        if g in keys:
            raise ConfigError(f"grupo '{g}' tem o mesmo nome de um cargo")
        for m in members:
            if m not in keys:
                raise ConfigError(f"grupo {g}: cargo desconhecido '{m}'")
    cfg["members"] = cfg.get("members") or {}
    for uid, rkeys in cfg["members"].items():
        if not re.fullmatch(r"\d{15,21}", str(uid)):
            raise ConfigError(f"members: '{uid}' não é um ID de utilizador do Discord")
        for k in rkeys:
            if k not in keys:
                raise ConfigError(f"members {uid}: cargo desconhecido '{k}'")
    seen_cats = set()
    for cat in cfg.get("categories") or []:
        if cat.get("name") in seen_cats:
            raise ConfigError(f"categoria repetida: {cat.get('name')}")
        seen_cats.add(cat.get("name"))
        expand(cat.get("visible_to") or [], cfg)
        expand(cat.get("write") or [], cfg)
        seen = set()
        for ch in cat.get("channels") or []:
            ctype = ch.get("type", "text")
            if ctype not in ("text", "voice"):
                raise ConfigError(f"canal {ch.get('name')}: type tem de ser text ou voice")
            key = (channel_key(ch["name"], CHANNEL_TYPES[ctype]), ctype)
            if key in seen:
                raise ConfigError(f"canal repetido em {cat['name']}: {ch['name']}")
            seen.add(key)
            expand(ch.get("visible_to") or [], cfg)
            expand(ch.get("write") or [], cfg)
    return cfg


def expand(refs, cfg) -> set[str]:
    keys = {r["key"] for r in cfg["roles"]}
    out: set[str] = set()
    for ref in refs or []:
        if ref == "everyone":
            out.add("everyone")
        elif ref in cfg.get("groups", {}):
            out.update(cfg["groups"][ref])
        elif ref in keys:
            out.add(ref)
        else:
            raise ConfigError(f"'{ref}' não é um cargo, grupo nem 'everyone'")
    return out


def perm_bits(names) -> int:
    value = 0
    for n in names or []:
        value |= PERMISSIONS[n]
    return value


def color_value(hex_color) -> int:
    return int(str(hex_color).lstrip("#"), 16) if hex_color else 0


def channel_key(name: str, ctype: int) -> str:
    """Discord stores text channel names lowercased with dashes."""
    name = (name or "").strip()
    return re.sub(r"\s+", "-", name.lower()) if ctype == 0 else name


def overwrites(visible: set[str], writers: set[str], kind: str, role_ids: dict, everyone_id: str) -> list[dict]:
    if kind == "voice":
        view, write = VOICE_VIEW | P["read_message_history"], VOICE_WRITE
    elif kind == "category":
        view, write = TEXT_VIEW | VOICE_VIEW, TEXT_WRITE | VOICE_WRITE
    else:
        view, write = TEXT_VIEW, TEXT_WRITE
    acc: dict[str, list[int]] = {}

    def add(target, allow=0, deny=0):
        cur = acc.setdefault(str(target), [0, 0])
        cur[0] |= allow
        cur[1] |= deny

    if "everyone" in visible:
        add(everyone_id, allow=view)
    else:
        add(everyone_id, deny=P["view_channel"])
    if "everyone" in writers:
        add(everyone_id, allow=write)
    else:
        add(everyone_id, deny=write)
    for k in sorted(visible - {"everyone"}):
        add(role_ids[k], allow=view)
    for k in sorted(writers - {"everyone"}):
        add(role_ids[k], allow=view | write)
    out = []
    for target, (allow, deny) in acc.items():
        out.append({"id": target, "type": 0, "allow": str(allow), "deny": str(deny & ~allow)})
    return sorted(out, key=lambda o: o["id"])


def _ow_set(ows) -> set:
    return {(str(o["id"]), int(o.get("type", 0)), str(o.get("allow", "0")), str(o.get("deny", "0"))) for o in ows or []}


# --------------------------------------------------------------------------- transports
class DiscordAPI:
    def __init__(self, token: str, client: httpx.Client | None = None, sleep=time.sleep):
        self.client = client or httpx.Client(base_url=API, timeout=20)
        self.headers = {"Authorization": f"Bot {token}", "User-Agent": USER_AGENT}
        self.sleep = sleep

    def call(self, method: str, path: str, json=None):
        for _ in range(8):
            r = self.client.request(method, API + path if not str(self.client.base_url) else path,
                                    json=json, headers=self.headers)
            if r.status_code == 429:
                try:
                    wait = float(r.json().get("retry_after", 1))
                except ValueError:
                    wait = float(r.headers.get("Retry-After", 1))
                self.sleep(min(wait, 30) + 0.25)
                continue
            if r.status_code >= 400:
                raise DiscordError(f"{method} {path} → HTTP {r.status_code}: {r.text[:200]}", r.status_code)
            return r.json() if r.content else None
        raise DiscordError(f"{method} {path}: rate limit persistente", 429)


class MemoryDiscord:
    """In-memory guild with the same REST surface we use. Powers --plan and the tests."""

    def __init__(self, guild_id: str = "100000000000000001", bot_id: str = "200000000000000002",
                 name: str = "Servidor novo"):
        self.gid, self.bot_id, self.name = guild_id, bot_id, name
        self._next = 300000000000000000
        self.roles = [
            {"id": guild_id, "name": "@everyone", "position": 0, "permissions": "0", "color": 0,
             "hoist": False, "mentionable": False, "managed": False},
            {"id": "200000000000000099", "name": "VC STAR Bot", "position": 1, "permissions": str(P["administrator"]),
             "color": 0, "hoist": False, "mentionable": False, "managed": True},
        ]
        self.channels: list[dict] = []
        self.members = {bot_id: {"user": {"id": bot_id}, "roles": ["200000000000000099"]}}
        self.writes: list[tuple[str, str]] = []

    def _id(self) -> str:
        self._next += 1
        return str(self._next)

    def call(self, method: str, path: str, json=None):
        if method != "GET":
            self.writes.append((method, path))
        g = self.gid
        if path == "/users/@me":
            return {"id": self.bot_id}
        if path == f"/guilds/{g}":
            if method == "PATCH":
                self.name = json["name"]
            return {"id": g, "name": self.name}
        if path == f"/guilds/{g}/roles":
            if method == "GET":
                return [dict(r) for r in self.roles]
            if method == "POST":
                for r in self.roles:
                    if r["position"] >= 1:
                        r["position"] += 1
                role = {"id": self._id(), "position": 1, "managed": False, "color": 0,
                        "hoist": False, "mentionable": False, "permissions": "0", **json}
                self.roles.append(role)
                return dict(role)
            if method == "PATCH":
                for item in json:
                    self._role(item["id"])["position"] = item["position"]
                return [dict(r) for r in self.roles]
        m = re.fullmatch(rf"/guilds/{g}/roles/(\d+)", path)
        if m and method == "PATCH":
            self._role(m.group(1)).update(json)
            return dict(self._role(m.group(1)))
        m = re.fullmatch(rf"/guilds/{g}/members/(\d+)", path)
        if m:
            if m.group(1) not in self.members:
                raise DiscordError("Unknown Member", 404)
            return self.members[m.group(1)]
        m = re.fullmatch(rf"/guilds/{g}/members/(\d+)/roles/(\d+)", path)
        if m and method == "PUT":
            self.members[m.group(1)]["roles"].append(m.group(2))
            return None
        if path == f"/guilds/{g}/channels":
            if method == "GET":
                return [dict(c) for c in self.channels]
            if method == "POST":
                siblings = [c for c in self.channels if c.get("parent_id") == json.get("parent_id")]
                ch = {"id": self._id(), "position": len(siblings), "topic": None, "parent_id": None,
                      "permission_overwrites": [], **json}
                self.channels.append(ch)
                return dict(ch)
            if method == "PATCH":
                for item in json:
                    self._channel(item["id"])["position"] = item["position"]
                return None
        m = re.fullmatch(r"/channels/(\d+)", path)
        if m and method == "PATCH":
            self._channel(m.group(1)).update(json)
            return dict(self._channel(m.group(1)))
        raise DiscordError(f"rota não simulada: {method} {path}", 404)

    def _role(self, rid):
        return next(r for r in self.roles if r["id"] == str(rid))

    def _channel(self, cid):
        return next(c for c in self.channels if c["id"] == str(cid))


# --------------------------------------------------------------------------- build
@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)
    unchanged: int = 0

    def lines(self) -> list[str]:
        out = [f"+ {x}" for x in self.created] + [f"~ {x}" for x in self.updated]
        out += [f"! {x}" for x in self.warnings]
        out += [f"? no Discord mas não no YAML (não apagado): {x}" for x in self.extras]
        out.append(f"= {len(self.created)} a criar, {len(self.updated)} a atualizar, {self.unchanged} sem alterações")
        return out


def build(cfg: dict, api, guild_id: str, dry_run: bool = False) -> Report:
    rep = Report()
    gid = str(guild_id)

    # ---- server name
    want_name = (cfg.get("server") or {}).get("name")
    if want_name:
        guild = api.call("GET", f"/guilds/{gid}")
        if guild.get("name") != want_name:
            rep.updated.append(f"nome do servidor: «{guild.get('name')}» → «{want_name}»")
            if not dry_run:
                api.call("PATCH", f"/guilds/{gid}", json={"name": want_name})
        else:
            rep.unchanged += 1

    # ---- roles
    existing = api.call("GET", f"/guilds/{gid}/roles")
    by_name = {r["name"]: r for r in existing}
    role_ids: dict[str, str] = {}
    for spec in cfg["roles"]:
        want = {
            "name": spec["name"],
            "permissions": str(perm_bits(spec.get("permissions"))),
            "color": color_value(spec.get("color")),
            "hoist": bool(spec.get("hoist", False)),
            "mentionable": bool(spec.get("mentionable", False)),
        }
        cur = by_name.get(spec["name"])
        if cur is None:
            rep.created.append(f"cargo {spec['name']}")
            role_ids[spec["key"]] = f"<novo:{spec['key']}>"
            if not dry_run:
                role_ids[spec["key"]] = str(api.call("POST", f"/guilds/{gid}/roles", json=want)["id"])
            continue
        role_ids[spec["key"]] = str(cur["id"])
        diff = {k: v for k, v in want.items() if str(cur.get(k)) != str(v)}
        if diff:
            rep.updated.append(f"cargo {spec['name']} ({', '.join(sorted(diff))})")
            if not dry_run:
                api.call("PATCH", f"/guilds/{gid}/roles/{cur['id']}", json=diff)
        else:
            rep.unchanged += 1

    # ---- role order: YAML order, right below the bot's highest role
    me = api.call("GET", "/users/@me")
    bot_member = api.call("GET", f"/guilds/{gid}/members/{me['id']}")
    roles_now = {r["id"]: r for r in api.call("GET", f"/guilds/{gid}/roles")}
    bot_top = max((roles_now[r]["position"] for r in bot_member.get("roles", []) if r in roles_now), default=0)
    real = [(spec, role_ids[spec["key"]]) for spec in cfg["roles"] if role_ids[spec["key"]] in roles_now]
    above = [spec["name"] for spec, rid in real if roles_now[rid]["position"] >= bot_top]
    if above:
        rep.warnings.append("o cargo do bot tem de ficar no TOPO da lista (Definições do servidor → Cargos → arrasta-o "
                            f"para cima). Cargos acima do bot que não posso gerir: {', '.join(above)}")
    current_order = [rid for _, rid in sorted(real, key=lambda x: -roles_now[x[1]]["position"])]
    wanted_order = [rid for _, rid in real]
    if current_order != wanted_order and not above:
        rep.updated.append("ordem dos cargos")
        if not dry_run:
            positions = [{"id": rid, "position": max(1, bot_top - 1 - i)} for i, rid in enumerate(wanted_order)]
            api.call("PATCH", f"/guilds/{gid}/roles", json=positions)

    # ---- categories and channels
    channels = api.call("GET", f"/guilds/{gid}/channels")
    used_ids: set[str] = set()

    def find(name, ctype, parent_id=None):
        key = channel_key(name, ctype)
        matches = [c for c in channels if c["type"] == ctype and channel_key(c["name"], ctype) == key
                   and c["id"] not in used_ids]
        same_parent = [c for c in matches if str(c.get("parent_id")) == str(parent_id)]
        return (same_parent or matches or [None])[0]

    order_cats, order_children = [], {}
    for cat in cfg.get("categories") or []:
        vis, wr = expand(cat.get("visible_to"), cfg), expand(cat.get("write"), cfg)
        ows = overwrites(vis, wr, "category", role_ids, gid)
        cur = find(cat["name"], 4)
        if cur is None:
            rep.created.append(f"categoria {cat['name']}")
            cat_id = f"<nova:{cat['name']}>"
            if not dry_run:
                cat_id = str(api.call("POST", f"/guilds/{gid}/channels",
                                      json={"name": cat["name"], "type": 4, "permission_overwrites": ows})["id"])
        else:
            cat_id = str(cur["id"])
            used_ids.add(cat_id)
            if _ow_set(cur.get("permission_overwrites")) != _ow_set(ows):
                rep.updated.append(f"categoria {cat['name']} (permissões)")
                if not dry_run:
                    api.call("PATCH", f"/channels/{cat_id}", json={"permission_overwrites": ows})
            else:
                rep.unchanged += 1
        order_cats.append((cat_id, cur))
        children = order_children.setdefault(cat_id, [])

        for ch in cat.get("channels") or []:
            kind = ch.get("type", "text")
            ctype = CHANNEL_TYPES[kind]
            cvis = expand(ch["visible_to"], cfg) if "visible_to" in ch else vis
            cwr = expand(ch["write"], cfg) if "write" in ch else wr
            cows = overwrites(cvis, cwr, kind, role_ids, gid)
            label = f"#{channel_key(ch['name'], ctype)}" if ctype == 0 else ch["name"]
            existing_ch = find(ch["name"], ctype, cat_id)
            want = {"permission_overwrites": cows, "parent_id": cat_id}
            if ctype == 0:
                want["topic"] = ch.get("topic") or None
            if existing_ch is None:
                rep.created.append(f"canal {label} em {cat['name']}")
                ch_id = f"<novo:{label}>"
                if not dry_run:
                    ch_id = str(api.call("POST", f"/guilds/{gid}/channels",
                                         json={"name": ch["name"], "type": ctype, **want})["id"])
                children.append((ch_id, None))
                continue
            ch_id = str(existing_ch["id"])
            used_ids.add(ch_id)
            diff = {}
            if _ow_set(existing_ch.get("permission_overwrites")) != _ow_set(cows):
                diff["permission_overwrites"] = cows
            if str(existing_ch.get("parent_id")) != str(cat_id):
                diff["parent_id"] = cat_id
            if ctype == 0 and (existing_ch.get("topic") or None) != want["topic"]:
                diff["topic"] = want["topic"]
            if diff:
                rep.updated.append(f"canal {label} ({', '.join(sorted(diff))})")
                if not dry_run:
                    api.call("PATCH", f"/channels/{ch_id}", json=diff)
            else:
                rep.unchanged += 1
            children.append((ch_id, existing_ch))

    # ---- channel order (categories in YAML order, channels in YAML order inside each)
    if not dry_run:
        fresh = {c["id"]: c for c in api.call("GET", f"/guilds/{gid}/channels")}
        moves = []
        for i, (cid, _) in enumerate(order_cats):
            if cid in fresh and fresh[cid].get("position") != i:
                moves.append({"id": cid, "position": i})
            for j, (chid, _) in enumerate(order_children.get(cid, [])):
                if chid in fresh and fresh[chid].get("position") != j:
                    moves.append({"id": chid, "position": j})
        if moves:
            rep.updated.append(f"ordem de {len(moves)} canais/categorias")
            api.call("PATCH", f"/guilds/{gid}/channels", json=moves)

    # ---- staff members → roles
    for uid, keys in (cfg.get("members") or {}).items():
        try:
            member = api.call("GET", f"/guilds/{gid}/members/{uid}")
        except DiscordError as exc:
            if exc.status == 404:
                rep.warnings.append(f"membro {uid} ainda não entrou no servidor")
                continue
            raise
        for k in keys:
            rid = role_ids[k]
            if rid in member.get("roles", []):
                rep.unchanged += 1
                continue
            rep.created.append(f"cargo {k} → membro {uid}")
            if not dry_run and not rid.startswith("<"):
                try:
                    api.call("PUT", f"/guilds/{gid}/members/{uid}/roles/{rid}")
                except DiscordError as exc:
                    rep.warnings.append(f"não consegui dar {k} a {uid}: {exc}")

    # ---- report (never delete) what exists in Discord but not in the YAML
    yaml_roles = {r["name"] for r in cfg["roles"]}
    for r in existing:
        if r["name"] != "@everyone" and not r.get("managed") and r["name"] not in yaml_roles:
            rep.extras.append(f"cargo {r['name']}")
    for c in channels:
        if c["id"] not in used_ids:
            rep.extras.append(f"canal {c['name']}")
    return rep


# --------------------------------------------------------------------------- cli
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Constrói o Discord VC STAR a partir de server.yml")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="sem rede: simula num servidor vazio")
    mode.add_argument("--dry-run", action="store_true", help="lê o servidor real, não altera nada")
    parser.add_argument("--config", default=str(CONFIG))
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except (ConfigError, KeyError, TypeError) as exc:
        print(f"Erro no server.yml: {exc}", file=sys.stderr)
        return 2

    if args.plan:
        mem = MemoryDiscord()
        rep = build(cfg, mem, mem.gid)
        print("PLANO (servidor vazio simulado):")
    else:
        token, gid = os.environ.get("DISCORD_BOT_TOKEN"), os.environ.get("DISCORD_GUILD_ID")
        if not token or not gid:
            print("Faltam os Secrets DISCORD_BOT_TOKEN e/ou DISCORD_GUILD_ID.", file=sys.stderr)
            return 2
        try:
            rep = build(cfg, DiscordAPI(token), gid, dry_run=args.dry_run)
        except DiscordError as exc:
            print(f"Erro do Discord: {exc}", file=sys.stderr)
            if exc.status in (401, 403):
                print("Verifica o token, se o bot está no servidor e se tem a permissão Administrador.", file=sys.stderr)
            return 1
        print("DRY-RUN (nada foi alterado):" if args.dry_run else "APLICADO:")
    for line in rep.lines():
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
