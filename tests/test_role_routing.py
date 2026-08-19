"""Guards on which CV profile a posting is routed to.

A misroute is expensive and quiet: the applicant sends a Development Support
Engineer CV to a Back End Engineer post and never learns why. The bug that
prompted these tests was a body keyword firing inside benefits boilerplate
("Career development support and wide ranging learning opportunities"), which
outvoted a title nothing else matched. So the guards here are of three kinds:

  * routes pinned for titles that have been misrouted before,
  * invariants on HOW a route may be decided (title evidence, or corroborated
    body evidence — never one incidental phrase),
  * a corpus sweep over the real analyzed jobs, asserting the invariants hold
    for every posting rather than only for the handful pinned below.
"""

import json
import os

import pytest

from cv_generator import (
    MIN_BODY_KEYWORDS,
    MIN_BODY_MARGIN,
    ROLE_KEYWORDS,
    _score_roles,
    detect_role_type,
    detect_role_type_with_evidence,
)

BENEFITS_BOILERPLATE = (
    "We offer a competitive salary, private medical care, life assurance, "
    "enhanced maternity and paternity pay. Career development support and wide "
    "ranging learning opportunities. Employee health and wellbeing support."
)


# ── Routes pinned for titles that have gone wrong before ────────────────────
@pytest.mark.parametrize(
    "title, description, expected",
    [
        # The reported bug: the title matched no keyword at all ("backend
        # developer" does not cover "Back End Engineer"), so one boilerplate
        # phrase in the benefits section picked the profile.
        ("Junior Back End Engineer",
         "You would be joining a team of exceptional engineers. As a software "
         "engineer you will work on research, design and testing. " + BENEFITS_BOILERPLATE,
         "web_developer"),
        # Same family of spellings, all of which used to score zero.
        ("Back End Engineer", "Python and PostgreSQL services.", "web_developer"),
        ("Back-End Engineer", "Python and PostgreSQL services.", "web_developer"),
        ("Backend Engineer", "Python and PostgreSQL services.", "web_developer"),
        ("Front End Engineer", "TypeScript and CSS.", "web_developer"),
        # Engineering disciplines that are not software: these were answered
        # with a web-developer and a product-designer CV respectively.
        ("Mechanical Design Engineer",
         "CAD, tolerances and manufacturing drawings. " + BENEFITS_BOILERPLATE,
         "general"),
        ("Electrical Design Engineer",
         "LV distribution and lighting design. " + BENEFITS_BOILERPLATE,
         "general"),
        # Titles that genuinely name the discipline still route.
        ("Graphic Designer", "InDesign and brand identity work.", "graphic_designer"),
        ("UX Designer", "Figma, prototyping, design systems.", "product_designer"),
        ("Platform Engineer", "Kubernetes and Terraform.", "platform_engineer"),
        ("Development Support Engineer", "Internal tooling for the studio.",
         "development_support"),
        ("Research Software Engineer", "Scientific software for a lab.",
         "research_engineer"),
    ],
)
def test_pinned_routes(title, description, expected):
    assert detect_role_type(title, description) == expected


# ── Boilerplate must never be the deciding evidence ─────────────────────────
def test_benefits_boilerplate_alone_routes_nowhere():
    """The exact sentence that caused the misroute, with no other signal."""
    role, evidence = detect_role_type_with_evidence("Sonographer", BENEFITS_BOILERPLATE)
    assert role == "general", evidence


def test_career_development_support_is_not_a_development_support_signal():
    hits = [kw for kw in ROLE_KEYWORDS["development_support"]
            if kw in BENEFITS_BOILERPLATE.lower()]
    assert hits == [], f"HR phrasing still reads as a role signal: {hits}"


# ── How a route may be decided ──────────────────────────────────────────────
def test_single_body_keyword_never_routes():
    """One incidental phrase is not evidence of a discipline."""
    role, evidence = detect_role_type_with_evidence(
        "Operations Coordinator", "Some familiarity with Figma is a plus.")
    assert role == "general"
    assert evidence.startswith("weak-body:"), evidence


def test_corroborated_body_evidence_still_routes():
    """A title that names nothing, over a description that is unambiguous."""
    role, evidence = detect_role_type_with_evidence(
        "Junior Technologist",
        "You will own our Kubernetes clusters, Terraform modules and "
        "observability stack alongside the DevOps team.")
    assert role == "platform_engineer", evidence
    assert evidence.startswith("body:"), evidence


def test_thin_margin_falls_back_instead_of_dict_order():
    """Two roles a hit apart used to be settled by ROLE_KEYWORDS insertion
    order, invisibly. Neither wins now."""
    role, evidence = detect_role_type_with_evidence(
        "Specialist",
        "Work with our quality assurance and test automation people, and with "
        "the software engineer team.")
    assert role == "general"
    assert evidence.startswith("thin-margin:"), evidence


# ── Anchoring: a keyword may not fire from inside a longer word ─────────────
def test_keyword_does_not_match_inside_a_longer_word():
    assert detect_role_type("Reactive Maintenance Engineer",
                            "Boiler repairs and reactive callouts.") == "general"


def test_suffixed_form_still_matches():
    """The anchor is suffix-tolerant: "graphic design" must hit "Graphic Designer"."""
    scored = _score_roles("Graphic Designer", "")
    assert "graphic design" in scored["graphic_designer"][1]


def test_run_together_scrape_artifact_still_matches():
    """Descriptions lose the space at HTML block joins. A capital letter is a
    word boundary in practice, so the hit must survive."""
    scored = _score_roles("", "Azure DevOpsKnowledge of Terraform required")
    assert "devops" in scored["platform_engineer"][2]


# ── Corpus sweep ────────────────────────────────────────────────────────────
ANALYZED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "10_output", "_analyzed.json")


def _corpus():
    if not os.path.exists(ANALYZED):
        pytest.skip("10_output/_analyzed.json not present")
    with open(ANALYZED, encoding="utf-8") as fh:
        data = json.load(fh)
    jobs = data if isinstance(data, list) else data.get("jobs", data)
    return [j for j in jobs if (j.get("description") or "").strip()]


def test_corpus_specialised_routes_are_all_justified():
    """Every specialised route in the real corpus must carry either title
    evidence or corroborated body evidence. No exceptions, no silent ties."""
    offenders = []
    for job in _corpus():
        title = job.get("title") or ""
        body = job["description"]
        role, evidence = detect_role_type_with_evidence(title, body)
        if role == "general":
            continue
        scored = _score_roles(title, body)
        score, title_hits, body_hits = scored[role]
        if title_hits:
            continue
        runner_up = max((v[0] for r, v in scored.items() if r != role), default=0)
        if len(body_hits) < MIN_BODY_KEYWORDS or score - runner_up < MIN_BODY_MARGIN:
            offenders.append((title, role, evidence))
    assert not offenders, f"{len(offenders)} unjustified routes, e.g. {offenders[:5]}"


def test_corpus_body_only_routes_stay_a_minority():
    """A keyword edit that turns some common phrase into a magnet shows up here
    as a jump in routes decided without the title. 8% at the time of writing."""
    body_only = specialised = 0
    for job in _corpus():
        role, evidence = detect_role_type_with_evidence(job.get("title") or "",
                                                        job["description"])
        if role == "general":
            continue
        specialised += 1
        if evidence.startswith("body:"):
            body_only += 1
    share = body_only / max(specialised, 1)
    assert share < 0.15, f"{body_only}/{specialised} routes decided by body alone ({share:.0%})"
