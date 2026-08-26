"""match_all must survive a failing job and report progress.

Both properties were missing from every matching pass. analyze_match reaches the
LLM for context scoring, so it raises whenever the provider chain is exhausted —
an ordinary end-state after a bulk day, not an exceptional one. Unguarded, one
job's failure discarded the scoring of the entire batch.

The progress output matters as much: a silent loop over 1000 jobs runs for more
than an hour with no output, which is indistinguishable from a hung process. That
ambiguity produced three false "the process died" reports in a single session
while the process was simply waiting on the API.
"""
import run


def _jobs(n):
    return [{"title": f"Job {i}", "company": "Acme"} for i in range(n)]


def test_one_failure_does_not_lose_the_batch(monkeypatch, capsys):
    def flaky(job, _config, **_k):
        if job["title"] == "Job 3":
            raise RuntimeError("all providers exhausted")
        return {"composite_score": 0.5}

    monkeypatch.setattr(run, "analyze_match", flaky)
    jobs = _jobs(6)
    fails = run.match_all(jobs, {})
    assert fails == 1
    scored = [j for j in jobs if j["match"].get("composite_score")]
    assert len(scored) == 5, "the five jobs that succeeded must keep their scores"


def test_failed_job_gets_an_empty_match_not_a_missing_key(monkeypatch):
    """Downstream code indexes job["match"]; a missing key would turn one failure
    into a KeyError somewhere else entirely."""
    monkeypatch.setattr(run, "analyze_match",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    jobs = _jobs(1)
    run.match_all(jobs, {})
    assert jobs[0]["match"] == {}


def test_progress_is_reported_so_a_long_run_is_not_silent(monkeypatch, capsys):
    monkeypatch.setattr(run, "analyze_match", lambda *_a, **_k: {"composite_score": 0.5})
    run.match_all(_jobs(250), {})
    out = capsys.readouterr().out
    assert "100/250 matched" in out
    assert "200/250 matched" in out
    assert "250/250 matched" in out, "the final tally must always print"


def test_small_batch_still_reports_once(monkeypatch, capsys):
    """A 7-job batch must not be silent just because it never reaches 100."""
    monkeypatch.setattr(run, "analyze_match", lambda *_a, **_k: {"composite_score": 0.5})
    run.match_all(_jobs(7), {})
    assert "7/7 matched" in capsys.readouterr().out


def test_failures_are_summarised_with_the_recovery_command(monkeypatch, capsys):
    monkeypatch.setattr(run, "analyze_match",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    run.match_all(_jobs(2), {})
    out = capsys.readouterr().out
    assert "2/2 jobs left without a match score" in out
    assert "--reanalyze" in out


def test_only_first_three_failures_print_in_full(monkeypatch, capsys):
    """Ten thousand identical tracebacks would bury the summary."""
    monkeypatch.setattr(run, "analyze_match",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    run.match_all(_jobs(10), {})
    assert capsys.readouterr().out.count("failed for") == 3


def test_kwargs_reach_analyze_match(monkeypatch):
    """The reanalyze pass calls with skip_summary=True; dropping it would silently
    re-pay for LLM job summaries on every job.

    match_all now also decides skip_llm_context per job — a filter reject is not
    worth an LLM context call — so that kwarg arrives ALONGSIDE the caller's, not
    instead of it. Pinning the whole dict made this test fail on a change that was
    correct; pin the kwarg the caller paid for, and that the per-job one is still
    being passed at all.
    """
    seen = {}
    monkeypatch.setattr(run, "analyze_match",
                        lambda job, cfg, **k: seen.update(k) or {"composite_score": 1})
    run.match_all(_jobs(1), {}, skip_summary=True)
    assert seen.get("skip_summary") is True, seen
    assert "skip_llm_context" in seen, seen
