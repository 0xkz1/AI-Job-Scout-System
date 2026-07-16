"""Regression tests for calculate_title_relevance's LLM-context rescue.

Bug fixed 2026-07-16: a title without a keyword-whitelist hit (e.g.
"Specialist Technician - Metal") got a hardcoded x0.1 penalty even when the
LLM, reading the full description against the persona, scored context at
88%. The report displayed a breakdown summing to 64% but a final score of
6%, with no explanation — the keyword gate was silently overriding a
confident full-context read.
"""
from matcher import calculate_title_relevance


def test_unrecognized_title_rescued_by_confident_llm_context():
    relevance = calculate_title_relevance(
        "Specialist Technician - Metal", context_score=0.88, context_source="llm"
    )
    assert relevance == 1.0


def test_unrecognized_title_not_rescued_without_llm_context():
    # No LLM signal (e.g. TF-IDF fallback) — keyword gate still applies.
    relevance = calculate_title_relevance(
        "Specialist Technician - Metal", context_score=0.88, context_source="tfidf"
    )
    assert relevance == 0.1


def test_unrecognized_title_not_rescued_by_weak_llm_context():
    relevance = calculate_title_relevance(
        "Specialist Technician - Metal", context_score=0.4, context_source="llm"
    )
    assert relevance == 0.1


def test_exclusion_words_always_zero_even_with_confident_context():
    # Hard exclusions (wrong domain entirely) must not be rescuable.
    relevance = calculate_title_relevance(
        "Registered Nurse", context_score=0.95, context_source="llm"
    )
    assert relevance == 0.0


def test_recognized_title_still_full_relevance():
    relevance = calculate_title_relevance("Creative Technologist")
    assert relevance == 1.0
