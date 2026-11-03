import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from radar.classify import load_rules  # noqa: E402
from radar.fetch import FetchResult  # noqa: E402
from radar.sources import Source  # noqa: E402

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def rules():
    return load_rules(ROOT / "config" / "keywords.yml", ROOT / "config" / "credible.yml")


def make_source(**kw):
    base = dict(id="test", name="Test", type="rss", url="https://example.com/feed", tier="community")
    base.update(kw)
    extra = base.pop("extra", {})
    return Source(**base, extra=extra)


@pytest.fixture
def source_factory():
    return make_source


def raw(title, url, hours_ago=1.0, summary="", source_title=None, source_url=None, author=""):
    return {
        "title": title, "url": url, "published": NOW - timedelta(hours=hours_ago),
        "summary": summary, "author": author, "source_title": source_title, "source_url": source_url,
    }


@pytest.fixture
def raw_factory():
    return raw


@pytest.fixture
def workdir(tmp_path):
    """A throwaway copy of the repo layout: real config, empty data."""
    shutil.copytree(ROOT / "config", tmp_path / "config")
    (tmp_path / "data").mkdir()
    (tmp_path / "docs" / "data").mkdir(parents=True)
    return tmp_path


class FakeFetcher:
    """Returns canned items per source id, ignoring the network."""

    def __init__(self, by_source=None, errors=None):
        self.by_source = by_source or {}
        self.errors = errors or {}

    def __call__(self, sources, cache):
        out = []
        for s in sources:
            if s.id in self.errors:
                out.append(FetchResult(source=s, error=self.errors[s.id]))
            else:
                out.append(FetchResult(source=s, items=list(self.by_source.get(s.id, [])), resolved_url=s.url))
        return out


class RecordingNotifier:
    def __init__(self, topic="test-topic", fail=False):
        self.topic = topic
        self.sent = []
        self.fail = fail

    @property
    def enabled(self):
        return bool(self.topic)

    def send(self, msg):
        if self.fail:
            return False
        self.sent.append(msg)
        return True
