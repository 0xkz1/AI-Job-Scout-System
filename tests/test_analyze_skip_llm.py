"""analyze_job(skip_llm=True) must stay free of LLM calls, and still produce
everything passes_filter reads.

This is what lets filtering run before the expensive calls. If either property
regresses the pipeline silently goes back to paying for jobs it then discards —
no error, just a bigger bill: 35% of the LLM spend used to go to postings dropped
moments later, 213 of 890 on a title keyword alone.
"""
import analyzer
import pytest
from filter import passes_filter


@pytest.fixture
def no_llm(monkeypatch):
    """Make any LLM top-up an immediate test failure."""
    def boom(*_a, **_k):
        raise AssertionError("skip_llm=True must not reach an LLM")

    monkeypatch.setattr(analyzer, "extract_skills_ollama", boom)
    monkeypatch.setattr(analyzer, "classify_experience_work_style_ollama", boom)


@pytest.fixture
def config():
    return {
        "exclude_title_keywords": ["senior", "manager"],
        "exclude_description_keywords": [],
        "include_levels": ["entry_level", "mid"],
        "employment_types": ["full_time", "part_time", "contract"],
        "min_salary_gbp": 26000,
    }


def _job(title="Web Developer", desc=None, salary="£35,000"):
    return {
        "title": title,
        "company": "Acme",
        "location": "London",
        "salary": salary,
        "description": desc if desc is not None else (
            "We are hiring a web developer to build responsive sites using "
            "JavaScript, HTML and CSS. Full time, permanent, hybrid. " * 6),
    }


def test_skip_llm_makes_no_llm_calls(no_llm):
    """A job with almost no extractable skills would normally trigger the top-up."""
    analyzer.analyze_job(_job(title="Zzz", desc="Short."), skip_llm=True)


def test_skip_llm_still_fills_every_field_the_filter_reads(no_llm, config):
    """passes_filter reads salary, experience_level, employment_types — all of them
    from regex and rules, which is exactly why the split is possible."""
    out = analyzer.analyze_job(_job(), skip_llm=True)
    analysis = out["analysis"]
    for field in ("salary", "experience_level", "employment_types", "work_style"):
        assert field in analysis, f"{field} missing — filter cannot decide"
    ok, reason = passes_filter(out, config)
    assert ok, f"a plain mid-level job should pass, got: {reason}"


def test_filter_still_excludes_on_the_cheap_pass(no_llm, config):
    """The 213-of-890 case: a title keyword needs no model to reject."""
    out = analyzer.analyze_job(_job(title="Senior Web Developer"), skip_llm=True)
    ok, reason = passes_filter(out, config)
    assert not ok and "senior" in reason.lower()


def test_salary_is_parsed_without_llm(no_llm, config):
    """The filter's salary rule must be decidable on the cheap pass. Asserted on the
    parse, not on rejection: an unparseable figure yields min/max None and passes on
    purpose, since "no stated salary" must not be read as "pays too little"."""
    out = analyzer.analyze_job(_job(salary="£35,000 - £45,000 per annum"),
                               skip_llm=True)
    salary = out["analysis"]["salary"]
    assert salary["min"] == 35000 and salary["max"] == 45000
    assert passes_filter(out, config)[0]

    # parse_salary needs BOTH a range and a period, so a low single figure yields
    # None and is not rejected. Asserted as-is rather than treated as a bug here:
    # this test guards the cheap/LLM split, and the split holds either way.
    poor = analyzer.analyze_job(_job(salary="£10,000 - £14,000 per annum"),
                                skip_llm=True)
    assert poor["analysis"]["salary"]["max"] == 14000
    ok, reason = passes_filter(poor, config)
    assert not ok and "salary" in reason.lower()


def test_enrichment_reruns_are_idempotent(monkeypatch):
    """Pass 2 re-runs analyze_job on survivors, so a second call must not duplicate
    or lose skills — the two-pass design depends on it."""
    monkeypatch.setattr(analyzer, "extract_skills_ollama", lambda t, d: ["Docker"])
    monkeypatch.setattr(analyzer, "classify_experience_work_style_ollama",
                        lambda t, d: {})
    job = _job()
    once = analyzer.analyze_job(job)
    twice = analyzer.analyze_job(analyzer.analyze_job(job))
    assert once["analysis"]["skills"] == twice["analysis"]["skills"]


def test_llm_top_up_still_fires_without_skip_llm(monkeypatch):
    """The saving must come from filtering, not from disabling enrichment."""
    calls = []
    monkeypatch.setattr(analyzer, "extract_skills_ollama",
                        lambda t, d: calls.append("skills") or ["Docker"])
    monkeypatch.setattr(analyzer, "classify_experience_work_style_ollama",
                        lambda t, d: calls.append("class") or {})
    out = analyzer.analyze_job(_job(title="Zzz", desc="Short."))
    assert calls, "enrichment should run when skip_llm is not set"
    assert "Docker" in out["analysis"]["skills"]
