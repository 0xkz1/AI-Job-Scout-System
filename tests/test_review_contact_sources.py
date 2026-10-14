"""Configured contact values are evidence even without a persona mention."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import cv_generator as cv
import reviewer


def test_review_has_the_same_configured_contact_source_as_the_cv(monkeypatch):
    monkeypatch.setattr(reviewer,"_load_persona_summary",lambda:"Authored persona without a phone.")
    monkeypatch.setattr(cv,"_ALL_ENTRIES",[])
    monkeypatch.setattr(cv,"CONTACT",{"name":"Example Candidate","phone":"020 7946 0000",
                                      "email":"candidate@example.test","unexpected_secret":"DO_NOT_INCLUDE"})
    facts=reviewer._load_review_facts()
    assert "CONFIGURED APPLICATION CONTACT" in facts
    assert "phone: 020 7946 0000" in facts and "email: candidate@example.test" in facts
    assert "DO_NOT_INCLUDE" not in facts
