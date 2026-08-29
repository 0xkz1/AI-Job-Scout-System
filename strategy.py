"""The strategy layer: what a job is worth beyond whether it can be got.

`matcher.analyze_match` answers one question — could this candidate realistically
get this job. That question is fitted, measured, and as good as anything measured
against it. It is also not the only question, and the brief of 2026-08-29 asked
for the other one: does taking this job move the career toward £43-45k creative
technology before the YMS visa expires on 2027-10-09.

Three deliberate constraints, all of them reactions to what has already failed
here:

  * NOTHING in this module calls a model. Every value is arithmetic over fields
    the cheap analysis pass already produced. A per-job LLM cost for a dimension
    with no ground truth to validate it is exactly the trade config.yaml records
    three failed attempts at.

  * `strategic_value` is NEVER blended into the composite. config.yaml:
    "every dimension is a weak predictor, so no linear recombination of them has
    anywhere to go". Adding a fifth weak term to four weak terms produces five
    weak terms and an opaque number. This is a second column, not a correction.

  * Every term is stored beside the total (`strategic_terms`), so a number can
    always be taken apart. A term with no data DROPS and the remaining weights
    renormalise — the same treatment `context_source == "unscored"` gets in the
    composite, and for the same reason: multiplying a 0.0 through a quarter of
    the score records "bad" where the truth is "not stated".
"""
from __future__ import annotations

# Families a detected_role belongs to, when config says nothing. Kept here only
# as a fallback; config.yaml `role_families` is the real map, so the taxonomy can
# change without a code change.
_DEFAULT_FAMILIES = {
    "core_design": ["graphic_designer"],
    "hybrid_design_dev": ["product_designer", "web_developer"],
    "creative_technology": ["creative_technologist", "technical_artist", "product_engineer"],
    "bridge": ["implementation_specialist", "technical_support", "qa_engineer",
               "product_ops", "research_engineer", "content_analyst",
               "development_support", "data_analysis"],
}
_DEFAULT_LADDER = {"core_design": 1, "hybrid_design_dev": 2, "creative_technology": 3}

# The numbers below are CONSTANTS, not settings, and that is a deliberate
# distinction. config.yaml is the right home for facts that change and for data
# that grows by observation — the visa date, the salary band, the family map, the
# title exceptions. It is the wrong home for a knob with no measurement behind
# it: exposing one advertises a tunability that does not exist, and every knob is
# another way for the system to be quietly wrong.
#
# There is no ground truth for "should I have applied to this job", so none of
# these can be fitted. They are a starting position, and the honest place for a
# starting position is next to the code that explains it. record_outcome.py is
# accumulating the outcomes that could eventually replace them with measurements;
# on that day these move to config, with the measurement written beside them.
_WEIGHTS = {"ladder": 0.30, "salary": 0.25, "runway": 0.25, "mobility": 0.20}
_TIER1 = {"composite": 0.60, "review": 75, "strategic": 0.50}
_TIER2 = {"composite": 0.50, "review": 60}
_MONITOR_MIN = 0.60
_OPPORTUNISTIC_MIN = 0.70
# Least share of strategic weight that must have had real data before a tier acts
# on strategic_value. `ladder` alone is 0.30 and `ladder` + `mobility` is 0.50, so
# this says the role family AND how far the arrangement travels must both be
# known. Salary and contract length are missing from most postings and cannot be
# required.
_COVERAGE_MIN = 0.50

# How far a remote arrangement travels. The ordering is the whole point: a role
# that survives leaving the UK is worth more than one that does not, whatever it
# pays, because it is the only kind that keeps working after 2027-10-09.
#
# `remote_uk` sits well below `remote_eu` for that reason and not because a UK
# remote job is worse today. Hybrid and on-site are not zero: they are the roles
# that can actually be started from Edinburgh, which is what the next twelve
# months are for.
_MOBILITY = {
    "remote_worldwide": 1.00,
    "remote_eu": 0.90,
    "remote_country": 0.90,
    "remote_unscoped": 0.60,
    "remote_uk": 0.35,
    "hybrid": 0.20,
    "onsite": 0.10,
    # Below on-site, not absent. An Americas-hours remote role is placed — it is
    # just placed in a timezone that makes it a night shift, which is the same
    # objection `exclude_timezone_keywords` encodes as a hard filter and
    # _classify_international_location scores at 0.18. Leaving it out of this map
    # made the term DROP, so such a job was scored as though its work style were
    # unknown rather than known and unwanted.
    "remote_americas": 0.05,
}


def role_family(detected_role: str, config: dict | None = None) -> str:
    """Which family a routed role belongs to. "other" for anything unmapped.

    Reads config so the taxonomy is data. The seventeen CV profiles in
    cv_generator.ROLE_KEYWORDS are the routing vocabulary and stay the single
    source of truth for WHICH profile a posting gets; this only groups them.
    """
    families = (config or {}).get("role_families") or _DEFAULT_FAMILIES
    for family, roles in families.items():
        if detected_role in (roles or []):
            return family
    return "other"


def ladder_step(family: str, config: dict | None = None) -> int | None:
    """1, 2, 3, or None for a family that is not on the ladder.

    None is not a failure. The bridge roles are a parallel track by design (see
    career-strategy-2026-2027.md §3) — jobs that pay now without breaking the
    story — and forcing them onto a rung would claim a progression that was never
    the plan.
    """
    ladder = (config or {}).get("ladder") or _DEFAULT_LADDER
    step = ladder.get(family)
    return int(step) if isinstance(step, (int, float)) else None


def _ladder_term(family: str, step: int | None, config: dict) -> float:
    current = int((config or {}).get("candidate_ladder_step", 1))
    if step is None:
        # The bridge exists to be taken. It scores below any on-ladder role and
        # far above an unrelated one.
        return 0.35 if family == "bridge" else 0.10
    if step > current:
        return 1.0
    if step == current:
        return 0.60
    return 0.30


def _salary_term(salary: dict | None, config: dict) -> float | None:
    """None when the posting states no usable figure — which is most of them.

    Uses the maximum, not the minimum: a range's top is what the role can pay,
    and the composite already declines to weight salary at all (config `weights`
    holds it at 0.00 because it correlates NEGATIVELY with review outcome). That
    finding is about predicting whether a CV will review well. It says nothing
    about whether a salary moves a career, which is what this term is for.
    """
    if not isinstance(salary, dict):
        return None
    top = salary.get("max")
    if not isinstance(top, (int, float)):
        return None
    period = (salary.get("period") or "").lower()
    if period == "hourly":
        top = top * 37.5 * 52
    if top < 1000:  # a misparse, not a salary — see filter._annualise
        return None
    band = (config or {}).get("salary_target_band") or [43000, 45000]
    low, high = float(band[0]), float(band[-1])
    floor = float((config or {}).get("min_salary_gbp") or 26000)
    if top >= high:
        return 1.0
    if top >= low:
        return 0.85
    if top <= floor:
        return 0.0
    return round(0.70 * (top - floor) / (low - floor), 3)


def _runway_term(runway_fit: str | None) -> float | None:
    """None for the 95% of postings that never state a length.

    `ends_after_expiry` is 0.40, not 0. A contract running past the visa is not
    worthless — it is the shape that forces a conversation about what comes next,
    and the sponsorship evidence recorded beside it is the material for that
    conversation. It is held below `fits` because it cannot be completed on the
    visa as it stands, which is a fact about the calendar and not a prediction.
    """
    if runway_fit == "fits":
        return 1.0
    if runway_fit == "ends_after_expiry":
        return 0.40
    return None


def _mobility_term(remote_scope: str | None) -> float | None:
    return _MOBILITY.get(remote_scope or "")


def strategic_value(job: dict, match: dict, config: dict | None = None) -> dict:
    """{"strategic_value": float|None, "strategic_terms": {...}} — interpretable.

    Returns None for the value when NO term had data, which is honest rather than
    zero: a posting that states no salary, no length and no work style has not
    been judged and must not be ranked as though it lost.
    """
    config = config or {}
    analysis = job.get("analysis") or {}
    family = role_family(match.get("detected_role") or "general", config)
    step = ladder_step(family, config)

    terms = {
        "ladder": _ladder_term(family, step, config),
        "salary": _salary_term(analysis.get("salary"), config),
        "runway": _runway_term(match.get("runway_fit")),
        "mobility": _mobility_term(match.get("remote_scope")),
    }
    live = {k: v for k, v in terms.items() if v is not None}
    total_weight = sum(_WEIGHTS[k] for k in live)
    value = (
        round(sum(v * _WEIGHTS[k] for k, v in live.items()) / total_weight, 3)
        if total_weight else None
    )
    return {
        "role_family": family,
        "ladder_step": step,
        "strategic_value": value,
        # How much of the weight actually had data. Renormalising without saying
        # so was actively misleading: "Product Design Engineer - AI-Native
        # Product" scored 1.00 on `ladder` alone, with no salary, no length and
        # no work style, and read as the most strategic posting in the corpus
        # when what it meant was "one thing is known and it was good".
        #
        # The value is still renormalised — scoring silence as zero is worse —
        # but action_tier will not act on a value below the coverage floor, so a
        # one-term score can inform a human without moving a decision.
        "strategic_coverage": round(total_weight / sum(_WEIGHTS.values()), 3),
        # Kept so the number can always be taken apart, the way context_source /
        # context_draws / context_provider exist beside context_score.
        "strategic_terms": terms,
    }


def action_tier(composite: float | None, strategic: float | None,
                review_score: float | None = None, filter_reason: str | None = None,
                coverage: float | None = None) -> int:
    """1 apply now · 2 apply · 3 opportunistic · 4 monitor · 5 ignore.

    A RULE TABLE, not a fitted score, and deliberately so: there is no ground
    truth for "should I have applied to this", so a fitted model would be fitting
    noise. The numbers below are a starting position to be revised against real
    outcomes once record_outcome.py has enough of them — not a measurement.

    Tier 1 is unreachable without a review score, mirroring the rule the tier
    labels already follow ("Strong Match" requires an LLM context read rather
    than a high keyword composite). Tier 1 asserts a human-checkable verdict, and
    the CV review is the only signal here that has one — see
    review-score-is-the-trusted-signal.

    A filtered posting can only reach 4 or 5. It has no documents, therefore no
    review, therefore nothing to act on except a decision to look again.
    """
    comp = float(composite or 0.0)
    sv = float(strategic) if isinstance(strategic, (int, float)) else 0.0
    # A strategic_value renormalised over one surviving term is not comparable to
    # one computed from four. Below the floor it is treated as unmeasured, so the
    # tier falls back on the composite and the review — both of which are always
    # present — instead of on a number that only looks confident.
    if coverage is not None and coverage < _COVERAGE_MIN:
        sv = 0.0

    if filter_reason:
        return 4 if ("level" in filter_reason and sv >= _MONITOR_MIN) else 5

    if review_score is not None:
        if (review_score >= _TIER1["review"] and comp >= _TIER1["composite"]
                and sv >= _TIER1["strategic"]):
            return 1
        if review_score >= _TIER2["review"] and comp >= _TIER2["composite"]:
            return 2
        return 4 if sv >= _MONITOR_MIN else 5

    # No human-checked signal. Tier 1 asserts one, so it cannot be reached here.
    if comp >= _TIER1["composite"] and sv >= _TIER1["strategic"]:
        return 2
    if comp >= _TIER2["composite"]:
        return 3
    if sv >= _OPPORTUNISTIC_MIN:
        return 3
    return 5


def annotate(job: dict, match: dict, config: dict | None = None,
             review_score: float | None = None) -> dict:
    """Everything this module adds to a match, in one call.

    `review_score` is passed in rather than looked up: it lives in the review
    file's frontmatter, not on the job, and a per-job file read inside the
    matcher would put disk IO in the middle of a scoring loop. Callers that have
    it (nightly_scout, the report writers) pass it; callers that do not get a
    tier computed without it, which is a defined case rather than a gap.
    """
    out = strategic_value(job, match, config)
    out["action_tier"] = action_tier(
        match.get("composite_score"), out["strategic_value"],
        review_score=review_score, filter_reason=job.get("_filter_reason"),
        coverage=out["strategic_coverage"],
    )
    return out
