"""Rules added after the first real run on the GitHub runner (03/11/2026)."""
from datetime import datetime, timezone

from conftest import make_source, raw
from radar.classify import build_item, classify
from radar.notify import push_priority

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def run(r, src, rules):
    it = build_item(r, src, NOW)
    return classify(it, src, rules) if it else None


def test_cfx_posts_without_gta6_do_not_push(rules):
    cfx = make_source(id="cfx_announcements", tier="official", relevance="always", extra={"push_requires_gta6": True})
    sale = run(raw("End of Summer 2026 Upvotes Sale", "https://forum.cfx.re/t/1", summary="FiveM servers sale"), cfx, rules)
    assert sale is not None and "rp" in sale["topics"]
    assert push_priority(sale, rules, cfx) is None
    big = run(raw("Cfx.re and GTA VI: roleplay servers are coming", "https://forum.cfx.re/t/2"), cfx, rules)
    assert push_priority(big, rules, cfx) == 5


def test_title_filter_keeps_only_matching_press_releases(rules):
    t2 = make_source(id="taketwo_press", tier="official", relevance="always",
                     extra={"title_filter": r"Rockstar|Grand Theft Auto|\bGTA\b|Reports Results"})
    assert run(raw("Ball Over Everything in NBA 2K27 Now Available", "https://www.businesswire.com/a"), t2, rules) is None
    ok = run(raw("Take-Two Interactive Software, Inc. Reports Results for Fiscal Q2", "https://www.businesswire.com/b"), t2, rules)
    assert ok is not None and ok["tag"] == "OFICIAL"


def test_gta6_or_topic_and_excluded_domains(rules):
    rs = make_source(id="rockstar_gnews", tier="official", relevance="gta6_or_topic",
                     extra={"exclude_domains": ["store.rockstargames.com"]})
    assert run(raw("Order support", "https://support.rockstargames.com/a"), rs, rules) is None
    assert run(raw("Grand Theft Auto VI Pre-Load Begins", "https://www.rockstargames.com/n/1"), rs, rules) is not None
    assert run(raw("Introducing the Rockstar Creator Platform", "https://www.rockstargames.com/n/2"), rs, rules) is not None
    assert run(raw("Grand Theft Auto VI vinyl", "https://store.rockstargames.com/v"), rs, rules) is None


def test_blocked_domains_are_dropped(rules):
    assert run(raw("GTA 6 Online Release Date: 2027 Report", "https://www.mmoexp.com/news/1"), make_source(), rules) is None


def test_standalone_rp_and_mods_count(rules):
    out = run(raw("Rockstar proibiu mods no GTA 6? E como fica o RP", "https://x.com.br/a"), make_source(lang="pt"), rules)
    assert set(out["topics"]) == {"rp", "creator"}
    # but not inside other words
    out = run(raw("GTA 6 is an RPG now", "https://x.com/b"), make_source(), rules)
    assert out["topics"] == []
