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


def test_discord_webhook_receives_urgent_alert_with_here_mention():
    import httpx
    from radar.notify import Notifier
    posts = []

    def handler(req):
        import json
        posts.append((str(req.url), json.loads(req.content)))
        return httpx.Response(204)

    n = Notifier(topic=None, discord_webhook="https://discord.com/api/webhooks/1/abc",
                 client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert n.enabled
    msg = plan_messages([(it("OFICIAL", ["servidores"], title="Private servers", i="a"), 5)])[0]
    assert n.send(msg) is True
    url, body = posts[0]
    assert url.startswith("https://discord.com/api/webhooks/")
    assert body["content"].startswith("@here") and body["allowed_mentions"] == {"parse": ["everyone"]}
    assert body["embeds"][0]["url"] == "https://e.com/a" and body["embeds"][0]["color"] == 0xFF2BD6


def test_discord_non_urgent_has_no_mention():
    import httpx
    from radar.notify import Notifier
    bodies = []
    n = Notifier(topic="t", discord_webhook="https://discord.com/api/webhooks/1/abc",
                 client=httpx.Client(transport=httpx.MockTransport(
                     lambda req: bodies.append(req.content) or httpx.Response(200))))
    n.send(plan_messages([(it("CREDIVEL", ["rp"], score=80, i="b"), 3)])[0])
    import json
    discord = [json.loads(b) for b in bodies if b"embeds" in b][0]
    assert discord["content"] is None and discord["allowed_mentions"] == {"parse": []}
    assert len(bodies) == 2  # ntfy + discord
