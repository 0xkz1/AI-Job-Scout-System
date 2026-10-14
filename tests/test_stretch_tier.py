"""The stretch tier: level-rejected postings that still get documents.

A posting the level gate rejects gets no CV, so it gets no CV review — and the
review score is what decides whether to apply. The rejection therefore did not
deprioritise the posting, it made it unjudgeable. selection.stretch_jobs picks
the small set worth judging anyway.

Two properties carry the design, and both are easy to lose in a refactor:

  - the ranking is by SKILLS score, not composite. A filtered job's composite is
    dominated by a context score the LLM never produced (TF-IDF stands in at 64%
    of the weight), which ranked the posting this tier exists for 106th of 203.
  - a title that names its own seniority is excluded. Without that cut the set
    fills with Principal/Staff/Sr. design roles, where the gap is seniority in
    the discipline itself and no document closes it.
"""
import matcher
import selection


CONFIG = {
    "include_levels": ["entry_level", "mid", "internship"],
    "stretch_top_count": 3,
}


def _job(company, title, level, skills, composite=0.30, url=None):
    return {
        "company": company,
        "title": title,
        "url": url or f"https://example.com/{company}".replace(" ", "-"),
        "description": "Build things. " * 40,
        "analysis": {"experience_level": level, "salary": {}},
        "match": {
            "composite_score": composite,
            "skills": {"score": skills},
        },
    }


def test_a_senior_posting_with_a_neutral_title_is_picked_up():
    jobs = [_job("ITG", "Creative Technologist/AI Specialist", "senior", 0.64)]
    assert [j["company"] for j in selection.stretch_jobs(CONFIG, jobs)] == ["ITG"]


def test_a_posting_that_passes_the_filter_is_not_in_the_stretch_tier():
    """The tier is for rejects. A passing job reaches documents the normal way."""
    jobs = [_job("Fine", "Creative Technologist", "mid", 0.9)]
    assert selection.stretch_jobs(CONFIG, jobs) == []


def test_a_title_naming_its_own_seniority_is_excluded():
    """Seniority in the discipline, not in a requirements list — skip regardless
    of how well the skills overlap."""
    jobs = [
        _job("A", "Principal UX/UI Designer", "senior", 0.90),
        _job("B", "Staff Brand Designer", "senior", 0.89),
        _job("C", "Sr. Product Designer", "senior", 0.88),
        _job("D", "Lead Developer", "senior", 0.87),
        _job("E", "Solutions Architect", "senior", 0.86),
        _job("F", "Web Developer", "senior", 0.10),
    ]
    assert [j["company"] for j in selection.stretch_jobs(CONFIG, jobs)] == ["F"]


def test_director_is_two_steps_up_and_never_stretched():
    jobs = [_job("Boardroom", "Creative Technologist", "director", 0.95)]
    assert selection.stretch_jobs(CONFIG, jobs) == []


def test_a_job_rejected_for_something_other_than_level_is_not_stretched():
    """Only the level gate is soft. A salary or title-keyword rejection stands."""
    jobs = [_job("Underpaid", "Creative Technologist", "mid", 0.95)]
    jobs[0]["analysis"]["salary"] = {"max": 9000.0, "period": "annual"}
    config = dict(CONFIG, min_salary_gbp=26000)
    assert selection.stretch_jobs(config, jobs) == []


def test_ranking_is_by_skills_not_composite():
    """The posting with the best composite is NOT the one to promote: for a
    filtered job that number is mostly a TF-IDF stand-in for a score no model
    produced."""
    jobs = [
        _job("HighComposite", "Designer", "senior", skills=0.20, composite=0.95),
        _job("HighSkills", "Designer", "senior", skills=0.80, composite=0.20),
    ]
    picked = selection.stretch_jobs(dict(CONFIG, stretch_top_count=1), jobs)
    assert [j["company"] for j in picked] == ["HighSkills"]


def test_the_cap_bounds_the_spend():
    jobs = [_job(f"C{i}", "Designer", "senior", skills=i / 100) for i in range(40)]
    assert len(selection.stretch_jobs(dict(CONFIG, stretch_top_count=5), jobs)) == 5


def test_zero_switches_the_tier_off():
    jobs = [_job("ITG", "Creative Technologist", "senior", 0.9)]
    assert selection.stretch_jobs(dict(CONFIG, stretch_top_count=0), jobs) == []


def test_the_report_flags_the_stretch_without_hiding_the_rejection():
    """A stretch job must never read as one that passed: the flag is additive,
    and filter_status/filter_reason stay exactly as they were."""
    job = _job("ITG", "Creative Technologist/AI Specialist", "senior", 0.64)
    job["_filter_reason"] = "level 'senior' not in allowed levels"
    matcher.set_stretch_urls([job["url"]])
    try:
        report = matcher.generate_match_report(job, _full_match(job))
    finally:
        matcher.set_stretch_urls([])
    assert "stretch: true" in report
    assert 'filter_status: "filtered"' in report
    assert "filter_reason:" in report


def test_a_passing_job_never_gets_the_stretch_flag():
    job = _job("Fine", "Creative Technologist", "mid", 0.9)
    matcher.set_stretch_urls([job["url"]])
    try:
        report = matcher.generate_match_report(job, _full_match(job))
    finally:
        matcher.set_stretch_urls([])
    assert "stretch: true" not in report


def _full_match(job):
    """A real score dict, built the cheap way.

    Hand-rolling one means chasing whichever key the report renderer indexes
    into next; skip_llm_context=True is the pipeline's own no-model path, so it
    produces the true shape and reaches no provider.
    """
    return matcher.analyze_match(job, selection.load_config(), skip_llm_context=True)
