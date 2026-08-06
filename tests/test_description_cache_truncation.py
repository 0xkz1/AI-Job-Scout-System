"""load_description_cache() must not hand out a truncated description as if
it were the complete one.

Adzuna's API caps descriptions at 500 characters. Measured 2026-08-05: 706 of
2214 postings in _analyzed.json have a description of exactly 500 chars, 714
of the <=500-char entries are source=adzuna. This cache mixes every source
under the same (title, company) key with no source tag, and used to keep
whichever record was read last regardless of length — so a full posting
scraped by reed or LinkedIn could be silently replaced by Adzuna's 500-char
stub, and every scraper sharing this cache (indeed, reed, adzuna, guardian)
would then treat the stub as a fetched, complete description. Confirmed case:
LinkedIn's "Web Developer @ Heriot-Watt University" is 7294 chars fetched
directly, 500 chars via the unguarded cache.
"""
import json

import scraper_helper as h


def _job(title, company, description, **extra):
    return {"title": title, "company": company, "description": description, **extra}


def test_short_description_is_never_cached():
    cache = {}
    h._offer(cache, _job("Web Developer", "Acme", "x" * 500))
    assert cache == {}


def test_long_description_is_cached():
    cache = {}
    job = _job("Web Developer", "Acme", "x" * 7000)
    h._offer(cache, job)
    assert cache[("web developer", "acme")] is job


def test_longer_description_replaces_shorter_one_regardless_of_order():
    cache = {}
    short = _job("Web Developer", "Acme", "x" * 700)
    long = _job("Web Developer", "Acme", "y" * 7000)
    h._offer(cache, short)
    h._offer(cache, long)
    assert cache[("web developer", "acme")] is long


def test_short_description_never_overwrites_a_cached_long_one():
    # The order-dependence that caused the original bug: whichever source file
    # happened to be read last used to win outright.
    cache = {}
    long = _job("Web Developer", "Acme", "y" * 7000)
    short = _job("Web Developer", "Acme", "x" * 500)
    h._offer(cache, long)
    h._offer(cache, short)
    assert cache[("web developer", "acme")] is long


def test_load_description_cache_excludes_adzuna_length_stubs(tmp_path):
    # End-to-end through the real loader, against a mix mirroring the actual
    # corpus shape: one adzuna stub, one full-length posting, same job.
    (tmp_path / "10_output").mkdir()
    (tmp_path / "00_saved").mkdir()
    analyzed = [
        {"title": "Web Developer", "company": "Heriot-Watt University",
         "description": "x" * 500, "source": "adzuna"},
    ]
    (tmp_path / "10_output" / "_analyzed.json").write_text(json.dumps(analyzed))
    saved = [
        {"title": "Web Developer", "company": "Heriot-Watt University",
         "description": "y" * 7294, "source": "linkedin"},
    ]
    (tmp_path / "00_saved" / "_raw_linkedin.json").write_text(json.dumps(saved))

    cache = h.load_description_cache(base_dir=str(tmp_path))
    got = cache[("web developer", "heriot-watt university")]
    assert len(got["description"]) == 7294, "the 500-char adzuna stub must not win"


def test_load_description_cache_still_works_with_default_repo_path():
    # The default argument must still resolve to the real repo — a regression
    # here would silently stop every scraper from finding its cache.
    cache = h.load_description_cache()
    assert isinstance(cache, dict)
