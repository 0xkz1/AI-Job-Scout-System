"""Regression tests for the two data-loss bugs fixed 2026-07-15/16:

1. --reanalyze used to write only filter-passed jobs back to _analyzed.json
   (the incremental-dedup DB), silently dropping filtered-out jobs — they'd
   get re-scraped and re-analyzed forever.
2. Duplicate postings (same company+title, matching description — e.g.
   LinkedIn reposts under a new job ID) overwrote each other's generated
   report/CV/CL because filenames are derived from company+title only.
"""
from run import dedupe_by_company_title, generate_outputs, _same_posting
from matcher import (
    calculate_skill_match, calculate_experience_match,
    calculate_location_match, calculate_salary_match, calculate_context_match,
)


def _job(company, title, url, description="", **extra):
    j = {"company": company, "title": title, "url": url, "description": description}
    j.update(extra)
    return j


def _match(composite_score, tier="🟡 Good Match"):
    # Build a real, fully-shaped match dict via the actual (network-free,
    # TF-IDF-only) scoring helpers, then override composite_score/tier —
    # avoids hand-guessing generate_match_report's expected field shape.
    weights = {"skills": 0.4, "experience": 0.25, "location": 0.1, "salary": 0.05, "context": 0.2}
    ctx = calculate_context_match("a generic job description")
    return {
        "composite_score": composite_score,
        "tier": tier,
        "description_missing": False,
        "skills": calculate_skill_match([], {}),
        "experience": calculate_experience_match("mid", {}),
        "location": calculate_location_match("Remote", "remote", {}),
        "salary": calculate_salary_match({}, 30000),
        "context_score": ctx["score"],
        "context_reasoning": ctx["reasoning"],
        "context_reasoning_en": "",
        "context_reasoning_ja": "",
        "context_top_terms": ctx.get("top_terms", []),
        "context_source": "tfidf",
        "title_relevance": 1.0,
        "weights": weights,
        "summary_en": "",
        "summary_ja": "",
    }


def test_dedupe_merges_matching_duplicate_postings():
    desc = "We are hiring a Product Designer. " * 30  # >100 chars, real content
    jobs = [
        _job("Acme", "Product Designer", "https://x.com/1", desc, match={"composite_score": 0.5}),
        _job("Acme", "Product Designer", "https://x.com/2", desc, match={"composite_score": 0.9}),
    ]
    result = dedupe_by_company_title(jobs)
    assert len(result) == 1
    # Keeps the higher-scoring/better-described entry, records the loser's URL
    assert result[0]["url"] == "https://x.com/2"
    assert result[0]["duplicate_urls"] == ["https://x.com/1"]


def test_dedupe_keeps_distinct_jobs_with_different_descriptions_separate():
    # Same company+title (e.g. a mislabeled scrape) but genuinely different
    # postings — must NOT merge. See the Wordsmith AI "Designer, Web & Brand"
    # vs "Product Designer" incident: a bad title extraction nearly caused
    # two different job postings to collapse into one.
    jobs = [
        _job("Acme", "Designer", "https://x.com/1", "Brand identity and print design role. " * 20),
        _job("Acme", "Designer", "https://x.com/2", "Backend API and database design role. " * 20),
    ]
    result = dedupe_by_company_title(jobs)
    assert len(result) == 2


def test_dedupe_preserves_total_job_count_when_no_duplicates():
    jobs = [
        _job("Acme", "Designer", "https://x.com/1", "desc " * 30),
        _job("Beta", "Engineer", "https://x.com/2", "desc " * 30),
        _job("Gamma", "Analyst", "https://x.com/3", "desc " * 30),
    ]
    result = dedupe_by_company_title(jobs)
    assert len(result) == 3


def test_same_posting_treats_missing_description_as_matching():
    # A job with no/short description can't be disproven as a duplicate —
    # must not become a false "distinct job" that blocks merging.
    a = _job("Acme", "Designer", "https://x.com/1", "")
    b = _job("Acme", "Designer", "https://x.com/2", "Full real description here. " * 20)
    assert _same_posting(a, b) is True


def test_generate_outputs_disambiguates_filename_collision(tmp_path):
    # Two genuinely distinct jobs sharing company+title (post-dedupe) must not
    # silently overwrite each other's report/CV/CL files.
    config = {"match_score_threshold": 0.99}  # suppress CV/CL generation (no LLM in test)
    jobs = [
        {
            "company": "Acme", "title": "Designer", "url": "https://x.com/1",
            "description": "desc", "location": "Remote", "match": _match(0.5),
        },
        {
            "company": "Acme", "title": "Designer", "url": "https://x.com/2",
            "description": "desc", "location": "Remote", "match": _match(0.6),
        },
    ]
    generate_outputs(jobs, config, str(tmp_path))
    reports = list((tmp_path / "00_matches").glob("*.md"))
    assert len(reports) == 2, f"expected 2 distinct reports, got {[r.name for r in reports]}"


def test_generate_outputs_writes_all_passed_jobs_reports(tmp_path):
    config = {"match_score_threshold": 0.99}
    jobs = [
        {
            "company": f"Company{i}", "title": "Role", "url": f"https://x.com/{i}",
            "description": "desc", "location": "Remote", "match": _match(0.3, "🔴 Weak Match"),
        }
        for i in range(5)
    ]
    generate_outputs(jobs, config, str(tmp_path))
    reports = list((tmp_path / "00_matches").glob("*.md"))
    assert len(reports) == 5
