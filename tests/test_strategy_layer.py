"""The strategy layer: role family, remote scope, strategic value, action tier.

These answer a different question from the composite — not "could this candidate
get the job" but "does taking it move the career toward £43-45k creative
technology before the visa expires". The tests exist to hold three properties
that are easy to lose:

  * strategic_value NEVER reaches the composite. config.yaml records three
    failed attempts at improving the composite by recombining weak terms; this
    is a second column, and a test asserts the separation.
  * A term with no data DROPS rather than scoring zero, because most postings
    state no salary and 95% state no contract length.
  * A value renormalised over one surviving term is not comparable to one
    computed from four, so `strategic_coverage` is reported and the tier refuses
    to act below a floor. Without that gate, "Product Design Engineer" scored
    1.00 off `ladder` alone and read as the strongest posting in the corpus.
"""
import json
from pathlib import Path

import pytest
import yaml

from matcher import classify_remote_scope
from strategy import (
    _MOBILITY,
    action_tier,
    annotate,
    ladder_step,
    role_family,
    strategic_value,
)

ROOT = Path(__file__).resolve().parent.parent
ANALYZED = ROOT / "10_output" / "_analyzed.json"

SCOPES = {"onsite", "hybrid", "remote_uk", "remote_country", "remote_eu",
          "remote_worldwide", "remote_americas", "remote_unscoped", "unknown"}


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus():
    if not ANALYZED.exists():
        pytest.skip("no live DB")
    return json.loads(ANALYZED.read_text(encoding="utf-8"))


def _job(**analysis):
    return {"analysis": analysis}


# ── taxonomy ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role, family, step", [
    ("graphic_designer", "core_design", 1),
    ("product_designer", "hybrid_design_dev", 2),
    ("web_developer", "hybrid_design_dev", 2),
    ("creative_technologist", "creative_technology", 3),
    ("technical_artist", "creative_technology", 3),
    # The bridge is a parallel track, not a rung. A step here would claim a
    # progression that was never the plan.
    ("qa_engineer", "bridge", None),
    ("technical_support", "bridge", None),
    # Unmapped falls through rather than raising.
    ("general", "other", None),
    ("camera_assistant", "other", None),
])
def test_families_and_rungs(config, role, family, step):
    assert role_family(role, config) == family
    assert ladder_step(family, config) == step


def test_every_routing_profile_is_placed(config):
    """A profile missing from role_families silently becomes "other" and scores
    0.10 on the ladder term. That is right for camera_assistant and wrong for a
    design profile someone forgets to add, so the mapping is asserted to cover
    every routing key that is not deliberately excluded."""
    from cv_generator import ROLE_KEYWORDS

    deliberate_other = {"camera_assistant", "platform_engineer"}
    placed = {r for roles in config["role_families"].values() for r in roles}
    missing = set(ROLE_KEYWORDS) - placed - deliberate_other
    assert not missing, f"routing profiles with no family: {sorted(missing)}"


# ── remote scope ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("location, style, country, description, scope, confidence", [
    ("Edinburgh", "onsite", "UK", "", "onsite", "inferred"),
    ("London", "hybrid", "UK", "", "hybrid", "inferred"),
    ("London", "remote", "UK", "", "remote_uk", "inferred"),
    ("Berlin", "remote", "Germany", "", "remote_country", "inferred"),
    ("Deutschland", "remote", "", "", "remote_country", "inferred"),
    ("Europe", "remote", "", "", "remote_eu", "inferred"),
    ("Tokyo, Japan", "remote", "", "", "remote_country", "inferred"),
    ("San Francisco, CA", "remote", "", "", "remote_americas", "inferred"),
    ("", "remote", "", "", "remote_unscoped", "unknown"),
    ("Edinburgh", "unknown", "UK", "", "unknown", "unknown"),
])
def test_scope_is_derived(location, style, country, description, scope, confidence):
    assert classify_remote_scope(location, style, country, description) == (scope, confidence)


@pytest.mark.parametrize("location, description, scope", [
    # What the posting SAYS beats what its location field happens to contain.
    ("London", "This role is remote within the UK only.", "remote_uk"),
    ("London", "Fully remote across Europe.", "remote_eu"),
    ("London", "You can work from anywhere.", "remote_worldwide"),
    # Ordering: the specific geography wins over the worldwide phrasing.
    ("London", "Remote - anywhere in Europe.", "remote_eu"),
])
def test_stated_scope_overrides_the_location_field(location, description, scope):
    got, confidence = classify_remote_scope(location, "remote", "UK", description)
    assert (got, confidence) == (scope, "stated")


def test_every_scope_has_a_mobility_value():
    """A new scope with no mobility entry would silently drop the term for every
    job carrying it, which looks like missing data rather than a missing map."""
    unscored = SCOPES - set(_MOBILITY) - {"unknown"}
    assert not unscored, f"scopes with no mobility weight: {sorted(unscored)}"


# ── terms drop rather than score zero ───────────────────────────────────────
def test_missing_data_drops_its_term(config):
    out = strategic_value(_job(salary={}), {"detected_role": "creative_technologist"}, config)
    assert out["strategic_terms"]["salary"] is None
    assert out["strategic_terms"]["runway"] is None
    assert out["strategic_terms"]["mobility"] is None
    # Only `ladder` survived, so coverage records that the number rests on 30%
    # of the weight — the value itself is still a renormalised 1.0.
    assert out["strategic_coverage"] == pytest.approx(0.30, abs=0.01)
    assert out["strategic_value"] == 1.0


def test_a_full_house_uses_every_term(config):
    out = strategic_value(
        _job(salary={"max": 50000, "period": "annual"}),
        {"detected_role": "creative_technologist", "runway_fit": "fits",
         "remote_scope": "remote_eu"},
        config,
    )
    assert all(v is not None for v in out["strategic_terms"].values())
    assert out["strategic_coverage"] == 1.0


@pytest.mark.parametrize("salary, expected", [
    ({"max": 50000, "period": "annual"}, 1.0),      # above the band
    ({"max": 44000, "period": "annual"}, 0.85),     # inside the band
    ({"max": 26000, "period": "annual"}, 0.0),      # at the floor
    ({"max": 2.0, "period": "annual"}, None),       # a misparse, not a salary
    ({}, None),
    ({"max": 30, "period": "hourly"}, 1.0),         # annualises to ~£58k
])
def test_salary_term(config, salary, expected):
    out = strategic_value(_job(salary=salary), {"detected_role": "web_developer"}, config)
    assert out["strategic_terms"]["salary"] == expected


def test_runway_term_is_not_zero_for_a_contract_that_outruns_the_visa(config):
    """A contract past the expiry is not worthless — it is the shape that forces
    a conversation, and the sponsorship evidence sits beside it. Below `fits`,
    above nothing."""
    terms = lambda fit: strategic_value(  # noqa: E731
        _job(), {"detected_role": "web_developer", "runway_fit": fit}, config
    )["strategic_terms"]["runway"]
    assert terms("fits") == 1.0
    assert 0 < terms("ends_after_expiry") < terms("fits")
    assert terms("unknown") is None


# ── action tier ─────────────────────────────────────────────────────────────
def test_tier_one_is_unreachable_without_a_review(config):
    """The top tier asserts a human-checked verdict, mirroring the rule the tier
    labels already follow: "Strong Match" needs an LLM context read, not a high
    keyword composite."""
    assert action_tier(0.95, 1.0, review_score=None, coverage=1.0) == 2
    assert action_tier(0.95, 1.0, review_score=90, coverage=1.0) == 1


def test_a_filtered_posting_can_only_monitor_or_ignore(config):
    """It has no documents, therefore no review, therefore nothing to act on."""
    level = "level 'senior' not in allowed levels ['entry_level', 'mid']"
    assert action_tier(0.9, 0.9, review_score=90, filter_reason=level,
                       coverage=1.0) == 4
    assert action_tier(0.9, 0.9, review_score=90, filter_reason=level,
                       coverage=1.0) != 1
    trade = "title contains excluded keyword 'electrical'"
    assert action_tier(0.9, 0.9, filter_reason=trade, coverage=1.0) == 5


def test_low_coverage_cannot_promote(config):
    """A 1.00 computed from `ladder` alone must not buy a tier. This is the exact
    case that made the gate necessary."""
    high = action_tier(0.30, 1.0, coverage=1.0)
    thin = action_tier(0.30, 1.0, coverage=0.30)
    assert high == 3 and thin == 5


def test_opportunistic_needs_no_review(config):
    """Tier 3 is the weak-fit / strong-trajectory case, and most postings outside
    the top 40% have no review at all — so it has to work without one."""
    assert action_tier(0.20, 0.85, review_score=None, coverage=1.0) == 3


# ── separation from the composite ───────────────────────────────────────────
def test_the_strategy_layer_never_touches_the_composite(config):
    """Three recorded re-weighting attempts lost out of sample. A fifth weak term
    would be the fourth."""
    job = {"title": "Creative Technologist", "company": "X",
           "location": "Remote", "description": "d" * 400,
           "analysis": {"salary": {"max": 60000, "period": "annual"},
                        "work_style": "remote", "skills": ["Python"],
                        "experience_level": "mid", "employment_types": ["full_time"]}}
    match = {"composite_score": 0.42, "detected_role": "creative_technologist",
             "runway_fit": "fits", "remote_scope": "remote_eu"}
    out = annotate(job, match, config)
    assert out["strategic_value"] > 0.8
    assert match["composite_score"] == 0.42
    assert "composite_score" not in out


# ── corpus sweep ────────────────────────────────────────────────────────────
def test_corpus_values_stay_inside_their_domains(config, corpus):
    from matcher import _infer_country, _runway_fit

    families = set(config["role_families"]) | {"other"}
    bad = []
    for job in corpus[:1500]:
        match = job.get("match") or {}
        analysis = job.get("analysis") or {}
        scope, confidence = classify_remote_scope(
            job.get("location") or "", analysis.get("work_style") or "",
            _infer_country(job), job.get("description") or "")
        out = annotate(job, {**match, "remote_scope": scope,
                             "runway_fit": _runway_fit(analysis.get("contract_months"), config)},
                       config)
        value = out["strategic_value"]
        if scope not in SCOPES or confidence not in {"stated", "inferred", "unknown"}:
            bad.append(("scope", job.get("title"), scope, confidence))
        if out["role_family"] not in families:
            bad.append(("family", job.get("title"), out["role_family"]))
        if value is not None and not (0.0 <= value <= 1.0):
            bad.append(("value", job.get("title"), value))
        if not (0.0 <= out["strategic_coverage"] <= 1.0):
            bad.append(("coverage", job.get("title"), out["strategic_coverage"]))
        if out["action_tier"] not in (1, 2, 3, 4, 5):
            bad.append(("tier", job.get("title"), out["action_tier"]))
    assert not bad, bad[:5]
