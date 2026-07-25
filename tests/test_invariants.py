"""invariants.py — each check must FIRE on the bug it exists for.

A check that cannot fail is worse than no check: it reports healthy forever. That
is not hypothetical here — check_unscoreable_excluded originally asked
selection.is_unscoreable whether exclusion had worked, so when that function was
loosened the check loosened with it and passed on a corpus where a job with no
description had scored review 91. So these tests inject each historical bug and
assert the violation is raised; the live-data run in invariants.main() is what
asserts the healthy case.
"""
import invariants
import pytest


@pytest.fixture
def config():
    return {
        "weights": {"skills": 0.20, "experience": 0.05, "location": 0.10,
                    "salary": 0.01, "context": 0.64},
        "match_score_threshold": 0.45,
        "generation_top_percent": 30,
        "review_top_percent": 30,
    }


def _job(title="Product Designer", company="Acme", composite=0.7,
         relevance=1.0, desc=None, weights=None):
    return {
        "company": company,
        "title": title,
        "description": desc if desc is not None else "Real posting prose. " * 40,
        "match": {
            "composite_score": composite,
            "title_relevance": relevance,
            "weights": weights or {"skills": 0.20, "experience": 0.05,
                                   "location": 0.10, "salary": 0.01, "context": 0.64},
        },
    }


def _spread(n=60):
    """A pool with real spread, so distribution checks are not the thing firing."""
    return [_job(title=f"Designer {i}", composite=0.9 - i * 0.01) for i in range(n)]


def test_unreachable_threshold_is_reported(monkeypatch, config):
    """The 2026-07-25 dead gate: rubric maxed at 100, style penalty took up to 30,
    threshold was 85 — so submission_ready was false for all 255 reviews."""
    import reviewer

    real = reviewer._extract_score

    def penalised(text):
        score, fact_block, nits = real(text)
        return (max(0, score - min(nits * 3, 30)) if score is not None else None,
                fact_block, nits)

    monkeypatch.setattr(reviewer, "_extract_score", penalised)
    monkeypatch.setattr(reviewer, "get_score_threshold", lambda: 85)
    found = invariants.check_submission_threshold_is_reachable(config)
    assert found and "unreachable" in found[0]


def test_reachable_threshold_is_silent(monkeypatch, config):
    import reviewer

    monkeypatch.setattr(reviewer, "get_score_threshold", lambda: 85)
    assert invariants.check_submission_threshold_is_reachable(config) == []


def test_floor_above_cutoff_is_reported(monkeypatch, config):
    """A floor above the top-N% cutoff silently becomes the real selector."""
    monkeypatch.setattr(invariants, "_load_config", lambda: config)
    import selection

    monkeypatch.setattr(selection, "ranked_jobs", lambda c=None, jobs=None: _spread())
    found = invariants.check_floor_below_selection_cutoff({**config, "match_score_threshold": 0.95})
    assert found and "real selector" in found[0]


def test_floor_below_cutoff_is_silent(monkeypatch, config):
    import selection

    monkeypatch.setattr(selection, "ranked_jobs", lambda c=None, jobs=None: _spread())
    assert invariants.check_floor_below_selection_cutoff(config) == []


def test_stale_stored_weights_are_reported(monkeypatch, config, tmp_path):
    """Recompute used to read each entry's own stored weights, so a config change
    never reached already-scored jobs."""
    db = tmp_path / "a.json"
    stale = {"skills": 0.35, "experience": 0.25, "location": 0.10,
             "salary": 0.01, "context": 0.29}
    db.write_text(__import__("json").dumps([_job(weights=stale)]))
    monkeypatch.setattr(invariants, "ANALYZED", db)
    found = invariants.check_stored_weights_match_config(config)
    assert found and "stale" in found[0]


def test_matching_stored_weights_are_silent(monkeypatch, config, tmp_path):
    db = tmp_path / "a.json"
    db.write_text(__import__("json").dumps([_job()]))
    monkeypatch.setattr(invariants, "ANALYZED", db)
    assert invariants.check_stored_weights_match_config(config) == []


def test_title_excluded_job_in_selection_is_reported(monkeypatch, config):
    """title_relevance 0.0 means hard-excluded, so composite must be 0. "Class 2
    Driver" held composite 0.49 because recompute skipped skill-less jobs."""
    import selection

    monkeypatch.setattr(selection, "select_top",
                        lambda stage, c=None, jobs=None, percent=None:
                        [_job(title="Class 2 Driver", relevance=0.0, composite=0.49)])
    found = invariants.check_irrelevant_titles_excluded(config)
    assert found and "title-excluded" in found[0]


def test_thin_description_in_selection_is_reported(monkeypatch, config):
    """A snippet-only posting gives the reviewer nothing to check, so it invents a
    rubric and scores high — review 91 off a 0-char description."""
    import selection

    monkeypatch.setattr(selection, "select_top",
                        lambda stage, c=None, jobs=None, percent=None:
                        [_job(title="Frontend Developer Needed", desc="")])
    monkeypatch.setattr(invariants.Path, "exists", lambda self: False)
    found = invariants.check_unscoreable_excluded(config)
    assert found and "invent a rubric" in found[0]


def test_thin_check_does_not_delegate_to_the_code_it_tests(monkeypatch, config):
    """Loosening selection.is_unscoreable must NOT silence this check — that is the
    self-referential failure that let it pass while the bug was live."""
    import selection

    monkeypatch.setattr(selection, "is_unscoreable", lambda job: False)
    monkeypatch.setattr(selection, "select_top",
                        lambda stage, c=None, jobs=None, percent=None:
                        [_job(title="Frontend Developer Needed", desc="")])
    monkeypatch.setattr(invariants.Path, "exists", lambda self: False)
    assert invariants.check_unscoreable_excluded(config)


def test_colliding_document_paths_are_reported(monkeypatch, config):
    """Two selected entries sharing make_safe_name share one CV/CL/review path."""
    import selection

    dupe = _job(title="Geotechnical Design Engineer", company="Penguin")
    monkeypatch.setattr(selection, "ranked_jobs",
                        lambda c=None, jobs=None: [dupe, dict(dupe)])
    found = invariants.check_one_entry_per_document_path(config)
    assert found and "more than one selected job" in found[0]


def test_distinct_document_paths_are_silent(monkeypatch, config):
    import selection

    monkeypatch.setattr(selection, "ranked_jobs", lambda c=None, jobs=None: _spread())
    assert invariants.check_one_entry_per_document_path(config) == []


def test_collapsed_score_spread_is_reported(monkeypatch, config):
    """Every job at 0.71 +/- 0.09 made "top 30%" near-arbitrary while every
    individual report still looked reasonable."""
    import selection

    flat = [_job(title=f"D{i}", composite=0.71) for i in range(60)]
    monkeypatch.setattr(selection, "ranked_jobs", lambda c=None, jobs=None: flat)
    found = invariants.check_composite_still_discriminates(config)
    assert found and "separates jobs" in found[0]


def test_healthy_score_spread_is_silent(monkeypatch, config):
    import selection

    monkeypatch.setattr(selection, "ranked_jobs", lambda c=None, jobs=None: _spread())
    assert invariants.check_composite_still_discriminates(config) == []


def test_stale_review_score_is_reported(monkeypatch, config, tmp_path):
    """A stored score computed under a retired rule is what every view sorts on."""
    reviews = tmp_path / "15_reviews"
    reviews.mkdir()
    (reviews / "X_CV_review.md").write_text(
        "---\ntype: \"review\"\nsubmission_score: 12\nstyle_nits: 0\n---\n\n"
        "```yaml\nrubric:\n  - requirement: \"r\"\n    evidence: \"Strong\"\n```\n",
        encoding="utf-8")
    monkeypatch.setattr(invariants, "REVIEWS", reviews)
    found = invariants.check_review_scores_track_rubric(config)
    assert found and "stale submission_score" in found[0]


def test_unscoreable_review_is_exempt_from_score_drift(monkeypatch, config, tmp_path):
    """An invalidated review holds no score, so it cannot have drifted."""
    reviews = tmp_path / "15_reviews"
    reviews.mkdir()
    (reviews / "X_CV_review.md").write_text(
        "---\ntype: \"review\"\nsubmission_score: null\nunscoreable: true\n---\n\n"
        "```yaml\nrubric:\n  - requirement: \"r\"\n    evidence: \"Strong\"\n```\n",
        encoding="utf-8")
    monkeypatch.setattr(invariants, "REVIEWS", reviews)
    assert invariants.check_review_scores_track_rubric(config) == []


def _scrape_config(searches, sites=("reed",)):
    """searches = len(keywords) x len(locations)."""
    return {
        "keywords": [f"k{i}" for i in range(searches)],
        "locations": ["l0"],
        "sites": list(sites),
        "max_pages_per_search": 3,
    }


def test_search_count_that_exceeds_the_cron_timeout_is_reported():
    """reed measured 68s per search, so 63 searches needs ~4300s of a 1500s cap."""
    found = invariants.check_scrape_fits_its_timeout(_scrape_config(63))
    assert len(found) == 1
    assert "exit 124" in found[0]


def test_search_count_within_the_cron_timeout_is_silent():
    """At 68s per search, 1500s affords 22 — 20 must pass."""
    assert invariants.check_scrape_fits_its_timeout(_scrape_config(20)) == []


def test_unmeasured_site_is_not_judged():
    """Guessing a rate for an unmeasured site would produce warnings the reader
    learns to ignore. adzuna and indeed have no observed per-search figure."""
    assert invariants.check_scrape_fits_its_timeout(
        _scrape_config(63, sites=("adzuna", "indeed"))) == []


def test_api_only_site_is_not_charged_for_page_walking():
    """remote_apis has no page walk, so it must not be judged on search count."""
    assert invariants.check_scrape_fits_its_timeout(
        _scrape_config(63, sites=("remote_apis",))) == []


def _analyzed(monkeypatch, tmp_path, jobs):
    db = tmp_path / "a.json"
    db.write_text(__import__("json").dumps(jobs))
    monkeypatch.setattr(invariants, "ANALYZED", db)


def test_silent_site_is_reported(monkeypatch, tmp_path):
    """A stale selector yields nothing and still exits 0 — adzuna went 13 nights
    contributing no job while every run reported success."""
    from datetime import date, timedelta

    old = (date.today() - timedelta(days=13)).isoformat()
    _analyzed(monkeypatch, tmp_path,
              [{"source": "adzuna", "scraped_at": f"{old}T05:00:00Z", "match": {}}])
    found = invariants.check_every_site_still_yields({"sites": ["adzuna"]})
    assert found and "13 days" in found[0]


def test_recently_yielding_site_is_silent(monkeypatch, tmp_path):
    from datetime import date

    today = date.today().isoformat()
    _analyzed(monkeypatch, tmp_path,
              [{"source": "reed", "scraped_at": f"{today}T05:00:00Z", "match": {}}])
    assert invariants.check_every_site_still_yields({"sites": ["reed"]}) == []


def test_site_with_no_jobs_yet_is_reported_without_asserting_a_fault(monkeypatch, tmp_path):
    """A site freshly added to `sites` and a broken scraper are indistinguishable
    from the database, so the report must not claim the scraper is failing."""
    _analyzed(monkeypatch, tmp_path, [])
    found = invariants.check_every_site_still_yields({"sites": ["remote_apis"]})
    assert found
    assert "no job recorded under it yet" in found[0]
    assert "or it has not had a nightly run" in found[0]


def test_site_reporting_under_alias_sources_counts_as_yielding(monkeypatch, tmp_path):
    """remote_apis tags jobs 'remotive'/'remoteok'/'arbeitnow', so matching on the
    site name alone would call a working scraper silent."""
    from datetime import date

    today = date.today().isoformat()
    _analyzed(monkeypatch, tmp_path,
              [{"source": "remotive", "scraped_at": f"{today}T05:00:00Z", "match": {}}])
    assert invariants.check_every_site_still_yields({"sites": ["remote_apis"]}) == []


def test_truncated_summaries_in_the_top_band_are_reported(monkeypatch, tmp_path):
    """Adzuna's API returns only a 500-char summary, and a summary scores HIGHER than
    full text (0.440 vs 0.340) because the cut part is the requirements. So these are
    held out of ranking as well as review, and the size of that backlog is worth
    surfacing — the exclusion is otherwise invisible."""
    jobs = [_job(title=f"D{i}", composite=0.9 - i * 0.01) for i in range(20)]
    jobs[0]["description_truncated"] = True
    jobs[1]["description_truncated"] = True
    _analyzed(monkeypatch, tmp_path, jobs)
    monkeypatch.setattr("filter.passes_filter", lambda j, c: (True, ""))
    found = invariants.check_truncated_descriptions_get_enriched(
        {"generation_top_percent": 30, "review_top_percent": 30})
    assert found
    assert "500-char API summary" in found[0]
    assert "refetch_unscoreable.py --top-only" in found[0], "must name the recovery step"


def test_full_descriptions_in_the_top_band_are_silent(monkeypatch, tmp_path):
    _analyzed(monkeypatch, tmp_path,
              [_job(title=f"D{i}", composite=0.9 - i * 0.01) for i in range(20)])
    monkeypatch.setattr("filter.passes_filter", lambda j, c: (True, ""))
    assert invariants.check_truncated_descriptions_get_enriched(
        {"generation_top_percent": 30, "review_top_percent": 30}) == []


def test_truncated_summaries_really_do_outscore_full_text():
    """The measurement the exclusion rests on, asserted against the live DB.

    A 500-char summary scoring HIGHER than a full description is counter-intuitive
    enough that it needs guarding: if it ever reverses, excluding these from ranking
    stops being justified and this test should fail loudly rather than let the
    exclusion persist on a stale premise. Skipped when the DB has too few of either
    kind to compare.
    """
    import json
    import statistics

    from filter import passes_filter
    from selection import _dedupe, is_unscoreable, load_config

    if not invariants.ANALYZED.exists():
        pytest.skip("no live DB")
    config = load_config()
    pool = [j for j in _dedupe(json.loads(invariants.ANALYZED.read_text(encoding="utf-8")))
            if j.get("match") and passes_filter(j, config)[0]]
    trunc = [j["match"]["composite_score"] for j in pool if j.get("description_truncated")]
    full = [j["match"]["composite_score"] for j in pool if not is_unscoreable(j)]
    if len(trunc) < 30 or len(full) < 30:
        pytest.skip("not enough of each kind to compare")
    assert statistics.mean(trunc) > statistics.mean(full), (
        f"summaries no longer outscore full text (summary {statistics.mean(trunc):.3f} "
        f"vs full {statistics.mean(full):.3f}) — re-examine whether they still need "
        f"holding out of the ranking"
    )


def test_truncated_api_summary_counts_as_unscoreable():
    """A 500-char summary passes a length check but omits the requirements, which is
    exactly the condition that makes the reviewer invent a rubric."""
    from selection import is_unscoreable

    job = {"description": "Real prose about the role. " * 40,
           "description_truncated": True}
    assert is_unscoreable(job)
    del job["description_truncated"]
    assert not is_unscoreable(job)


def test_a_broken_check_is_reported_not_raised(monkeypatch, config):
    """A check that explodes must not take the nightly run with it."""
    def boom(_config):
        raise RuntimeError("db unreadable")

    monkeypatch.setattr(invariants, "CHECKS", (boom,))
    found = invariants.run_all(config)
    assert found and "could not run" in found[0]
