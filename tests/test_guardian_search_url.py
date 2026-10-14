"""Guardian Jobs accepts `keywords`; `q` is accepted and ignored.

Measured 2026-09-24: ?q=graphic+designer, ?q=nurse and ?q=accountant returned the
same twenty rows — the front page of /jobs/. Across 65 nights and 2,233 searches the
board returned exactly 60 or exactly 100 rows and never zero, 60 being three pages of
twenty, because the query was never applied. With `keywords`, a nonsense term returns
0 and 'nurse' returns nursing posts.
"""
from urllib.parse import parse_qs, urlparse

from scraper_guardian import _search_url


def test_the_parameter_is_keywords_not_q():
    q = parse_qs(urlparse(_search_url("Graphic Designer")).query)
    assert "keywords" in q, f"the board ignores anything else: {q}"
    assert q["keywords"] == ["Graphic Designer"]
    assert "q" not in q


def test_no_location_is_sent():
    """location=, Location=, locationsearch= and radialsearch= were each measured
    against a fixed keyword and all returned what sending no location returns."""
    q = parse_qs(urlparse(_search_url("Designer")).query)
    assert not {"location", "Location", "locationsearch", "radialsearch"} & set(q)


def test_later_pages_keep_the_keyword():
    """Pagination still built the old ?q= URL from names the fix removed, so every
    search died with NameError on page 2 and the whole board scraped nothing on
    2026-09-25 and 2026-09-26."""
    url = urlparse(_search_url("Graphic Designer", 2))
    assert url.path == "/jobs/2/"
    assert parse_qs(url.query) == {"keywords": ["Graphic Designer"]}
    assert urlparse(_search_url("Designer", 1)).path == "/jobs/"


def test_only_keyword_titles_reach_the_detail_fetch(monkeypatch):
    """`keywords=` is full-text, so most rows only mention a keyword in the body.
    Fetching all of them (~4s each) overran the 1,500s cap on 2026-09-27 and staged
    nothing; the gate has to sit before the fetch, not after it."""
    import asyncio
    import scraper_guardian as g

    rows = [
        {"title": "Interaction Designer - Newcastle", "snippet": "", "url": "u1"},
        {"title": "Lead Software Engineer - Java", "snippet": "Equities", "url": "u2"},
        {"title": "Content Lead", "snippet": "working with our web designer", "url": "u3"},
    ]

    class Page:
        async def goto(self, *a, **k): pass
        async def wait_for_timeout(self, *a): pass
        async def title(self): return ""
        async def evaluate(self, script):
            return "" if "body.textContent" in script else [dict(r) for r in rows]

    class Browser:
        async def new_context(self, **k): return self
        async def new_page(self): return Page()
        async def close(self): pass

    class Chromium:
        async def launch(self, **k): return Browser()

    class Playwright:
        chromium = Chromium()

    fetched = []

    async def fake_fetch(context, jobs, cache, fn, sleep_delay=1.0):
        fetched.extend(j["url"] for j in jobs)

    monkeypatch.setattr(g, "fetch_descriptions_sequential", fake_fetch)
    jobs = asyncio.run(g.scrape_guardian(
        "Designer", max_pages=1, config={"keywords": ["Designer", "Web Designer"]},
        cache={}, playwright_instance=Playwright()))
    assert fetched == ["u1", "u3"]
    assert [j["url"] for j in jobs] == ["u1", "u3"]


def test_the_keyword_is_encoded():
    assert "Graphic+Designer" in _search_url("Graphic Designer")
    assert " " not in urlparse(_search_url("C# Developer")).query
