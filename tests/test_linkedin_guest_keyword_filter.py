"""scrape_linkedin_guest_all must not reach for a name that was never bound.

On 2026-08-13 a full pipeline run scraped 726 unique LinkedIn postings, fetched
502 descriptions over the network, and then threw
`NameError: name 'keywords' is not defined` on the line immediately after —
discarding all 726. The line read `filter_jobs_by_keywords(all_jobs, keywords)`
inside a function whose only parameter is `config`; every other scraper does
`config.get("keywords", [])` first (see scraper_linkedin.scrape_linkedin_all).

It failed at the very end, after the expensive part, so the run still reported
"1/6 sites failed" and moved on — LinkedIn had simply been returning nothing on
every run that got this far.

The test drives the real function with the network parts stubbed, because that
NameError only fires on the path where postings survive to the filter: any test
that mocks the filter itself, or that returns zero postings, passes over it.
"""
import scraper_indeed
import scraper_linkedin_guest as guest


def test_postings_survive_the_keyword_filter_instead_of_raising(monkeypatch):
    postings = [
        {"job_id": "1", "title": "Product Designer", "company": "A",
         "location": "Edinburgh", "description": "design systems and figma"},
        {"job_id": "2", "title": "Warehouse Operative", "company": "B",
         "location": "Leeds", "description": "pallets and forklifts"},
    ]

    monkeypatch.setattr(guest, "search", lambda kw, loc, max_pages: postings)
    monkeypatch.setattr(guest, "fill_descriptions", lambda jobs, cache: None)
    monkeypatch.setattr(scraper_indeed, "load_description_cache", lambda: {}, raising=False)
    monkeypatch.setattr("scraper_helper.load_description_cache", lambda: {})
    monkeypatch.setattr("selection.max_pages_for", lambda site, config: 1)
    monkeypatch.setattr("selection.search_pairs", lambda config, site=None: [("Designer", "Edinburgh")])

    config = {"keywords": ["Designer"]}
    out = guest.scrape_linkedin_guest_all(config)

    titles = [j["title"] for j in out]
    assert "Product Designer" in titles, (
        "a posting matching a configured keyword was dropped"
    )


def test_the_configured_keywords_are_the_ones_applied(monkeypatch):
    """Not just 'it does not crash' — the list handed to the filter has to be
    the one from config, or the filter silently keeps everything."""
    seen = {}

    def spy(jobs, keywords):
        seen["keywords"] = keywords
        return jobs

    monkeypatch.setattr(guest, "search", lambda kw, loc, max_pages: [
        {"job_id": "1", "title": "Product Designer", "company": "A",
         "location": "Edinburgh", "description": "figma"}])
    monkeypatch.setattr(guest, "fill_descriptions", lambda jobs, cache: None)
    monkeypatch.setattr("scraper_helper.load_description_cache", lambda: {})
    monkeypatch.setattr("selection.max_pages_for", lambda site, config: 1)
    monkeypatch.setattr("selection.search_pairs", lambda config, site=None: [("Designer", "Edinburgh")])
    monkeypatch.setattr(scraper_indeed, "filter_jobs_by_keywords", spy)

    guest.scrape_linkedin_guest_all({"keywords": ["Designer", "Creative Technologist"]})

    assert seen["keywords"] == ["Designer", "Creative Technologist"]


def test_a_config_without_keywords_does_not_raise(monkeypatch):
    """config.get with a default, not config["keywords"] — a config missing the
    key should degrade to an empty filter, not take the whole site down."""
    monkeypatch.setattr(guest, "search", lambda kw, loc, max_pages: [
        {"job_id": "1", "title": "Product Designer", "company": "A",
         "location": "Edinburgh", "description": "figma"}])
    monkeypatch.setattr(guest, "fill_descriptions", lambda jobs, cache: None)
    monkeypatch.setattr("scraper_helper.load_description_cache", lambda: {})
    monkeypatch.setattr("selection.max_pages_for", lambda site, config: 1)
    monkeypatch.setattr("selection.search_pairs", lambda config, site=None: [("Designer", "Edinburgh")])

    guest.scrape_linkedin_guest_all({})
