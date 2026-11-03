"""Discord-as-code builder, exercised against the in-memory guild (no network)."""
import copy

import httpx
import pytest

from discord_setup.build import (
    CONFIG, P, ConfigError, DiscordAPI, DiscordError, MemoryDiscord, build, load_config, overwrites,
)


@pytest.fixture
def cfg():
    return load_config(CONFIG)


def ow_for(chan, target):
    return next(o for o in chan["permission_overwrites"] if o["id"] == target)


def test_real_config_is_valid(cfg):
    assert len(cfg["roles"]) >= 10 and len(cfg["categories"]) >= 5


def test_first_build_creates_everything_and_second_changes_nothing(cfg):
    mem = MemoryDiscord()
    rep = build(cfg, mem, mem.gid)
    n_channels = sum(len(c["channels"]) for c in cfg["categories"])
    assert len([r for r in mem.roles if not r["managed"] and r["name"] != "@everyone"]) == len(cfg["roles"])
    assert len([c for c in mem.channels if c["type"] == 4]) == len(cfg["categories"])
    assert len([c for c in mem.channels if c["type"] != 4]) == n_channels
    assert mem.name == "VC STAR" and not rep.warnings
    mem.writes.clear()
    rep2 = build(cfg, mem, mem.gid)
    assert mem.writes == [] and rep2.created == [] and rep2.updated == []


def test_roles_are_ordered_like_the_yaml_below_the_bot(cfg):
    mem = MemoryDiscord()
    build(cfg, mem, mem.gid)
    ours = sorted([r for r in mem.roles if r["name"] in {x["name"] for x in cfg["roles"]}], key=lambda r: -r["position"])
    assert [r["name"] for r in ours] == [x["name"] for x in cfg["roles"]]
    bot = next(r for r in mem.roles if r["managed"])
    assert all(r["position"] < bot["position"] for r in ours)


def test_private_staff_channel_permissions(cfg):
    mem = MemoryDiscord()
    build(cfg, mem, mem.gid)
    role = {r["name"]: r["id"] for r in mem.roles}
    fin = next(c for c in mem.channels if c["name"] == "financeiro")
    everyone = ow_for(fin, mem.gid)
    assert int(everyone["deny"]) & P["view_channel"]
    assert int(ow_for(fin, role["💰 Financeiro"])["allow"]) & P["send_messages"]
    assert all(o["id"] != role["🔨 Moderador"] for o in fin["permission_overwrites"])  # moderators can't see finance


def test_read_only_info_channel(cfg):
    mem = MemoryDiscord()
    build(cfg, mem, mem.gid)
    rules = next(c for c in mem.channels if c["name"] == "regras")
    everyone = ow_for(rules, mem.gid)
    assert int(everyone["allow"]) & P["view_channel"]
    assert int(everyone["deny"]) & P["send_messages"]


def test_channel_override_beats_category(cfg):
    mem = MemoryDiscord()
    build(cfg, mem, mem.gid)
    role = {r["name"]: r["id"] for r in mem.roles}
    logs = next(c for c in mem.channels if c["name"] == "logs")
    assert int(ow_for(logs, role["🤖 Bots"])["allow"]) & P["send_messages"]
    assert not int(ow_for(logs, role["⭐ Staff"])["allow"]) & P["send_messages"]


def test_manual_changes_are_repaired_and_extras_never_deleted(cfg):
    mem = MemoryDiscord()
    build(cfg, mem, mem.gid)
    regras = next(c for c in mem.channels if c["name"] == "regras")
    regras["permission_overwrites"] = []          # someone broke it by hand
    mem.channels.append({"id": "999", "name": "canal-manual", "type": 0, "parent_id": None,
                         "position": 0, "permission_overwrites": []})
    rep = build(cfg, mem, mem.gid)
    assert any("#regras" in u for u in rep.updated)
    assert "canal canal-manual" in rep.extras
    assert any(c["name"] == "canal-manual" for c in mem.channels)


def test_dry_run_writes_nothing(cfg):
    mem = MemoryDiscord()
    rep = build(cfg, mem, mem.gid, dry_run=True)
    assert mem.writes == [] and len(rep.created) > 50


def test_staff_members_get_their_roles(cfg):
    cfg = copy.deepcopy(cfg)
    cfg["members"] = {"300000000000000777": ["moderador", "staff"], "300000000000000888": ["fundador"]}
    mem = MemoryDiscord()
    mem.members["300000000000000777"] = {"user": {"id": "300000000000000777"}, "roles": []}
    rep = build(cfg, mem, mem.gid)
    role = {r["name"]: r["id"] for r in mem.roles}
    assert set(mem.members["300000000000000777"]["roles"]) == {role["🔨 Moderador"], role["⭐ Staff"]}
    assert any("300000000000000888 ainda não entrou" in w for w in rep.warnings)


def test_bot_role_below_our_roles_is_reported(cfg):
    mem = MemoryDiscord()
    build(cfg, mem, mem.gid)
    bot = next(r for r in mem.roles if r["managed"])
    bot["position"] = 2
    rep = build(cfg, mem, mem.gid)
    assert any("TOPO" in w for w in rep.warnings)


def test_bad_references_are_rejected(tmp_path):
    bad = tmp_path / "s.yml"
    bad.write_text("roles:\n  - {key: a, name: A}\ncategories:\n  - {name: X, visible_to: [nope], channels: []}\n")
    with pytest.raises(ConfigError):
        load_config(bad)


def test_overwrites_never_allow_and_deny_the_same_bit():
    ows = overwrites({"everyone"}, {"everyone"}, "text", {}, "1")
    assert all(int(o["allow"]) & int(o["deny"]) == 0 for o in ows)


def test_rate_limit_is_respected():
    calls, slept = [], []

    def handler(req):
        calls.append(req.url.path)
        if len(calls) == 1:
            return httpx.Response(429, json={"retry_after": 1.5})
        return httpx.Response(200, json={"id": "1", "name": "VC STAR"})

    api = DiscordAPI("t", client=httpx.Client(base_url="https://discord.com/api/v10",
                                              transport=httpx.MockTransport(handler)), sleep=slept.append)
    assert api.call("GET", "/guilds/1")["name"] == "VC STAR"
    assert len(calls) == 2 and slept and slept[0] >= 1.5


def test_auth_error_is_clear():
    api = DiscordAPI("t", client=httpx.Client(base_url="https://discord.com/api/v10",
                                              transport=httpx.MockTransport(lambda r: httpx.Response(401, json={}))))
    with pytest.raises(DiscordError) as exc:
        api.call("GET", "/guilds/1")
    assert exc.value.status == 401
