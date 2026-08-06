"""Nightly review must select by rank in the pool, not by an absolute score.

Review used to fire on composite_score >= REVIEW_MIN (0.80), a hand-rolled
floor, while generation already went through selection.select_top() on a
configured percentile. Switched 2026-08-06 to select_top("review", ...) so both
stages rank the same pool the same way, governed by
config.yaml:review_top_percent.

The cut is on composite_score rank alone. Review scores cannot feed back into
it — a document has no review score until it has been reviewed — so these tests
check ordering behaviour, never a relationship between the two scores.
"""
import nightly_scout
import selection


def _job(company, title, score, url=None):
    desc = (
        "We are looking for a designer to join the team. Responsibilities "
        "include shipping product work end to end and partnering with "
        "engineering. Requirements: portfolio, Figma, and prior experience. "
    ) * 4
    return {
        "company": company, "title": title, "description": desc,
        "url": url or f"https://example.com/{company}-{title}".replace(" ", "-"),
        "match": {"composite_score": score},
    }


def test_low_score_job_is_selected_when_it_ranks_in_the_top_percent():
    # A pool where 0.31 is genuinely near the top — the exact shape that an
    # absolute REVIEW_MIN floor would reject outright regardless of rank.
    jobs = [_job(f"Co{i}", f"Role{i}", s) for i, s in
            enumerate([0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.28, 0.31])]
    config = {"review_top_percent": 40, "match_score_threshold": 0}
    top = selection.select_top("review", config, jobs=jobs)
    assert any(j["match"]["composite_score"] == 0.31 for j in top), (
        "the highest-ranked job in the pool must be selected for review "
        "even though 0.31 would fail any absolute floor near 0.70-0.80"
    )


def test_high_score_job_is_excluded_when_the_pool_is_all_high_scores():
    # The mirror case: an absolute floor would review everything here; the
    # percentile must still cut the bottom of the pool.
    jobs = [_job(f"Co{i}", f"Role{i}", s) for i, s in
            enumerate([0.99, 0.97, 0.95, 0.93, 0.91, 0.89, 0.87, 0.85, 0.83, 0.81])]
    config = {"review_top_percent": 40, "match_score_threshold": 0}
    top = selection.select_top("review", config, jobs=jobs)
    assert not any(j["match"]["composite_score"] == 0.81 for j in top), (
        "the lowest-ranked job must be excluded even at 0.81, well above any "
        "absolute floor this project has used"
    )
    assert len(top) < len(jobs)


def test_nightly_scout_no_longer_defines_an_absolute_review_floor():
    assert not hasattr(nightly_scout, "REVIEW_MIN"), (
        "REVIEW_MIN is back — review selection has regressed to an absolute "
        "composite_score floor instead of selection.select_top('review', ...)"
    )


def test_review_loop_still_checks_gen_version_is_locked():
    """select_top("review", ...) ranks purely on composite_score — it has no
    idea a job is applied or expired, and 17 of the 488 jobs it currently
    selects are (Wordsmith AI Product Designer among them, score 0.89). The
    lock check inside the per-job loop is what actually stops those from being
    re-reviewed; this only guards that the call was not dropped when the
    selection mechanism changed."""
    import ast
    import pathlib
    src = pathlib.Path(nightly_scout.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    called = {n.func.attr for n in ast.walk(main)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "is_locked"}
    assert "is_locked" in called, (
        "gen_version.is_locked is no longer called in the review loop — "
        "applied/expired jobs would be re-reviewed"
    )


def test_nightly_scout_review_gate_uses_select_top():
    import ast
    import pathlib
    src = pathlib.Path(nightly_scout.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    called_names = {
        n.func.id for n in ast.walk(main)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    } | {
        n.func.attr for n in ast.walk(main)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "select_top" in called_names, (
        "nightly_scout.main() no longer calls select_top — review selection "
        "may have reverted to a hand-rolled threshold"
    )
