"""A score is only worth buying again when the persona actually moved.

context_persona_chars stamps a score with the persona that produced it, which is
what makes staleness detectable at all. Compared for exact equality it also
makes every score stale on any edit: writing one line of effective years into
timeline.md grew the persona 54,260 -> 55,048 characters, +1.4%, and marked all
1,642 eligible postings due for a rescore.

That rescore was measured before it was stopped. Of 162 postings redone, 102
came back identical to two decimal places and the mean absolute change was
0.0246 — below the run-to-run variance of the model itself. The remaining 1,480
would have been several nights of LLM spend to mostly reproduce the numbers
already on disk.

The threshold separates the two cases that matter. Adding the portfolio grew the
persona 25,429 -> 54,260, +113%: a different document, and rescoring against it
changed real conclusions. A +1.4% edit is the same document. Postings never
scored against any persona stay due either way — those are newly ingested ones
carrying no score from the current persona at all, which is a different thing
from carrying a slightly older one.
"""
import rescore_context
from rescore_context import _is_stale
import pytest


def test_a_posting_never_scored_is_always_due():
    """No stamp means no score from any recent persona — usually a fresh
    ingest. National Westminster Bank's UI Software Engineer sat at composite
    0.80, top of the pool, in exactly this state."""
    assert _is_stale(None, 55048) is True


def test_an_exact_match_is_never_due():
    assert _is_stale(55048, 55048) is False


@pytest.mark.parametrize("stamped,current,due,label", [
    (54260, 55048, False, "+1.4% — one line of effective years"),
    (55048, 52000, False, "-5.5% — a trimmed paragraph"),
    (25429, 54260, True, "+113% — the portfolio added"),
    (55048, 49000, True, "-11% — a document removed"),
])
def test_only_a_real_edit_makes_a_stored_score_stale(stamped, current, due, label):
    assert _is_stale(stamped, current) is due, label


def test_the_threshold_sits_above_the_measured_noise():
    """Anchored to data, not taste: the +1.4% edit produced a mean absolute
    score change of 0.0246 with 63% of postings unchanged, so anything at that
    scale must not trigger a rescore."""
    assert 0.02 < rescore_context.PERSONA_DRIFT_THRESHOLD < 0.5
    assert not _is_stale(54260, 55048), (
        "the edit that exposed this must not be treated as a persona change"
    )


def test_drift_is_measured_in_both_directions():
    """Deleting half the persona is as much a change as doubling it."""
    grew = _is_stale(50000, 60000)
    shrank = _is_stale(60000, 50000)
    assert grew and shrank, "shrinking the persona also invalidates its scores"


def test_the_selection_shrinks_to_the_genuinely_unscored(monkeypatch):
    """End to end over `due`, with the filter stubbed out: given a corpus mixing
    never-scored, slightly-older and current postings, only the first group
    should come back."""
    monkeypatch.setattr(rescore_context, "passes_filter", lambda j, c: (True, ""))
    monkeypatch.setattr(rescore_context.selection, "is_unscoreable", lambda j: False)

    def job(stamp):
        return {"url": f"u{stamp}", "match": {"context_score": 0.5,
                                              "context_persona_chars": stamp}}

    jobs = [job(None), job(None), job(54260), job(55048), job(25429)]
    out = rescore_context.due(jobs, {}, persona_chars=55048)
    stamps = [j["match"]["context_persona_chars"] for j in out]
    assert stamps.count(None) == 2, "never-scored postings must be included"
    assert 54260 not in stamps, "a +1.4% difference is not a reason to pay again"
    assert 25429 in stamps, "a persona that doubled must invalidate its scores"
