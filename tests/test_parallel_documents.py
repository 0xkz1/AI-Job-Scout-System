"""CV/CL generation and review are LLM work, and they were the serial tail.

Measured 2026-08-22 while the backlog drain was generating: 11 CVs and 11 letters
in an hour — ~5.5 minutes per job, one job at a time. 341 documents were waiting
for review behind that. Since review is the LAST stage, a high-scoring posting
(Pony Visual Designer, composite 0.82, rank 33 of 4492) had its CV and letter
written and still could not be reviewed, because the stage had not had a turn.

Two things must survive making these concurrent:

  - the ORDER in which jobs claim their filenames. `base` is disambiguated
    against seen_bases as the loop walks, so which file a job owns depends on
    the jobs before it. Only the provider calls may move off that path.
  - the refusal to overwrite. Existing documents are never rewritten here (a
    hand-edited CV would be lost), so the existence check has to stay ahead of
    the generation, not race it.
"""
import inspect
from pathlib import Path

import pytest

import nightly_scout
import run

ROOT = Path(__file__).resolve().parent.parent


def _generate_outputs_src():
    return inspect.getsource(run.generate_outputs)


def test_documents_are_written_in_a_pool():
    assert "ThreadPoolExecutor" in _generate_outputs_src()


def test_the_pool_is_the_configured_width():
    assert 'config.get("analysis_workers")' in _generate_outputs_src()


def test_filenames_are_still_claimed_in_order():
    """seen_bases makes `base` depend on the jobs before it. Moving that into
    the pool would hand two jobs the same file on a different run each time."""
    src = _generate_outputs_src()
    loop = src[src.index("for job in jobs:"):src.index("_doc_tasks:\n")]
    assert "seen_bases.add(base)" in loop
    assert "ThreadPoolExecutor" not in loop


def test_the_expensive_calls_left_the_loop():
    """generate_cv/save_cover_letter inside the loop is what made it serial."""
    src = _generate_outputs_src()
    loop = src[src.index("for job in jobs:"):src.index("--- The expensive half")]
    assert "generate_cv(" not in loop
    assert "save_cover_letter(" not in loop


def test_an_existing_document_is_never_queued():
    """The overwrite guard has to sit in the ordered pass. Checking inside the
    worker would let two runs race on the same absent file."""
    src = _generate_outputs_src()
    loop = src[src.index("for job in jobs:"):src.index("--- The expensive half")]
    assert "want_cv = not os.path.exists(cv_path)" in loop
    assert "want_cl = not os.path.exists(cl_path)" in loop


def test_a_letter_failure_does_not_lose_the_cv():
    """The assembler refuses rather than emitting a letter with no identity
    block. That refusal must stay per job, not end the batch."""
    src = _generate_outputs_src()
    worker = src[src.index("def _write_documents"):src.index("_workers = max(")]
    assert "except Exception as e:" in worker
    assert "cl_error" in worker


def test_a_task_carries_only_what_the_worker_needs():
    src = _generate_outputs_src()
    assert '"cv_path": cv_path if want_cv else None' in src
    assert '"cl_path": cl_path if want_cl else None' in src


# --- the review stage ---

def _review_src():
    return inspect.getsource(nightly_scout.main)


def test_reviews_run_in_a_pool():
    assert "ThreadPoolExecutor" in _review_src()


def test_review_selection_stays_serial_and_local():
    """Existence, the lock marker and the stored-hash check are file reads. Doing
    them up front keeps the paid loop to one flat list."""
    src = _review_src()
    sel = src[src.index("pending: list = []"):src.index("def _review_one")]
    assert "gen_version.is_locked" in sel
    assert "review_is_current" in sel
    assert "run_review(" not in sel  # the comment names it; the call must not be here


def test_a_locked_document_is_never_reviewed():
    """run_review writes a backlink into the document, and a verdict on a
    submitted or closed application is advice that can no longer be taken."""
    src = _review_src()
    sel = src[src.index("pending: list = []"):src.index("def _review_one")]
    assert "continue" in sel[sel.index("gen_version.is_locked"):]


def test_one_failed_review_does_not_sink_the_batch():
    src = _review_src()
    worker = src[src.index("def _review_one"):src.index("workers = max(")]
    assert "except Exception as e:" in worker
    assert "return base, kind, False" in worker


def test_the_ready_count_is_tallied_after_the_pool():
    """`ready_count += 1` from several threads loses increments, and that number
    is what the notification reports as submittable."""
    src = _review_src()
    tail = src[src.index("for base, kind, ready, err in results:"):]
    assert "ready_count += 1" in tail
    worker = src[src.index("def _review_one"):src.index("workers = max(")]
    assert "ready_count" not in worker


# --- reviewing at generation time ---
#
# Reviews were the last stage, and the stage only looked at jobs NEW in that run.
# So a document could be written and never reviewed at all: 341 were waiting on
# 2026-08-22, and Pony Visual Designer (composite 0.82, rank 33 of 4492) held a
# CV and a letter with no verdict — the number that decides whether to apply.

def test_generation_reviews_what_it_wrote():
    assert "_review_generated(" in _generate_outputs_src()


def test_it_can_be_switched_off():
    assert 'config.get("review_on_generation"' in _generate_outputs_src()


def test_the_gate_is_an_absolute_score_not_a_rank():
    """Every job is scored by this point, so a rank exists — but a floor is what
    makes the set independent of how the rest of the pool happened to land."""
    src = _generate_outputs_src()
    assert 'config.get("review_on_generation_min"' in src
    assert "select_top" not in src[src.index("--- Review what was just written"):]


def test_documents_are_reviewed_best_first():
    """If the slot runs out, the reviews that ran should be the ones worth
    reading."""
    src = _generate_outputs_src()
    tail = src[src.index("--- Review what was just written"):]
    assert "_to_review.sort(" in tail
    assert "reverse=True" in tail


def test_the_review_set_is_a_superset_of_the_generation_set():
    """The reason reviewing here bypasses no selection: both stages rank the same
    pool with the same floor, and review takes the wider slice. If these ever
    invert, generation would start producing documents that review would not
    have chosen."""
    import selection
    c = selection.load_config()
    assert selection.stage_percent(c, "review") >= selection.stage_percent(c, "generation")


def test_a_locked_document_is_not_reviewed_here_either():
    src = inspect.getsource(run._review_generated)
    assert "gen_version.is_locked" in src


def test_an_already_current_review_is_not_paid_for_twice():
    """nightly_scout sweeps afterwards; without this the same document would be
    reviewed once here and once there."""
    assert "review_is_current" in inspect.getsource(run._review_generated)


def test_a_review_failure_cannot_cost_the_run_its_documents():
    """The CVs, letters and match reports are already on disk when this runs. A
    provider outage must not turn that into a failed run."""
    import re
    src = inspect.getsource(run._review_generated)
    assert "return 0" in src
    # the docstring says "never raised"; what matters is that no statement does
    assert not re.search(r"^\s*raise\b", src, re.M)


def test_reviews_here_run_in_the_same_pool():
    assert "ThreadPoolExecutor" in inspect.getsource(run._review_generated)


def test_the_stretch_tier_is_reviewed_regardless_of_the_floor():
    """The stretch tier buys documents for one reason: so the CV review exists
    for a posting the level gate rejected. Measured 2026-08-22, that reason was
    not being served — 15 stretch jobs, 15 CVs, 0 reviews, one at composite 0.84.

    nightly_scout cannot do it: it ranks filter-passed jobs, and a stretch job is
    filtered by definition. And a floor on composite is the wrong instrument,
    because the level rejection is what depressed that composite."""
    src = _generate_outputs_src()
    tail = src[src.index("--- Review what was just written"):]
    assert "id(t[\"job\"]) in stretch_ids" in tail


def test_the_stretch_tier_is_outside_the_review_selection():
    """The fact that makes the exemption necessary rather than generous."""
    import json
    import selection
    jobs = json.loads((ROOT / "10_output" / "_analyzed.json").read_text(encoding="utf-8")) \
        if (ROOT / "10_output" / "_analyzed.json").exists() else None
    if not jobs:
        pytest.skip("no analysed DB to measure against")
    c = selection.load_config()
    stretch = selection.stretch_jobs(c, jobs)
    if not stretch:
        pytest.skip("no stretch jobs in the current pool")
    review_ids = {id(j) for j in selection.select_top("review", c, jobs=jobs)}
    assert not any(id(j) in review_ids for j in stretch), (
        "a stretch job reached the review set; the exemption may now be "
        "double-reviewing what nightly_scout already covers"
    )


def test_reviewing_at_generation_cannot_review_more_than_the_old_rule():
    """The whole safety argument in one assertion: what generation writes is a
    subset of what review would have selected, so moving the review earlier
    changes when it happens, never how much of it happens."""
    import json
    import selection
    path = ROOT / "10_output" / "_analyzed.json"
    if not path.exists():
        pytest.skip("no analysed DB to measure against")
    jobs = json.loads(path.read_text(encoding="utf-8"))
    c = selection.load_config()
    gen = {id(j) for j in selection.select_top("generation", c, jobs=jobs)}
    rev = {id(j) for j in selection.select_top("review", c, jobs=jobs)}
    assert gen <= rev
