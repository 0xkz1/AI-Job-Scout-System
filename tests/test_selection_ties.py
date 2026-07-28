"""The top-N% boundary must never split a group of equally-scored jobs.

Composite scores are quantised to 2 decimals, so equal scores arrive in blocks —
19 jobs sat on exactly 0.5400 in the live 665-job pool. A plain ranked[:k] slice
cuts through whichever block the boundary lands in, and because the sort is
stable the winners are decided by row order in _analyzed.json. That is how
excluding 54 off-trade titles pushed 16 already-generated jobs, every one of them
on 0.54, out of the generation set while same-score jobs stayed in.
"""
import selection


def _job(score, i):
    # Long enough to clear MIN_REVIEWABLE_DESC and read as prose, so is_unscoreable
    # and is_junk_description both pass and the job reaches ranking.
    desc = (
        f"We are looking for a designer to join the team. Responsibilities "
        f"include shipping product work end to end and partnering with "
        f"engineering. Requirements: portfolio, Figma, and prior experience. "
    ) * 4
    return {
        "company": f"Co{i}",
        "title": f"Designer {i}",
        "description": desc,
        "match": {"composite_score": score},
    }


def _pool(scores):
    return [_job(s, i) for i, s in enumerate(scores)]


CONFIG = {"generation_top_percent": 30, "match_score_threshold": 0}


def test_boundary_inside_a_tie_block_keeps_the_whole_block():
    # 10 jobs, top 30% = 3, but ranks 2..6 all score 0.54.
    scores = [0.90, 0.54, 0.54, 0.54, 0.54, 0.54, 0.40, 0.30, 0.20, 0.10]
    top = selection.select_top("generation", CONFIG, jobs=_pool(scores))
    assert [j["match"]["composite_score"] for j in top] == [0.90] + [0.54] * 5


def test_tie_selection_does_not_depend_on_input_order():
    scores = [0.90, 0.54, 0.54, 0.54, 0.54, 0.54, 0.40, 0.30, 0.20, 0.10]
    jobs = _pool(scores)
    forward = {j["title"] for j in selection.select_top("generation", CONFIG, jobs=jobs)}
    reverse = {j["title"] for j in selection.select_top("generation", CONFIG, jobs=jobs[::-1])}
    assert forward == reverse


def test_distinct_scores_still_cut_at_exactly_the_percentage():
    # No ties, so tie-inclusion must not widen the set at all.
    scores = [0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50, 0.45]
    top = selection.select_top("generation", CONFIG, jobs=_pool(scores))
    assert [j["match"]["composite_score"] for j in top] == [0.90, 0.85, 0.80]


def test_floor_still_trims_a_tie_block_it_covers():
    # match_score_threshold is a quality guard and outranks tie-inclusion: pulling
    # in the rest of a block must not smuggle sub-floor jobs into generation.
    scores = [0.90, 0.54, 0.54, 0.54, 0.54, 0.54, 0.40, 0.30, 0.20, 0.10]
    config = {"generation_top_percent": 30, "match_score_threshold": 0.60}
    top = selection.select_top("generation", config, jobs=_pool(scores))
    assert [j["match"]["composite_score"] for j in top] == [0.90]


def test_a_single_all_tied_pool_selects_everything():
    # Degenerate but reachable on a small pool: no basis to prefer any of them.
    top = selection.select_top("generation", CONFIG, jobs=_pool([0.54] * 8))
    assert len(top) == 8


def test_empty_pool_is_still_empty():
    assert selection.select_top("generation", CONFIG, jobs=[]) == []
