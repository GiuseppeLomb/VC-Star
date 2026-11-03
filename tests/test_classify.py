from datetime import datetime, timezone

from radar.classify import CREDIVEL, OFICIAL, RUMOR, build_item, classify

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def run(raw, source, rules):
    item = build_item(raw, source, NOW)
    return classify(item, source, rules) if item else None


def test_official_source_is_official(rules, source_factory, raw_factory):
    src = source_factory(id="rockstar_newswire", tier="official", relevance="always")
    out = run(raw_factory("Red Dead Online bonuses this week", "https://www.rockstargames.com/newswire/article/1"), src, rules)
    assert out["tag"] == OFICIAL


def test_official_domain_via_google_news(rules, source_factory, raw_factory):
    src = source_factory(id="gnews_online")
    r = raw_factory("GTA 6 Online coming in 2027 - Rockstar Games", "https://news.google.com/rss/articles/AU_yqLx",
                    source_title="Rockstar Games", source_url="https://www.rockstargames.com")
    out = run(r, src, rules)
    assert out["tag"] == OFICIAL and out["domain"] == "rockstargames.com"
    assert out["title"] == "GTA 6 Online coming in 2027"


def test_credible_domain(rules, source_factory, raw_factory):
    out = run(raw_factory("GTA 6 roleplay servers detailed", "https://www.insider-gaming.com/gta-6-rp"),
              source_factory(), rules)
    assert out["tag"] == CREDIVEL


def test_journalist_in_title_is_credible(rules, source_factory, raw_factory):
    out = run(raw_factory("Jason Schreier: GTA 6 Online gets RP mode", "https://random-blog.xyz/p/1"),
              source_factory(), rules)
    assert out["tag"] == CREDIVEL


def test_high_rate_leaker_gets_leaker_tag(rules, source_factory, raw_factory):
    for who in ("Tom Henderson", "Tez2", "NateTheHate"):
        out = run(raw_factory(f"{who}: GTA 6 Online gets RP mode", f"https://random-blog.xyz/{who}"),
                  source_factory(), rules)
        assert out["tag"] == "LEAKER", who
    # a credible outlet stays CREDIVEL even when quoting a leaker
    out = run(raw_factory("Tez2 says GTA 6 roleplay servers are coming", "https://www.ign.com/x"), source_factory(), rules)
    assert out["tag"] == CREDIVEL


def test_everything_else_is_rumor(rules, source_factory, raw_factory):
    out = run(raw_factory("GTA 6 RP servers coming soon?", "https://random-blog.xyz/p/2"), source_factory(), rules)
    assert out["tag"] == RUMOR


def test_relevance_filter_drops_other_games(rules, source_factory, raw_factory):
    assert run(raw_factory("Minecraft roleplay servers are huge", "https://x.com/1"), source_factory(), rules) is None
    assert run(raw_factory("GTA 5 FiveM update released", "https://x.com/2"), source_factory(), rules) is None


def test_relevance_accepts_gta_vi_spellings(rules, source_factory, raw_factory):
    for t in ("Grand Theft Auto VI roleplay", "GTA VI roleplay", "GTA6 roleplay", "gta-6 roleplay"):
        assert run(raw_factory(t, f"https://x.com/{t}"), source_factory(), rules) is not None, t


def test_official_and_cfx_skip_relevance(rules, source_factory, raw_factory):
    cfx = source_factory(id="cfx_announcements", tier="official", relevance="always")
    out = run(raw_factory("FiveM: new server artifacts available", "https://forum.cfx.re/t/123"), cfx, rules)
    assert out is not None and out["tag"] == OFICIAL and "rp" in out["topics"]


def test_topic_relevance(rules, source_factory, raw_factory):
    sub = source_factory(id="reddit_gta6", relevance="topic")
    assert run(raw_factory("Lucia new screenshot", "https://reddit.com/r/GTA6/1"), sub, rules) is None
    assert run(raw_factory("Will there be roleplay servers?", "https://reddit.com/r/GTA6/2"), sub, rules) is not None


def test_score_weights_and_multipliers(rules, source_factory, raw_factory):
    # rumor: roleplay(40) + private servers(40) = 80
    out = run(raw_factory("GTA 6 roleplay on private servers", "https://x.com/a"), source_factory(), rules)
    assert out["score"] == 80 and set(out["topics"]) == {"rp", "servidores"}
    # credible x1.2: GTA 6 Online (30) + PC version (20) = 50 -> 60
    out = run(raw_factory("GTA 6 Online and PC version news", "https://www.ign.com/a"), source_factory(), rules)
    assert out["score"] == 60
    # official x1.5 with cap 100
    off = source_factory(tier="official", relevance="always")
    out = run(raw_factory("GTA 6 Online private servers and FiveM roleplay", "https://www.rockstargames.com/n/1"), off, rules)
    assert out["score"] == 100


def test_each_keyword_entry_counts_once(rules, source_factory, raw_factory):
    out = run(raw_factory("GTA 6 trailer trailer trailer", "https://x.com/t"), source_factory(), rules)
    assert out["score"] == 10 and out["topics"] == ["trailer"]


def test_scam_terms_discard_or_penalise(rules, source_factory, raw_factory):
    assert run(raw_factory("GTA 6 free download APK", "https://scam.xyz/1"), source_factory(), rules) is None
    assert run(raw_factory("GTA 6 mod menu roleplay", "https://scam.xyz/2"), source_factory(), rules) is None
    out = run(raw_factory("GTA 6 roleplay cheats list", "https://x.com/c"), source_factory(), rules)
    assert out["score"] == 10  # 40 - 30


def test_google_news_excerpt_that_repeats_title_is_dropped(rules, source_factory, raw_factory):
    r = raw_factory("GTA 6 roleplay servers - IGN", "https://news.google.com/rss/articles/AU_yqLz",
                    summary='<a href="x">GTA 6 roleplay servers</a>&nbsp;&nbsp;<font color="#6f6f6f">IGN</font>',
                    source_title="IGN", source_url="https://www.ign.com")
    out = run(r, source_factory(), rules)
    assert out["excerpt"] == "" and out["source_name"] == "IGN"
