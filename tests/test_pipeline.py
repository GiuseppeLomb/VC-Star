"""End-to-end runs of radar.main.run with a fake network."""
import json
from datetime import timedelta

from conftest import NOW, FakeFetcher, RecordingNotifier, raw
from radar.main import run


def quiet(_):
    pass


HISTORY = {
    "gnews_online": [
        raw("GTA 6 Online roleplay rumours explained - IGN", "https://www.ign.com/gta-6-online-rp", 30,
            source_title="IGN", source_url="https://www.ign.com"),
        raw("GTA 6 trailer breakdown", "https://random-blog.xyz/trailer", 40),
    ],
    "reddit_rp": [raw("Will FiveM move to GTA 6?", "https://www.reddit.com/r/FiveM/comments/1", 5)],
}


def test_first_run_indexes_history_silently(workdir):
    n = RecordingNotifier()
    res = run(workdir, fetcher=FakeFetcher(HISTORY), notifier=n, now=NOW, out=quiet)
    assert res["first_run"] is True
    assert len(n.sent) == 1 and n.sent[0].title.startswith("✅ Radar ativo — 3 itens")
    news = json.loads((workdir / "docs/data/news.json").read_text())
    assert news["count"] == 3
    seen = json.loads((workdir / "data/seen.json").read_text())
    assert seen["push_ready"] is True and not any(v["pending"] for v in seen["items"].values())
    assert (workdir / "docs/data/health.json").exists()


def test_second_run_no_duplicates_and_no_repeated_pushes(workdir):
    n = RecordingNotifier()
    run(workdir, fetcher=FakeFetcher(HISTORY), notifier=n, now=NOW, out=quiet)
    n.sent.clear()
    res = run(workdir, fetcher=FakeFetcher(HISTORY), notifier=n, now=NOW + timedelta(minutes=10), out=quiet)
    assert res["new"] == [] and n.sent == []
    assert res["changed"]["news"] is False
    news = json.loads((workdir / "docs/data/news.json").read_text())
    ids = [i["id"] for i in news["items"]]
    assert len(ids) == len(set(ids)) == 3


def test_injected_official_private_servers_item_pushes_priority_5(workdir):
    n = RecordingNotifier()
    run(workdir, fetcher=FakeFetcher(HISTORY), notifier=n, now=NOW, out=quiet)
    n.sent.clear()
    fake = dict(HISTORY)
    fake["rockstar_gnews"] = [raw("Grand Theft Auto VI: Private Servers Coming to GTA Online",
                                     "https://www.rockstargames.com/newswire/article/999/gta-vi-private-servers", 0.2)]
    later = NOW + timedelta(minutes=10)
    res = run(workdir, fetcher=FakeFetcher(fake), notifier=n, now=later, out=quiet)
    assert len(res["new"]) == 1 and res["new"][0]["tag"] == "OFICIAL"
    assert len(n.sent) == 1
    assert n.sent[0].priority == 5 and n.sent[0].title.startswith("🚨 OFICIAL:")
    assert res["commit_message"] == "radar: +1 itens (1 oficiais)"
    # and never again
    n.sent.clear()
    run(workdir, fetcher=FakeFetcher(fake), notifier=n, now=later + timedelta(minutes=10), out=quiet)
    assert n.sent == []


def test_rumor_never_pushes(workdir):
    n = RecordingNotifier()
    run(workdir, fetcher=FakeFetcher(HISTORY), notifier=n, now=NOW, out=quiet)
    n.sent.clear()
    fake = {"gnews_rp": [raw("GTA 6 private RP servers leaked", "https://random-blog.xyz/leak", 0.1)]}
    res = run(workdir, fetcher=FakeFetcher(fake), notifier=n, now=NOW + timedelta(minutes=10), out=quiet)
    assert len(res["new"]) == 1 and res["new"][0]["tag"] == "RUMOR" and n.sent == []


def test_more_than_ten_important_items_are_capped(workdir):
    n = RecordingNotifier()
    run(workdir, fetcher=FakeFetcher(HISTORY), notifier=n, now=NOW, out=quiet)
    n.sent.clear()
    subjects = ["Vice City police", "Leonida beaches", "Port Gellhorn races", "Ambrosia farms", "Grassrivers boats",
                "Mount Kalaga hikes", "Kelly County bikers", "Keys fishing", "Downtown nightclubs", "Airport heists",
                "Swamp airboats", "Studio lots", "Stock market", "Radio stations"]
    burst = {"rockstar_gnews": [
        raw(f"GTA VI Online roleplay: {s} explained", f"https://www.rockstargames.com/newswire/article/{k}", 0.1)
        for k, s in enumerate(subjects)]}
    run(workdir, fetcher=FakeFetcher(burst), notifier=n, now=NOW + timedelta(minutes=10), out=quiet)
    assert len(n.sent) == 10 and "novidades" in n.sent[-1].title


def test_without_topic_pushes_wait_then_bootstrap_silences_history(workdir):
    off = RecordingNotifier(topic=None)
    run(workdir, fetcher=FakeFetcher(HISTORY), notifier=off, now=NOW, out=quiet)
    fake = {"rockstar_gnews": [raw("GTA VI private servers", "https://www.rockstargames.com/newswire/article/5", 0.1)]}
    run(workdir, fetcher=FakeFetcher(fake), notifier=off, now=NOW + timedelta(minutes=10), out=quiet)
    on = RecordingNotifier()
    run(workdir, fetcher=FakeFetcher(fake), notifier=on, now=NOW + timedelta(minutes=20), out=quiet)
    assert len(on.sent) == 1 and on.sent[0].title.startswith("✅ Radar ativo")


def test_failed_push_is_retried_next_run(workdir):
    ok = RecordingNotifier()
    run(workdir, fetcher=FakeFetcher(HISTORY), notifier=ok, now=NOW, out=quiet)
    fake = {"rockstar_gnews": [raw("GTA VI Online roleplay announced", "https://www.rockstargames.com/newswire/article/7", 0.1)]}
    bad = RecordingNotifier(fail=True)
    run(workdir, fetcher=FakeFetcher(fake), notifier=bad, now=NOW + timedelta(minutes=10), out=quiet)
    ok.sent.clear()
    run(workdir, fetcher=FakeFetcher(fake), notifier=ok, now=NOW + timedelta(minutes=20), out=quiet)
    assert len(ok.sent) == 1 and ok.sent[0].priority == 5


def test_failing_source_is_isolated_and_recorded(workdir):
    n = RecordingNotifier()
    res = run(workdir, fetcher=FakeFetcher(HISTORY, errors={"reddit_gta6": "HTTP 403"}), notifier=n, now=NOW, out=quiet)
    h = res["health"]["sources"]
    assert h["reddit_gta6"]["error"] == "HTTP 403" and h["reddit_gta6"]["consecutive_failures"] == 1
    assert h["gnews_online"]["error"] is None and h["gnews_online"]["last_count"] == 2
    assert len(res["selected"]) == 3


def test_dry_run_writes_nothing(workdir):
    res = run(workdir, dry_run=True, fetcher=FakeFetcher(HISTORY), now=NOW, out=quiet)
    assert not (workdir / "docs/data/news.json").exists()
    assert not (workdir / "data/seen.json").exists()
    assert res["sent"] and res["sent"][0].title.startswith("✅")


def test_all_sources_failing_on_first_run_does_not_repeat_test_push(workdir):
    n = RecordingNotifier()
    errors = {"gnews_online": "HTTP 503", "reddit_rp": "HTTP 403"}
    run(workdir, fetcher=FakeFetcher({}, errors=errors), notifier=n, now=NOW, out=quiet)
    run(workdir, fetcher=FakeFetcher({}, errors=errors), notifier=n, now=NOW + timedelta(minutes=10), out=quiet)
    assert len(n.sent) == 1  # one test push only
    # when the sources come back, the history is still treated as history (no flood)
    res = run(workdir, fetcher=FakeFetcher(HISTORY), notifier=n, now=NOW + timedelta(minutes=20), out=quiet)
    assert res["first_run"] is True and len(n.sent) == 1
    res = run(workdir, fetcher=FakeFetcher(HISTORY), notifier=n, now=NOW + timedelta(minutes=30), out=quiet)
    assert res["first_run"] is False and len(n.sent) == 1
