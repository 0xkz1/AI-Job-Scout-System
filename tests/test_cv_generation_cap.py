"""The CV cap must limit how much a run writes, not which ranks it can reach.

config.yaml calls cv_generation_limit a "safety cap on how many NEW CVs one run
may generate" that "guards against a huge first run". It did not do that. It
sliced the ranked list at 150 and generated only within that slice, while the
write itself is guarded by `if not os.path.exists(cv_path)` — so once the top
150 all had CVs, every run selected the same 150, wrote nothing, and handed the
unused slots back instead of passing them down the ranking.

Measured on the live database when this was found: the generation set held 491
jobs, 317 with a CV and 174 without. The old rule would have written 0 CVs that
night and left all 174 permanently unreachable. "Synechron Graphic Designer" sat
at rank 437 of 1,636 — inside the top 30%, above threshold, 137th in the queue
of jobs awaiting a document — and no number of runs would have reached it.

Skipping jobs that already have a CV costs no overwrite protection, because
run.py never regenerates an existing document by design (its own docstring:
"Existing CV/CL files are never overwritten (manual edits are preserved)").
Regeneration belongs to regen_top_docs.py — the same split as nightly_scout.py
for new reviews versus rereview_top.py for the backlog.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _generation_block() -> str:
    """The lines that decide which jobs this run may write a CV for."""
    text = (ROOT / "run.py").read_text(encoding="utf-8")
    start = text.index("cv_limit = config.get(\"cv_generation_limit\"")
    return text[start:start + 1800]


def test_the_cap_counts_pending_documents_not_ranks():
    block = _generation_block()
    assert "os.path.exists" in block, (
        "the cap is applied without asking whether a CV already exists, so it "
        "re-selects the same top N every run and never descends the ranking"
    )


def test_the_cap_is_not_a_bare_slice_of_the_ranked_list():
    """`select_top(...)[:cv_limit]` is the shape of the bug: it cuts by rank."""
    block = _generation_block()
    bare_slice = re.search(r"select_top\([^)]*\)\s*\[:\s*cv_limit\s*\]", block)
    assert not bare_slice, (
        "the eligible set is a rank slice; everything below cv_limit is then "
        "unreachable no matter how many times the pipeline runs"
    )


def test_run_py_still_refuses_to_overwrite_an_existing_document():
    """The reason the change above is safe. If this ever stops being true, the
    cap change would start silently regenerating hand-edited CVs."""
    text = (ROOT / "run.py").read_text(encoding="utf-8")
    assert "if not os.path.exists(cv_path):" in text
    assert "if not os.path.exists(cl_path):" in text


def test_regeneration_has_its_own_tool():
    """Overwriting is a separate job, deliberately. Without this the cap change
    would look like it removed the ability to refresh documents."""
    assert (ROOT / "regen_top_docs.py").exists(), (
        "nothing regenerates existing CVs; run.py will not, by design"
    )


@pytest.mark.parametrize("total,already,cap,expect_written", [
    (491, 317, 150, 150),   # the live case: 174 pending, cap writes 150
    (200, 190, 150, 10),    # fewer pending than the cap — write them all
    (100, 100, 150, 0),     # nothing pending — nothing to write
    (500, 0, 150, 150),     # a first run — the case the cap exists for
])
def test_the_cap_writes_what_it_promises(total, already, cap, expect_written):
    """The arithmetic the fix restores, independent of run.py's plumbing: a run
    writes min(cap, pending), never min(cap, rank) — which is 0 whenever the top
    of the ranking is already served."""
    selected = list(range(total))
    has_cv = set(selected[:already])
    pending = [j for j in selected if j not in has_cv]
    assert len(pending[:cap]) == expect_written

    old_rule = [j for j in selected[:cap] if j not in has_cv]
    if already >= cap:
        assert not old_rule, "the old rule writes nothing once the top N is served"
