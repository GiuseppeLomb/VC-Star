import base64

from radar.util import (
    decode_google_news,
    domain_of,
    make_excerpt,
    normalize_url,
    resolve_link,
    strip_source_suffix,
    url_id,
)


def test_strips_tracking_fragment_and_trailing_slash():
    url = "HTTPS://WWW.IGN.com/articles/gta-6-online/?utm_source=x&utm_medium=y&fbclid=abc&ref=home&page=2#comments"
    assert normalize_url(url) == "https://www.ign.com/articles/gta-6-online?page=2"


def test_http_and_www_variants_share_the_same_id():
    a = url_id("http://www.example.com/news/gta-6/")
    b = url_id("https://example.com/news/gta-6?utm_campaign=z")
    assert a == b and len(a) == 40


def test_root_path_and_ports():
    assert normalize_url("https://example.com:443/") == "https://example.com"


def test_bing_redirect_is_unwrapped():
    link = ("http://www.bing.com/news/apiclick.aspx?ref=FexRss&aid=&tid=1&url="
            "https%3a%2f%2fwww.gamesradar.com%2fgta-6-rp%2f&c=123&mkt=en-us")
    assert resolve_link(link) == "https://www.gamesradar.com/gta-6-rp/"
    assert domain_of(normalize_url(link)) == "gamesradar.com"


def test_google_news_old_style_ids_are_decoded():
    target = b"https://www.insider-gaming.com/gta-6-private-servers/"
    token = base64.urlsafe_b64encode(b"\x08\x13\x22" + bytes([len(target)]) + target + b"\xd2\x01\x00").decode().rstrip("=")
    link = f"https://news.google.com/rss/articles/{token}?oc=5"
    assert decode_google_news(link) == target.decode()
    assert normalize_url(link) == "https://www.insider-gaming.com/gta-6-private-servers"


def test_google_news_new_style_ids_stay_but_lose_query():
    link = "https://news.google.com/rss/articles/AU_yqLPnotdecodable123?oc=5&hl=en"
    assert decode_google_news(link) is None
    assert normalize_url(link) == "https://news.google.com/rss/articles/AU_yqLPnotdecodable123"


def test_excerpt_is_short_and_plain():
    text = "<p>" + ("palavra " * 100) + "</p>"
    ex = make_excerpt(text)
    assert len(ex) <= 280 and "<" not in ex and ex.endswith("…")


def test_google_suffix_removed():
    assert strip_source_suffix("GTA 6 Online detailed - IGN", "IGN") == "GTA 6 Online detailed"


def test_google_suffix_removed_when_publisher_name_varies():
    assert strip_source_suffix("GTA 6 RP explained - GamesRadar", "GamesRadar+") == "GTA 6 RP explained"
    # a dash that is part of the headline stays
    assert strip_source_suffix("GTA 6 - the RP question", "IGN") == "GTA 6 - the RP question"
