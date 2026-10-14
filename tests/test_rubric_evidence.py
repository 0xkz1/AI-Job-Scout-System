"""verify_rubric_evidence — a Strong rubric row has to quote the CV, and the
quote has to be in it. The rubric IS the score, so an unsupported Strong is 14
points that reach apply_priority through cv_review_score."""

from reviewer import _extract_score, verify_rubric_evidence

CV = """# CV
**Skills:** Python, Docker / Docker Compose
• Built a Multi-Provider LLM Orchestration layer with automatic fallback
  across cloud providers and a local Ollama instance.
"""


def _rubric(rows: str) -> str:
    return f"```yaml\nrubric:\n{rows}```\n\n### 総評\nprose\n"


def test_a_quote_that_is_not_in_the_cv_is_downgraded():
    """The Meltwater case: a posting naming NLP, Transformers, fine-tuning and
    transfer learning throughout scored Strong on exactly that requirement,
    against a CV containing none of those words in any form."""
    body = _rubric('  - requirement: "NLP/Transformer"\n'
                   '    evidence: "Strong"\n'
                   '    evidence_quote: "Fine-tuned BERT for entity recognition"\n')

    fixed, demoted = verify_rubric_evidence(body, CV)

    assert demoted == ["NLP/Transformer"]
    assert "evidence: Weak" in fixed
    assert "downgraded_from: Strong" in fixed


def test_a_quote_the_cv_really_carries_survives_its_markdown():
    """The CV is markdown, so a model reliably drops the bold markers and
    reflows the line. Matching is normalised for that, the way finding quotes
    already are — otherwise the guard rejects true evidence constantly."""
    body = _rubric(
        '  - requirement: "Python"\n'
        '    evidence: "Strong"\n'
        '    evidence_quote: "Built a **Multi-Provider LLM Orchestration** layer '
        'with automatic fallback across cloud providers and a local Ollama instance."\n')

    fixed, demoted = verify_rubric_evidence(body, CV)

    assert demoted == []
    assert fixed == body


def test_strong_without_any_quote_is_downgraded():
    body = _rubric('  - requirement: "Kubernetes"\n    evidence: "Strong"\n')

    _fixed, demoted = verify_rubric_evidence(body, CV)

    assert demoted == ["Kubernetes"]


def test_weak_and_none_are_left_alone():
    """Only Strong carries a full point, so only Strong has to be substantiated.
    Demanding a quote for Weak would reject partial evidence that is real."""
    body = _rubric('  - requirement: "Azure"\n    evidence: "None"\n'
                   '  - requirement: "Docker"\n    evidence: "Weak"\n')

    fixed, demoted = verify_rubric_evidence(body, CV)

    assert demoted == []
    assert fixed == body


def test_the_demotion_is_to_weak_so_a_wrong_rejection_costs_half_a_row():
    """A quote can be real and still not support its requirement, which this
    cannot see. Demoting to None would make that mistake cost a whole row."""
    body = _rubric('  - requirement: "A"\n    evidence: "Strong"\n'
                   '    evidence_quote: "nowhere in the CV"\n'
                   '  - requirement: "B"\n    evidence: "None"\n')

    fixed, _demoted = verify_rubric_evidence(body, CV)

    # 30 + 70 * (0.5 + 0) / 2 — Weak, not None.
    assert _extract_score(fixed)[0] == 47


def test_a_review_without_the_quote_field_at_all_is_untouched():
    """583 stored reviews predate evidence_quote. invariants recomputes their
    score from the body on disk, so a guard that changed them would report the
    lot as drifted."""
    body = _rubric('  - requirement: "Python"\n    evidence: "Strong"\n'
                   '  - requirement: "Azure"\n    evidence: "None"\n')

    before = _extract_score(body)[0]

    assert before == 65
    # Reaching run_review is what applies the guard; nothing re-reads old
    # reviews through it, and _extract_score alone leaves them as they were.
    assert _extract_score(body)[0] == before
