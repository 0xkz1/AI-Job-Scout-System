"""Regression tests for the skill-scoring layers added 2026-07-24.

Each test pins a bug that shipped silently — no exception, no empty output, just
quietly wrong scores. They exist because manual inspection was the only thing
that caught them.
"""
from matcher import (
    _resolve_by,
    _singularize,
    calculate_skill_match,
    load_user_skills,
    normalize_skill_name,
)


def _known():
    return {normalize_skill_name(s["name"]): s["name"]
            for skills in load_user_skills().values() for s in skills}


# --- _resolve_by: the bug that silently dropped ~every positive verdict -------

def test_resolve_by_accepts_whole_catalogue_line():
    """The model echoes back the full catalogue line instead of just the name.
    Before the fix this matched no row, so the verdict was discarded."""
    known = _known()
    assert _resolve_by("Multi-Agent Systems (intermediate) [ML / AI (Local-First)]",
                       known) == "Multi-Agent Systems"
    assert _resolve_by("Python (advanced) [Programming Languages] — 4+ years",
                       known) == "Python"


def test_resolve_by_accepts_plain_name():
    known = _known()
    assert _resolve_by("React", known) == "React"


def test_resolve_by_rejects_unknown_skill():
    """Unattributable credit must be dropped — this is what stops the model
    inventing a skill the candidate never listed."""
    assert _resolve_by("Kubernetes Service Mesh Wizardry", _known()) == ""
    assert _resolve_by("", _known()) == ""


# --- _singularize: safe only because the stem is a lookup key ----------------

def test_singularize_handles_real_plurals():
    assert _singularize("component libraries") == "component library"
    assert _singularize("large language models") == "large language model"


def test_singularize_leaves_short_and_ss_us_is_words_alone():
    """Bogus stems would be harmless (they match no entry), but not mangling
    them keeps the lookup honest."""
    for w in ("aws", "css", "sass", "business", "analysis", "redis"):
        assert _singularize(w) == w, w


# --- calculate_skill_match: the floor, and the LLM layer's limits ------------

def test_zero_matches_scores_zero():
    """The strength floor must never invent a fit — no match, no floor."""
    user = load_user_skills()
    r = calculate_skill_match(["Underwater Basket Weaving", "Equine Dentistry"], user)
    assert r["score"] == 0.0
    assert not r["matched"] and not r["partial"]


def test_real_matches_survive_a_long_unmatched_tail():
    """The original bug: 3 real matches among ~20 requirements scored exactly 0
    because coverage_ratio - gap_penalty went negative."""
    user = load_user_skills()
    job = ["Python", "Bash / Shell", "Docker / Docker Compose"] + [
        f"Nonexistent Skill {i}" for i in range(17)]
    r = calculate_skill_match(job, user)
    assert len(r["matched"]) >= 3
    assert r["score"] > 0.15, f"real matches collapsed to {r['score']}"


def test_llm_coverage_rescues_only_with_a_resolvable_by():
    """A verdict the covering row can't be resolved for must NOT score."""
    user = load_user_skills()
    job = ["Software Engineering"]
    good = calculate_skill_match(job, user, llm_coverage={
        "Software Engineering": {"verdict": "full", "by": "Code Refactoring"}})
    bad = calculate_skill_match(job, user, llm_coverage={
        "Software Engineering": {"verdict": "full", "by": "Nonexistent Row"}})
    assert good["matched"] and good["score"] > 0
    assert not bad["matched"] and bad["missing"] == ["Software Engineering"]


def test_not_a_skill_leaves_the_denominator():
    """Extraction noise must not sit in the denominator as a fake requirement.

    Uses enough real requirements to clear _SKILL_MIN_REQS: below that floor the
    denominator is pinned, so dropping one noise term cannot move the score and
    the assertion would pass or fail for reasons unrelated to what it checks.
    """
    user = load_user_skills()
    job = ["Python", "JavaScript", "HTML", "CSS", "Git", "16Personalities"]
    with_noise = calculate_skill_match(job, user)
    cleaned = calculate_skill_match(job, user, llm_coverage={
        "16Personalities": {"verdict": "not_a_skill", "by": ""}})
    assert cleaned["score"] > with_noise["score"]
    assert "16Personalities" not in cleaned["missing"]


def test_sparse_requirement_list_cannot_inflate_coverage():
    """A posting that names one requirement must not yield a near-perfect fit.

    Unfloored, coverage was matched/total, so a single matched term out of one
    listed term scored ~1.0 — which is how a Geotechnical Design Engineer role
    reached a 96% skill fit off the word "Design" alone.
    """
    user = load_user_skills()
    sparse = calculate_skill_match(["Python"], user)
    assert sparse["matched"], "expected Python to match the candidate's skills"
    assert sparse["score"] <= 0.5, f"one matched requirement scored {sparse['score']}"


def test_llm_coverage_cannot_overturn_a_dictionary_match():
    """The LLM layer is a rescue path only — it runs after the deterministic
    passes and must not demote what they already matched."""
    user = load_user_skills()
    r = calculate_skill_match(["Python"], user, llm_coverage={
        "Python": {"verdict": "none", "by": ""}})
    assert r["matched"] and not r["missing"]
