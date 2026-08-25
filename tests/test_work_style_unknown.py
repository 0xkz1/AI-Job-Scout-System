"""A posting that never says where the work happens has not said "on-site".

When the keyword classifier returns "unknown", an LLM is asked instead — and
its schema offered only remote|hybrid|onsite. With no "unknown" to answer, a
model reading silent text picks one, and it picks the one the matcher scores as
a severe penalty for a candidate who would have to relocate.

Measured 2026-08-26: 1704 postings are recorded onsite and 1104 of them contain
no wording about where the work happens at all. Moth's Creative Technologist
posting mentions neither an office, a city, nor a day pattern, and was marked
onsite — 0.25 on location where "unknown" scores 0.35.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import analyzer  # noqa: E402
import matcher  # noqa: E402


SILENT = ("Moth is a quantum computing company. You will build rapid prototypes "
          "and demos using our core technologies, and collaborate with artists "
          "and musicians to bring their ideas to life.")


# --- the schema must allow the honest answer ---

def test_the_prompt_offers_unknown_for_work_style():
    src = (ROOT / "analyzer.py").read_text(encoding="utf-8")
    assert '"work_style": "remote|hybrid|onsite|unknown"' in src, \
        "the enum forces a guess about something postings often do not state"


def test_the_validator_still_accepts_it():
    """The validator always allowed "unknown"; only the prompt withheld it."""
    src = (ROOT / "analyzer.py").read_text(encoding="utf-8")
    assert '"remote", "hybrid", "onsite", "unknown"' in src


# --- the guard on a verdict the text cannot support ---

def test_silent_text_supports_no_onsite_reading():
    assert not analyzer._ONSITE_EVIDENCE.search(SILENT)
    assert analyzer.classify_work_style("Creative Technologist", SILENT) == "unknown"


@pytest.mark.parametrize("text", [
    "Our work style is hybrid, two days per week in the Edinburgh office.",
    "This role is office-based.",
    "You will be on-site with the client.",
    "We expect you to attend the studio in person.",
    "The successful candidate will relocate to Bristol.",
])
def test_wording_about_place_is_recognised(text):
    assert analyzer._ONSITE_EVIDENCE.search(text)


def test_an_unsupported_onsite_verdict_is_downgraded(monkeypatch):
    monkeypatch.setattr(analyzer, "classify_experience_work_style_ollama",
                        lambda t, d: {"experience_level": "mid", "work_style": "onsite"})
    monkeypatch.setattr(analyzer, "extract_skills_ollama", lambda t, d: [])
    job = {"title": "Creative Technologist", "description": SILENT, "salary": ""}
    assert analyzer.analyze_job(job)["analysis"]["work_style"] == "unknown"


def test_a_supported_onsite_verdict_is_kept(monkeypatch):
    monkeypatch.setattr(analyzer, "classify_experience_work_style_ollama",
                        lambda t, d: {"experience_level": "mid", "work_style": "onsite"})
    monkeypatch.setattr(analyzer, "extract_skills_ollama", lambda t, d: [])
    job = {"title": "Creative Technologist", "salary": "",
           "description": SILENT + " You will be based in our London office five days a week."}
    assert analyzer.analyze_job(job)["analysis"]["work_style"] == "onsite"


def test_remote_and_hybrid_verdicts_are_never_touched(monkeypatch):
    """The guard exists because "onsite" is the costly default, not because the
    model is distrusted in general."""
    for style in ("remote", "hybrid"):
        monkeypatch.setattr(analyzer, "classify_experience_work_style_ollama",
                            lambda t, d, s=style: {"experience_level": "mid", "work_style": s})
        monkeypatch.setattr(analyzer, "extract_skills_ollama", lambda t, d: [])
        job = {"title": "Creative Technologist", "description": SILENT, "salary": ""}
        assert analyzer.analyze_job(job)["analysis"]["work_style"] == style


# --- what it is worth downstream ---

def test_unknown_costs_less_than_an_invented_commute():
    exp = matcher.load_user_experience()
    onsite = matcher.calculate_location_match("London, England, United Kingdom", "onsite",
                                              exp, country="UK")
    unknown = matcher.calculate_location_match("London, England, United Kingdom", "unknown",
                                               exp, country="UK")
    assert unknown["score"] > onsite["score"]
    assert not any("On-site required" in n for n in unknown["notes"])
