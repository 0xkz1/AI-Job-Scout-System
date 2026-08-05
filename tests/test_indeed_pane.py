"""Indeed descriptions come from the listing's preview pane, not from /viewjob.

/viewjob answers with "Additional Verification Required" and a Cloudflare Ray ID —
a hard block, not a challenge that waiting solves — so every fetch through it spent
62s and returned "". indeed scraped nothing for 12 days without erroring, because an
empty description is indistinguishable from a posting that has none.

The subtle part is matching cards to jobs. A card list and a job list are NOT
index-aligned: a duplicate URL is dropped from `jobs` while still occupying a card,
so pairing by position would attach one posting's description to another's title and
every downstream score would be computed against the wrong text. Hence the jk match,
which these tests pin.
"""
import asyncio

from scraper_indeed import (
    _PANE_SELECTORS,
    _fill_descriptions_from_pane,
    _pane_description,
)


class FakeElement:
    def __init__(self, text="", href=None, child=None):
        self._text = text
        self._href = href
        self._child = child

    async def inner_text(self):
        return self._text

    async def get_attribute(self, _name):
        return self._href

    async def query_selector(self, _selector):
        return self._child

    async def click(self):
        return None


class FakePage:
    """A listing page whose card list is re-read on every query, as the real one is."""

    def __init__(self, hrefs, pane_text="A real description. " * 20, queries=None):
        self._hrefs = hrefs
        self._pane_text = pane_text
        self.card_queries = 0
        self.clicked = []
        self._queries = queries if queries is not None else []

    async def query_selector_all(self, _selector):
        self.card_queries += 1
        cards = []
        for href in self._hrefs:
            link = FakeElement(href=href)
            original_click = link.click

            async def click(_h=href, _c=original_click):
                self.clicked.append(_h)
                await _c()

            link.click = click
            cards.append(FakeElement(child=link))
        return cards

    async def query_selector(self, selector):
        self._queries.append(selector)
        if selector == _PANE_SELECTORS[0]:
            return FakeElement(text=self._pane_text)
        return None

    async def wait_for_selector(self, _selector, timeout=None):
        return FakeElement(text=self._pane_text)


def run(coro):
    """pytest-asyncio is not a dependency of this project and these tests do not
    need an event-loop fixture — one loop per test is enough."""
    return asyncio.run(coro)


def _job(title):
    return {"title": title, "company": "Acme", "url": "u", "description": ""}


def test_descriptions_are_matched_by_jk_not_by_card_position():
    """Cards 0 and 2 have jobs; card 1 is a duplicate that was dropped from `jobs`.

    Index pairing would give card 2's job the text fetched while card 1 was open.
    """
    first, third = _job("First"), _job("Third")
    page = FakePage(["/viewjob?jk=aaa111", "/viewjob?jk=bbb222", "/viewjob?jk=ccc333"])

    filled = run(_fill_descriptions_from_pane(page, {"aaa111": first, "ccc333": third}))

    assert filled == 2
    assert first["description"].startswith("A real description.")
    assert third["description"].startswith("A real description.")
    # The dropped card must never have been opened.
    assert page.clicked == ["/viewjob?jk=aaa111", "/viewjob?jk=ccc333"]


def test_card_list_is_requeried_for_every_card():
    """The click re-renders the list, so element handles from an earlier query go
    stale. Holding one list across the loop raises "Element is not attached"."""
    jobs = {f"jk{i}": _job(str(i)) for i in range(3)}
    page = FakePage([f"/viewjob?jk=jk{i}" for i in range(3)])

    run(_fill_descriptions_from_pane(page, jobs))

    # One query to count, then one per card.
    assert page.card_queries == 4


def test_a_job_that_already_has_a_description_is_not_reopened():
    """Cache hits are the reason later nights finish inside the timeout at all."""
    cached = _job("Cached")
    cached["description"] = "Already known."
    page = FakePage(["/viewjob?jk=aaa111"])

    filled = run(_fill_descriptions_from_pane(page, {"aaa111": cached}))

    assert filled == 0
    assert cached["description"] == "Already known."
    assert page.clicked == []


def test_a_card_with_no_jk_is_skipped_rather_than_mispaired():
    """Sponsored/ad cards carry no jk. Skipping keeps the rest aligned."""
    job = _job("Real")
    page = FakePage(["/promo/advert", "/viewjob?jk=aaa111"])

    filled = run(_fill_descriptions_from_pane(page, {"aaa111": job}))

    assert filled == 1
    assert page.clicked == ["/viewjob?jk=aaa111"]


def test_pane_text_is_capped_and_short_text_rejected():
    """A Cloudflare interstitial is ~162 chars of chrome; a real posting measured
    12,807-20,406. The >50 floor rejects the empty-pane case, the cap bounds the
    prompt cost of the long ones."""
    long_page = FakePage(hrefs=[], pane_text="x" * 9000)
    assert len(run(_pane_description(long_page))) == 5000

    short_page = FakePage(hrefs=[], pane_text="too short")
    assert run(_pane_description(short_page)) == ""


def test_the_primary_pane_selector_is_tried_before_the_wrapper():
    """The wrapper also matches, but prepends "Job details / Pay / Job type" to
    every description — ~220 chars of boilerplate the matcher would then read as
    part of the posting."""
    queries = []
    page = FakePage(hrefs=[], queries=queries)
    run(_pane_description(page))
    assert queries[0] == "#jobDescriptionText"


def test_viewjob_is_not_used_by_the_scraper():
    """The regression guard. _fetch_job_description is retained for other callers,
    but scrape_indeed must never route descriptions through it again."""
    import inspect

    import scraper_indeed

    source = inspect.getsource(scraper_indeed.scrape_indeed)
    assert "_fetch_job_description" not in source
    assert "_fill_descriptions_from_pane" in source


def _all_config():
    return {"keywords": ["A", "B"], "locations": ["X", "Y"], "max_pages_per_site": {"indeed": 1}}


def _patch_all(monkeypatch, results):
    """Drive scrape_indeed_all with a scripted per-search outcome list."""
    import scraper_indeed

    calls = []

    async def fake_scrape(kw, loc, **kwargs):
        calls.append((kw, loc))
        outcome = results[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(scraper_indeed, "scrape_indeed", fake_scrape)
    monkeypatch.setattr(scraper_indeed, "load_description_cache", lambda *a, **k: {})
    monkeypatch.setattr(scraper_indeed, "_SEARCH_PAUSE_SECONDS", 0)
    return calls


def _posting(title):
    # The description has to contain a configured keyword ("A", per _all_config).
    # scrape_indeed_all now runs its results through filter_jobs_by_keywords like
    # every other scraper, so a posting matching nothing is dropped — correct
    # behaviour, but it would empty these fixtures and make the tests below look
    # like failures of the resilience they actually check.
    return {"title": title, "company": "Acme", "location": "X",
            "description": "keyword A appears in the body"}


def test_one_failed_search_does_not_discard_the_others(monkeypatch):
    """The bug this replaces: search 4 of 30 raised `Page.goto: Timeout 30000ms
    exceeded`, the exception left scrape_indeed_all, and run.py reported "every
    requested site failed" while binning the 6 postings already scraped."""
    from scraper_indeed import scrape_indeed_all

    calls = _patch_all(monkeypatch, [
        [_posting("one")],
        TimeoutError("Page.goto: Timeout 30000ms exceeded"),
        [_posting("two")],
        [_posting("three")],
    ])

    jobs = run(scrape_indeed_all(_all_config()))

    assert [j["title"] for j in jobs] == ["one", "two", "three"]
    # The failure must not stop the remaining searches from being attempted.
    assert len(calls) == 4


def test_a_wholly_failed_run_still_raises(monkeypatch):
    """A site that scraped nothing must keep reporting failure, or the cron exit
    code stops meaning anything — that silence is how indeed went 12 days unnoticed."""
    import pytest

    from scraper_indeed import scrape_indeed_all

    _patch_all(monkeypatch, [TimeoutError("blocked")] * 4)

    with pytest.raises(RuntimeError, match="all 4 Indeed searches failed"):
        run(scrape_indeed_all(_all_config()))
