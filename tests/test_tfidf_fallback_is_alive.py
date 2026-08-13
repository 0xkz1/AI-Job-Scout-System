"""The TF-IDF context fallback must actually run, not return a constant.

scikit-learn is declared in requirements.txt but was not installed in the venv,
so SKLEARN_AVAILABLE was False and calculate_context_match returned on its first
line:

    if not SKLEARN_AVAILABLE or not job_description:
        return {"score": 0.5, "reasoning": "", "top_terms": []}

Every job the LLM path did not cover therefore scored exactly 0.50 on context —
596 of 604 in the database, the other 8 predating the situation. Context carries
0.64 of the composite, so each of those jobs held 0.32 of unearned score, and
0.50 sat well above the mean LLM role_fit of 0.335: "no opinion" outranked most
real opinions. Four trade postings (Mechanical Designer, Electrical Designer,
Sales Engineer - Rockfall and Geotechnical) reached the generation set on it
with a skills score of 0.0, held out only by an exclude_title_keywords entry.

None of the calibration below that line had ever executed. RAW_FLOOR, RAW_CEIL
and TFIDF_SCORE_CAP, and the comment reasoning about a "29% weight", described
code that never ran.

A missing optional dependency degrading to a constant is not visibly broken from
the outside — the scores look like scores. These tests make it visible.
"""
import matcher
import pytest


def test_sklearn_is_actually_importable():
    """requirements.txt line 8 says scikit-learn>=1.3.0. If the venv disagrees,
    the whole fallback silently becomes the constant 0.5."""
    assert matcher.SKLEARN_AVAILABLE, (
        "scikit-learn is not importable, so calculate_context_match returns a "
        "constant 0.5 for every job the LLM path does not cover"
    )


def test_the_fallback_separates_a_relevant_job_from_an_unrelated_one():
    """The point of the fallback is a signal, however weak. Two postings at
    opposite ends of the persona must not come back with the same number."""
    relevant = matcher.calculate_context_match(
        "We are hiring a creative technologist to build AI-driven design tools, "
        "ComfyUI pipelines, Python automation and interactive web experiences."
    )
    unrelated = matcher.calculate_context_match(
        "Mechanical Designer required for HVAC ductwork drawings, AutoCAD, "
        "sheet metal fabrication and site surveys."
    )
    assert relevant["score"] != unrelated["score"], (
        "the fallback returns the same score for a creative-technology posting "
        "and an HVAC drafting one — it is not computing anything"
    )
    assert relevant["score"] > unrelated["score"]


def test_a_computed_score_carries_its_evidence():
    """The constant-0.5 return has an empty reasoning and no terms; a real one
    names the words it matched. That difference is how the dead path was found
    in the stored data."""
    result = matcher.calculate_context_match(
        "Creative technologist role: generative AI, ComfyUI, Blender Python "
        "automation, design systems and front-end prototyping."
    )
    assert result.get("top_terms"), "a computed score should report its terms"
    assert result.get("reasoning"), "a computed score should report its reasoning"
    assert "raw_similarity" in result, (
        "raw_similarity is only set on the computed path; its absence means one "
        "of the constant-0.5 escape hatches was taken"
    )


def test_an_empty_description_still_returns_the_neutral_constant():
    """The one case where 0.5 is legitimate — nothing to compare against."""
    result = matcher.calculate_context_match("")
    assert result["score"] == 0.5
    assert "raw_similarity" not in result


@pytest.mark.parametrize("field", ["RAW_FLOOR", "RAW_CEIL", "TFIDF_SCORE_CAP"])
def test_the_calibration_constants_are_reachable(field):
    """These live inside the function body, so the only way to know they are
    exercised is to reach the computed path at all. If this file's other tests
    pass, they are — this one just pins the names so a rename does not quietly
    strand them again."""
    import inspect
    source = inspect.getsource(matcher.calculate_context_match)
    assert field in source
