from radar.dedup import dedup, similar_titles


def item(i, title, tag="RUMOR", domain="a.com", published="2026-11-20T10:00:00Z"):
    return {"id": i, "title": title, "tag": tag, "domain": domain, "published": published,
            "fetched": published, "also_on": []}


def test_near_identical_titles_are_merged():
    items = [
        item("1", "GTA 6 Online will support private RP servers, report says", domain="rumor.net"),
        item("2", "Report: GTA 6 Online will support private RP servers", domain="ign.com"),
    ]
    out = dedup(items)
    assert len(out) == 1
    assert out[0]["also_on"] == ["ign.com"]


def test_highest_tier_wins_then_oldest():
    items = [
        item("1", "Rockstar confirms GTA 6 private servers for roleplay", tag="RUMOR", domain="x.com",
             published="2026-11-20T08:00:00Z"),
        item("2", "Rockstar confirms GTA 6 private servers for roleplay", tag="OFICIAL", domain="rockstargames.com",
             published="2026-11-20T09:00:00Z"),
        item("3", "Rockstar confirms GTA 6 private servers for roleplay!", tag="CREDIVEL", domain="ign.com",
             published="2026-11-20T07:00:00Z"),
    ]
    out = dedup(items)
    assert len(out) == 1
    assert out[0]["id"] == "2"
    assert set(out[0]["also_on"]) == {"x.com", "ign.com"}


def test_oldest_wins_within_same_tier():
    items = [
        item("new", "GTA 6 creator platform job listings spotted", published="2026-11-20T10:00:00Z"),
        item("old", "GTA 6 creator platform job listings spotted", published="2026-11-19T10:00:00Z", domain="b.com"),
    ]
    assert [i["id"] for i in dedup(items)] == ["old"]


def test_same_id_is_collapsed():
    out = dedup([item("1", "Same story about GTA 6 Online"), item("1", "Same story about GTA 6 Online")])
    assert len(out) == 1


def test_outside_72h_window_is_kept():
    items = [
        item("1", "GTA 6 trailer 3 release date rumours swirl", published="2026-11-10T10:00:00Z"),
        item("2", "GTA 6 trailer 3 release date rumours swirl", published="2026-11-20T10:00:00Z"),
    ]
    assert len(dedup(items)) == 2


def test_different_stories_are_not_merged():
    assert not similar_titles("GTA 6 Online private servers confirmed by Rockstar",
                              "GTA 6 PC version delayed to 2027 says insider")
    # a short generic title must not swallow a longer specific one
    assert not similar_titles("GTA 6", "GTA 6 Online roleplay servers explained in new report")
