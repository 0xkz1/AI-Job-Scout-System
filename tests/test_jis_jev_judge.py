"""Unit and contract tests for jis_jev_judge.py."""
import pytest
from types import SimpleNamespace

import jis_jev_judge as judge


def test_is_configured_runs_without_crash():
    # Verify is_configured returns a boolean
    res = judge.is_configured()
    assert isinstance(res, bool)


def test_check_sponsorship_heuristic():
    res = judge._check_sponsorship_heuristic("We offer UK skilled worker visa sponsorship for this role.")
    assert res["sponsorship_likely"] is True
    assert res["blocked_by_visa"] is False

    res_neg = judge._check_sponsorship_heuristic("Candidates must have right to work in the UK; no visa sponsorship provided.")
    assert res_neg["sponsorship_likely"] is False
    assert res_neg["blocked_by_visa"] is True


def test_classify_role_heuristic():
    res = judge._classify_role_heuristic("Senior Graphic Designer", "Visual and brand design, typography")
    assert res["role"] == "graphic_designer" or res["role"] is not None


def test_fast_pre_audit_documents():
    job = {"company": "TestCo", "title": "Creative Technologist"}
    cv_valid = "Personal Profile\nCreative Technologist with experience in WebGL and Python.\n" + ("x" * 800)
    cl_valid = "Dear Hiring Team,\nI am writing to express my interest in the position.\n" + ("x" * 300)

    res = judge.fast_pre_audit_documents(cv_valid, cl_valid, job)
    assert res["passed"] is True
    assert len(res["violations"]) == 0

    # Test failure on placeholder
    cv_placeholder = cv_valid + "\nWorked at [Company] as [Title]."
    res_bad = judge.fast_pre_audit_documents(cv_placeholder, cl_valid, job)
    assert res_bad["passed"] is False
    assert any("[Company]" in v for v in res_bad["violations"])


def test_mocked_jev_sponsorship(monkeypatch):
    monkeypatch.setattr(judge, "is_configured", lambda: True)
    monkeypatch.setattr(judge, "_sdk_types", lambda: (None, lambda **kwargs: None, None, None))

    def mock_system_one(**kwargs):
        return SimpleNamespace(
            nouls={
                "sponsorship_offered": SimpleNamespace(noul=0.92),
                "visa_barrier": SimpleNamespace(noul=0.05),
            }
        )

    monkeypatch.setattr(judge, "get_client", lambda: SimpleNamespace(system_one=mock_system_one))

    res = judge.check_sponsorship_jev("Some posting text")
    assert res["source"] == "jev"
    assert res["sponsorship_offered_prob"] == 0.92
    assert res["sponsorship_likely"] is True

