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


def test_the_keyword_is_encoded():
    assert "Graphic+Designer" in _search_url("Graphic Designer")
    assert " " not in urlparse(_search_url("C# Developer")).query
