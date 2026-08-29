"""contract_kind / contract_months, and the runway_fit they feed.

employment_types already says a posting is a contract. What it cannot say is WHEN
THE CONTRACT ENDS, and that is the question the YMS expiry (config `yms_expiry`)
makes load-bearing: a 12-month FTC starting now finishes inside the visa, the same
FTC starting in 2027 does not.

Two words were removed from the classifier after measuring them against the live
corpus, and the negative tests below are what keeps them out: "contractor" fired
on "engineering contractor" (a company) and "Maintenance Contractor" (a persona in
a UX brief); "seasonal" fired on "seasonal campaigns" in marketing copy.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from analyzer import (
    analyze_job,
    classify_contract_kind,
    contract_duration_months,
)

ROOT = Path(__file__).resolve().parent.parent
ANALYZED = ROOT / "10_output" / "_analyzed.json"

KINDS = {"permanent", "ftc", "freelance", "temp", "unknown"}


@pytest.fixture(scope="module")
def corpus():
    if not ANALYZED.exists():
        pytest.skip("no live DB")
    return json.loads(ANALYZED.read_text(encoding="utf-8"))


# ── duration: real corpus wording ───────────────────────────────────────────
@pytest.mark.parametrize("title, description, expected", [
    # Titles that state their own length — the reliable case.
    ("Lead UX Designer (12 Month FTC)", "", 12),
    ("Service Designer - FTC - 12 Months", "", 12),
    ("Marketing Manager and Designer - 6 Month FTC", "", 6),
    # Years are converted, not stored in a second unit. This is the posting the
    # `director` exception exists for, so it has to parse as well as pass.
    ("Marketing Designer / Art Director (1 year FTC)", "", 12),
    # Body wording, all lifted from real postings.
    ("Web Developer", "to join their development team for a 12-month FTC.", 12),
    ("Principal UX/UI Designer", "to join their team on a 6-month contract.", 6),
    ("People Manager", "to join us on a 12-month maternity cover , and we welcome", 12),
    ("UX Researcher", "on an initial 3month fully remote contract with extensions", 3),
    ("Clerk of Works", "Immediate start available. 18-month temporary contract.", 18),
])
def test_duration_is_read(title, description, expected):
    assert contract_duration_months(title, description) == expected


@pytest.mark.parametrize("description", [
    # A probation period is not a contract length.
    "Permanent role. After 6 months you move onto an enhanced contract.",
    "Full-time permanent. 3 month probationary period applies to this contract.",
    # Experience is not a contract length.
    "We require 12 months of commercial experience on contract work.",
    "You will bring 24 months of experience delivering contract projects.",
    # A notice period is not a contract length.
    "Permanent contract with a 3 month notice period.",
])
def test_months_that_belong_to_something_else_are_ignored(description):
    assert contract_duration_months("Designer", description) is None


# ── kind ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title, description, expected", [
    ("Designer", "Job Type: Full-time, Permanent", "permanent"),
    ("Web Developer", "This is a 6 month contract, outside IR35.", "freelance"),
    ("Freelance Brand Designer", "", "freelance"),
    ("Digital Designer", "Contract: Freelance Duration: Approximately 6 months", "freelance"),
    ("Multi-Media Designer", "Type: 1-Year Fixed-Term Contract (Maternity Cover)", "ftc"),
    ("Warehouse Operative", "based in Birmingham on a full-time temporary basis.", "temp"),
    # Bare "contract" is deliberately not mapped: UK postings use the word for
    # both a fixed-term employee and a day-rate contractor, and employment_types
    # already records that it appeared.
    ("Graphic Designer", "A 12 week contract for an agency.", "unknown"),
])
def test_kind_is_classified(title, description, expected):
    assert classify_contract_kind(title, description) == expected


@pytest.mark.parametrize("description", [
    # "contractor" as a company or a persona, not an engagement.
    "A leading specialist engineering contractor is seeking a Design Engineer.",
    "Understanding our user personas (Tenant, Landlord, Maintenance Contractor).",
    "Identification of contractor design elements and engagement of designers.",
])
def test_contractor_in_prose_is_not_freelance(description):
    assert classify_contract_kind("Designer", description) != "freelance"


@pytest.mark.parametrize("description", [
    # "seasonal" as marketing vocabulary, not as a seasonal job.
    "Design creative concepts that support seasonal campaigns and product launches.",
    "Develop seasonal and innovation packaging for beauty categories.",
    # Recruiter boilerplate that appears in every posting from some agencies.
    "We act as an employment business for the supply of temporary workers.",
    # A civil-engineering discipline, not a temp role.
    "Become part of one of the UK's leaders in temporary works design.",
])
def test_prose_that_is_not_a_temp_role(description):
    assert classify_contract_kind("Designer", description) != "temp"


# ── the fields reach analyze_job, in the cheap pass ─────────────────────────
def test_fields_are_computed_without_an_llm():
    """All four are regex, so they must be present under skip_llm=True — the
    filter reads them before any model call is paid for."""
    out = analyze_job(
        {"title": "Digital Designer (12 Month FTC)",
         "description": "Fixed term contract. We cannot offer visa sponsorship."},
        skip_llm=True,
    )["analysis"]
    assert out["contract_kind"] == "ftc"
    assert out["contract_months"] == 12
    assert out["sponsorship"] == "refused"
    assert "sponsor" in (out["sponsorship_evidence"] or "").lower()


# ── runway_fit ──────────────────────────────────────────────────────────────
def test_runway_fit_compares_length_against_the_visa():
    from matcher import _runway_fit

    config = {"yms_expiry": date.today().replace(year=date.today().year + 1)}
    assert _runway_fit(6, config) == "fits"
    assert _runway_fit(24, config) == "ends_after_expiry"
    # No stated length, and no configured expiry, are both "unknown" rather than
    # a verdict. Most postings state no length at all.
    assert _runway_fit(None, config) == "unknown"
    assert _runway_fit(0, config) == "unknown"
    assert _runway_fit(12, {}) == "unknown"


def test_yms_expiry_accepts_a_date_or_an_iso_string():
    from selection import months_until_expiry, yms_expiry

    assert yms_expiry({"yms_expiry": date(2027, 10, 9)}) == date(2027, 10, 9)
    assert yms_expiry({"yms_expiry": "2027-10-09"}) == date(2027, 10, 9)
    assert yms_expiry({"yms_expiry": "not a date"}) is None
    assert yms_expiry({}) is None
    # Negative once the date has passed — a passed expiry is a real state and
    # must not be clamped to zero.
    assert months_until_expiry({"yms_expiry": date(2020, 1, 1)}) < 0


# ── corpus sweep ────────────────────────────────────────────────────────────
def test_corpus_values_stay_inside_their_domains(corpus):
    bad_kind, bad_months = [], []
    for j in corpus:
        title = j.get("title") or ""
        description = j.get("description") or j.get("snippet") or ""
        kind = classify_contract_kind(title, description)
        months = contract_duration_months(title, description)
        if kind not in KINDS:
            bad_kind.append((title[:34], kind))
        if months is not None and not (1 <= months <= 36):
            bad_months.append((title[:34], months))
    assert not bad_kind, bad_kind[:5]
    assert not bad_months, bad_months[:5]
