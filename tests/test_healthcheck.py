from datetime import timedelta

from conftest import NOW
from radar.healthcheck import problems
from radar.util import iso


def test_healthy():
    h = {"generated_at": iso(NOW - timedelta(minutes=20)), "sources": {
        "a": {"tier": "official", "enabled": True, "error": None, "last_success": iso(NOW)}}}
    assert problems(h, NOW) == []


def test_official_down_more_than_6h_and_stale():
    h = {"generated_at": iso(NOW - timedelta(hours=2)), "sources": {
        "a": {"name": "Rockstar Newswire", "tier": "official", "enabled": True, "error": "HTTP 403",
              "last_success": iso(NOW - timedelta(hours=7))},
        "b": {"name": "Reddit", "tier": "community", "enabled": True, "error": "HTTP 429", "last_success": None}}}
    out = problems(h, NOW)
    assert len(out) == 2 and "parados" in out[0] and "Rockstar Newswire" in out[1]
