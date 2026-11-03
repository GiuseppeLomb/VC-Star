from datetime import datetime, timezone

from radar.notify import plan_messages, push_priority

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def it(tag, topics=(), score=0, title="Item", i="x", published="2026-11-20T11:00:00Z"):
    return {"id": i, "tag": tag, "topics": list(topics), "score": score, "title": title,
            "url": f"https://e.com/{i}", "published": published, "source_name": "S", "excerpt": ""}


def test_priority_rules(rules):
    assert push_priority(it("OFICIAL", ["servidores"]), rules) == 5
    assert push_priority(it("OFICIAL", ["creator"]), rules) == 5
    assert push_priority(it("OFICIAL", ["trailer"]), rules) == 4
    assert push_priority(it("OFICIAL", [], title="Grand Theft Auto VI launch trailer"), rules) == 4
    # official but about another game, no topic -> stays in the app only
    assert push_priority(it("OFICIAL", [], title="Red Dead Online bonuses"), rules) is None
    assert push_priority(it("CREDIVEL", ["rp"], score=60), rules) == 3
    assert push_priority(it("CREDIVEL", ["rp"], score=48), rules) is None
    assert push_priority(it("RUMOR", ["rp", "servidores"], score=100), rules) is None


def test_urgent_message_format(rules):
    msg = plan_messages([(it("OFICIAL", ["servidores"], title="Private servers", i="a"), 5)])[0]
    assert msg.priority == 5 and msg.title.startswith("🚨 OFICIAL: ") and msg.tags == ["rotating_light"]
    assert msg.click == "https://e.com/a"


def test_at_most_ten_pushes_with_summary():
    cands = [(it("OFICIAL", ["rp"], i=str(n)), 5 if n < 3 else 4) for n in range(15)]
    msgs = plan_messages(cands, 10)
    assert len(msgs) == 10
    assert all(m.priority == 5 for m in msgs[:3])           # urgent ones go individually first
    assert "6 novidades" in msgs[-1].title and len(msgs[-1].item_ids) == 6


def test_exactly_ten_has_no_summary():
    msgs = plan_messages([(it("OFICIAL", ["rp"], i=str(n)), 4) for n in range(10)], 10)
    assert len(msgs) == 10 and all(len(m.item_ids) == 1 for m in msgs)
