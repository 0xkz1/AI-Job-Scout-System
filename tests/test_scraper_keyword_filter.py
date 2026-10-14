"""Every scraper must filter its results against the configured keywords.

Indeed was the exception for a long time — it trusted its own search relevance
and returned whatever the query brought back. Measured on 2026-08-05, that meant
133 of 296 postings contained none of the configured keywords anywhere, and 84
of those survived config filtering and were paid for with an LLM enrichment call
each: semiconductor analog design, garment technology, exam marking, sign
installation. These tests fail if any scraper drops the filter again.
"""
import ast
import pathlib

import pytest

from scraper_indeed import filter_jobs_by_keywords

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The site scrapers whose entry point returns postings for the analysis pipeline.
# scraper_saved / scraper_url_list are excluded on purpose: those carry jobs the
# user chose by hand, where a keyword test would throw away a deliberate pick.
SCRAPER_ENTRY_POINTS = {
    "scraper_indeed.py": "scrape_indeed_all",
    "scraper_linkedin_guest.py": "scrape_linkedin_guest_all",
    "scraper_reed.py": "scrape_reed_all",
    "scraper_guardian.py": "scrape_guardian_all",
    "scraper_adzuna.py": "scrape_adzuna_all",
    "scraper_remote_apis.py": "scrape_remote_apis_all",
}

KEYWORDS = ["Creative Technologist", "Technical Artist", "Web Developer",
            "Web Designer", "Digital Designer", "Designer"]


def _calls_in(path: pathlib.Path, func_name: str) -> set[str]:
    """Names called anywhere inside the named top-level function."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return {
                sub.func.id
                for sub in ast.walk(node)
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
            }
    raise AssertionError(f"{func_name} not found in {path.name}")


@pytest.mark.parametrize("module,entry", sorted(SCRAPER_ENTRY_POINTS.items()))
def test_scraper_applies_keyword_filter(module, entry):
    assert "filter_jobs_by_keywords" in _calls_in(ROOT / module, entry), (
        f"{module}:{entry} returns postings without checking them against "
        f"config keywords — this is how Indeed spent LLM calls on analog design "
        f"and garment technology roles for weeks"
    )


def test_off_domain_titles_are_dropped():
    # Real titles from the 2026-08-05 Indeed run, all returned for the
    # "Technical Artist" and "Creative Technologist" queries.
    jobs = [
        {"title": "Technologist - Analog Design", "snippet": "",
         "description": "semiconductor analog layout, SPICE, tapeout"},
        {"title": "Non-Apparel Technologist", "snippet": "",
         "description": "garment and accessory testing, fit sessions"},
        {"title": "Sign Installer", "snippet": "",
         "description": "install signage on site, own transport required"},
    ]
    assert filter_jobs_by_keywords(jobs, KEYWORDS) == []


def test_body_only_match_is_kept():
    # A title-only test would drop these, and six of the postings currently
    # scoring 0.80+ match on the body alone.
    job = {"title": "Creative Lead", "snippet": "",
           "description": "you will mentor our designer team and own the system"}
    assert filter_jobs_by_keywords([job], KEYWORDS) == [job]


def test_empty_keyword_list_keeps_everything():
    # An unconfigured keyword list must not silently empty the pipeline.
    jobs = [{"title": "Anything", "snippet": "", "description": ""}]
    assert filter_jobs_by_keywords(jobs, []) == jobs
