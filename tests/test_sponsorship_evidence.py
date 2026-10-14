"""The sponsorship flag records what a posting SAYS, and never infers.

This is the only field in the pipeline that touches immigration, so it is held to
a stricter rule than the rest: every verdict carries the sentence that produced
it, and a reading that requires a leap is not taken at all.

Three ways of getting it wrong were found by measuring the first version against
the live corpus, and each has a test here:

  * "Whilst the University is a licensed sponsor, under UKVI not all roles
    qualify" was read as an OFFER. Being a licensed sponsor is a fact about the
    employer, not about this job.
  * "this vacancy does not currently meet the minimum salary threshold for
    Skilled Worker" was read as an OFFER, on the words "Skilled Worker ...
    sponsor".
  * "we can't offer visa sponsorship" was read as an OFFER, because the posting
    used a curly apostrophe and missed every refusal pattern.
"""
import json
from pathlib import Path

import pytest

from analyzer import classify_sponsorship

ROOT = Path(__file__).resolve().parent.parent
ANALYZED = ROOT / "10_output" / "_analyzed.json"


@pytest.fixture(scope="module")
def corpus():
    if not ANALYZED.exists():
        pytest.skip("no live DB")
    return json.loads(ANALYZED.read_text(encoding="utf-8"))


@pytest.mark.parametrize("description", [
    "Unfortunately we are unable to offer visa sponsorship for this role.",
    "We cannot offer sponsorship for this role.",
    "Please note that we currently do not offer visa sponsorship.",
    "Only candidates with rights to work in the UK will be considered "
    "(No Visa sponsorship available)",
    "We do not hold a sponsorship licence and can only consider applications from "
    "candidates who are legally entitled to work in the UK.",
    "Visa sponsorship is not available.",
    "This role is offered without sponsorship.",
    # The curly-apostrophe case. Word processors produce these constantly.
    "Unfortunately, we can’t offer visa sponsorship or relocation support.",
    "You’ll need the right to work in the UK; we’re unable to offer visa sponsorship.",
])
def test_refusals_are_read_as_refusals(description):
    state, quote = classify_sponsorship("Designer", description)
    assert state == "refused"
    assert "sponsor" in quote.lower()


@pytest.mark.parametrize("description", [
    "Visa sponsorship is available for this role under certain circumstances.",
    "We are happy to sponsor the right candidate.",
    "We can sponsor candidates already in the UK.",
])
def test_offers_are_read_as_offers(description):
    state, quote = classify_sponsorship("Designer", description)
    assert state == "offered"
    assert "sponsor" in quote.lower()


@pytest.mark.parametrize("description", [
    # A fact about the employer, not an offer for this job.
    "Whilst the University is a licensed sponsor, under UK Visas and Immigration "
    "(UKVI) rules not all roles are eligible.",
    # An explicit statement that this job does NOT qualify.
    "Please note that this vacancy does not currently meet the minimum salary "
    "threshold requirements for Skilled Worker sponsorship.",
])
def test_employer_facts_are_not_read_as_offers(description):
    assert classify_sponsorship("Designer", description)[0] != "offered"


def test_refusal_wins_when_a_posting_says_both():
    """66 corpus postings match both patterns, and in every sampled one the offer
    wording sat inside the refusal ("unable to OFFER SPONSORSHIP"). Reading such a
    posting as an offer is the expensive error of the two."""
    state, _ = classify_sponsorship(
        "Designer",
        "We sponsor for some senior roles. For this position we cannot sponsor.",
    )
    assert state == "refused"


def test_silence_is_silence():
    """96% of postings say nothing about sponsorship. Silence must stay its own
    state — it is neither an offer nor a refusal, and no score may be derived
    from it."""
    assert classify_sponsorship("Digital Designer", "A great place to work.") == ("silent", None)


def test_every_verdict_in_the_corpus_quotes_the_posting(corpus):
    """The same assertion invariants.check_sponsorship_claims_carry_evidence makes
    against the stored DB, made here against a live re-read — so a regression in
    the extractor is caught before it reaches the database."""
    bad = []
    for j in corpus:
        title = j.get("title") or ""
        description = j.get("description") or j.get("snippet") or ""
        state, quote = classify_sponsorship(title, description)
        if state == "silent":
            continue
        if not quote or "sponsor" not in quote.lower():
            bad.append((title[:34], state, (quote or "")[:60]))
    assert not bad, bad[:5]


def test_the_invariant_catches_a_missing_quote():
    """A check that cannot fail is not a check."""
    import invariants

    fabricated = [
        {"title": "Fabricated", "analysis": {"sponsorship": "refused",
                                             "sponsorship_evidence": ""}},
        {"title": "Clipped", "analysis": {"sponsorship": "offered",
                                          "sponsorship_evidence": "Produce designs."}},
        {"title": "Fine", "analysis": {"sponsorship": "offered",
                                       "sponsorship_evidence": "Sponsorship is available."}},
        {"title": "Silent", "analysis": {"sponsorship": "silent"}},
    ]
    original = invariants.ANALYZED
    tmp = Path(ROOT) / "10_output" / "_test_sponsorship_fixture.json"
    try:
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(fabricated), encoding="utf-8")
        invariants.ANALYZED = tmp
        found = invariants.check_sponsorship_claims_carry_evidence({})
    finally:
        invariants.ANALYZED = original
        tmp.unlink(missing_ok=True)
    assert len(found) == 2
    assert "no evidence quote" in found[0]
    assert "do not contain the word" in found[1]


# A fourth way of getting it wrong, found the same way: the refusal pattern only
# allowed 30 characters between the negator and "sponsor", which fits "we cannot
# sponsor" and little else a real posting writes. The qualifier lives in exactly
# that gap, so ten postings that refuse in plain English were read as silent —
# four of them designer roles, i.e. jobs offered up as worth applying to at a
# company that had said it could not hire him.
@pytest.mark.parametrize("sentence", [
    "We cannot accept applications from anyone requiring sponsorship for UK employment.",
    "Please note that this role does not meet the eligibility criteria for visa sponsorship.",
    "On this occasion the University will not consider applicants requiring sponsorship for this role.",
    "This role does not meet the minimum requirements set by the UKVI to enable sponsorship of migrant workers.",
    "Please be aware that this role does not fulfil the requirements for visa sponsorship.",
    "This vacancy does not currently meet the minimum salary threshold requirements for Skilled Worker sponsorship.",
])
def test_refusal_survives_a_qualifier_between_the_negator_and_sponsor(sentence):
    state, evidence = classify_sponsorship("Graphic Designer", sentence)
    assert state == "refused", f"read as {state!r}: {sentence}"
    assert evidence and "sponsor" in evidence.lower()


def test_widened_gap_does_not_reach_across_a_sentence():
    """The gap reaches a qualifier, not a negator in the sentence before.

    A separate, older rule (_NEGATOR_NEAR looks back 60 characters) suppresses the
    offer here, so this reads as silent both before and after the widening — the
    point being asserted is only that "cannot" in the previous sentence does not
    now pair with this sentence's "sponsorship" and manufacture a refusal.
    """
    state, _ = classify_sponsorship(
        "Designer",
        "We cannot accept late applications. Visa sponsorship is available for this role.",
    )
    assert state != "refused"
