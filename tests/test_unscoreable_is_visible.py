"""A posting held out of generation must say so in its own report.

`scoreable` in the frontmatter tested description_truncated alone — the Adzuna
case — while selection.is_unscoreable, which actually decides whether anything
downstream acts on the job, also rejects a description that is too short or is
junk. So a posting held out for being short still reported `scoreable: true`.

"PODFather — Product Designer" is the one that surfaced it: match_score 0.79,
`scoreable: true`, no CV, no cover letter, no review, and a 313-character body
reading "This vacancy has now been filled. If you are interested in joining the
Podfather team use our Contact Us form". Nothing in the report said why the
pipeline had skipped it, so the only way to find out was to read the code. 563
postings above threshold were in that state.

The score itself is left in place. It is real arithmetic over thin evidence, and
removing it would hide that the posting was seen at all — the honest form is to
print the number and say it is not trusted.
"""
import matcher
import pytest


def _job(description="x" * 4000, **kw):
    job = {
        "title": "Product Designer",
        "company": "Example",
        "location": "Edinburgh",
        "url": "https://example.com/1",
        "description": description,
        "analysis": {"experience_level": "mid", "skills": []},
    }
    job.update(kw)
    return job


def test_a_short_description_is_flagged_not_just_a_truncated_one():
    """The regression. 313 characters is below MIN_REVIEWABLE_DESC, and nothing
    downstream will touch the job, so the report must not claim it is
    scoreable."""
    assert matcher._is_summary_only(_job(description="short body. " * 20)) is True


def test_a_truncated_api_summary_is_still_flagged():
    """The case the flag already handled — it must survive the widening."""
    assert matcher._is_summary_only(_job(description_truncated=True)) is True


def test_a_full_description_is_not_flagged():
    assert matcher._is_summary_only(_job()) is False


def test_the_flag_agrees_with_the_stage_that_actually_skips_the_job():
    """Two implementations of one question is how they drifted apart. The report
    must mirror selection.is_unscoreable, not approximate it."""
    from selection import is_unscoreable
    for job in (_job(), _job(description="tiny"), _job(description_truncated=True)):
        assert matcher._is_summary_only(job) == is_unscoreable(job)


@pytest.mark.parametrize("job,marker", [
    (_job(description="This vacancy has now been filled. " * 4), "本文が"),
    (_job(description_truncated=True), "APIの要約"),
])
def test_the_report_says_why_no_documents_were_generated(job, marker, tmp_path, monkeypatch):
    """Not just a false flag in the frontmatter — a human reading the report
    should not have to open the source to learn why there is no CV."""
    monkeypatch.setattr(matcher, "read_review_scores", lambda base: {})
    report = matcher.generate_match_report(
        job,
        {"composite_score": 0.79, "tier": "🟡 Good Match",
         "skills": {"score": 0.5, "matched": [], "partial": [], "missing": []},
         "experience": {"score": 0.9, "job_level": "mid", "note": ""},
         "location": {"score": 1.0, "notes": []},
         "salary": {"score": 0.6, "note": ""},
         "context_score": 0.8, "context_reasoning": "",
         "weights": {"skills": 0.2, "experience": 0.05, "location": 0.1,
                     "salary": 0.01, "context": 0.64}},
        expired=False, applied=False,
    )
    assert "scoreable: false" in report
    assert "CV・カバーレターは生成されません" in report, (
        "the report shows a score and no explanation of why nothing was generated"
    )
    assert marker in report, "the warning should name the specific reason"


def test_a_normal_posting_gets_no_such_warning(monkeypatch):
    monkeypatch.setattr(matcher, "read_review_scores", lambda base: {})
    report = matcher.generate_match_report(
        _job(),
        {"composite_score": 0.79, "tier": "🟡 Good Match",
         "skills": {"score": 0.5, "matched": [], "partial": [], "missing": []},
         "experience": {"score": 0.9, "job_level": "mid", "note": ""},
         "location": {"score": 1.0, "notes": []},
         "salary": {"score": 0.6, "note": ""},
         "context_score": 0.8, "context_reasoning": "",
         "weights": {"skills": 0.2, "experience": 0.05, "location": 0.1,
                     "salary": 0.01, "context": 0.64}},
        expired=False, applied=False,
    )
    assert "scoreable: true" in report
    assert "生成されません" not in report
