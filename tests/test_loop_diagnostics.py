"""Offline observations must not become invented root causes or repair outcomes."""
import json
import subprocess
import sys

import pytest

import loop_repair as lr


@pytest.mark.parametrize("statuses,yields,expected", [
    (["ok", "ok"], [0, 0], "empty-unexplained"),
    (["ok", "timeout"], [0, 0], "timeout-or-partial"),
    (["ok", "partial"], [0, 3], "timeout-or-partial"),
    (["ok", "skipped"], [0, 0], "budget-skipped"),
    (["ok", "auth"], [0, 0], "access-blocked"),
    (["ok", "error"], [0, 0], "scrape-error"),
    (["ok", "ok"], [0, 4], "returning-jobs"),
    ([], [0, 0], "insufficient-evidence"),
])
def test_diagnosis_preserves_what_is_known(tmp_path, monkeypatch, statuses, yields, expected):
    for attr, values in [("YIELD_HISTORY", yields), ("STATUS_HISTORY", statuses)]:
        path = tmp_path / attr
        path.write_text(json.dumps({"guardian": values}))
        monkeypatch.setattr(lr, attr, path)
    result = lr.diagnose_site("guardian")
    assert result["diagnosis"] == expected
    assert result["recent_yields"] == yields
    assert result["recent_statuses"] == statuses
    assert result["selector_failure_proven"] is False


def test_diagnose_command_does_not_spawn_or_acknowledge_notifications(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["loop_repair.py", "--diagnose"])
    for attr in ["YIELD_HISTORY", "STATUS_HISTORY", "REPAIR_STATE"]:
        path = tmp_path / attr
        path.write_text(json.dumps({"guardian": {"attempts": 2}} if attr == "REPAIR_STATE" else {}))
        monkeypatch.setattr(lr, attr, path)
    before = lr.REPAIR_STATE.read_bytes()
    monkeypatch.setattr(lr, "_run", lambda *a, **k: pytest.fail("diagnosis must not spawn"))
    assert lr.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["execution"][0]["exhausted"]
    assert result["outcome"]["restored_scrapers"] is None
    assert lr.REPAIR_STATE.read_bytes() == before


def test_forcing_a_site_cannot_bypass_attempt_cap(tmp_path, monkeypatch):
    path = tmp_path / "repair.json"
    path.write_text(json.dumps({"guardian": {"attempts": 2}}))
    monkeypatch.setattr(lr, "REPAIR_STATE", path)
    assert lr.pick_site("guardian")[0] is None


def test_alternate_data_root_reads_status_only_failures_without_writes(tmp_path):
    folder = tmp_path / "10_output"
    folder.mkdir()
    (folder / lr.STATUS_HISTORY.name).write_text(json.dumps({"saved_bodies": ["error"]}))
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    report = lr.diagnostic_report(tmp_path)
    assert report["execution"][0]["site"] == "saved_bodies"
    assert report["execution"][0]["diagnosis"] == "scrape-error"
    assert before == {p.name: p.read_bytes() for p in folder.iterdir()}


def test_prompt_reports_zero_observations_without_claiming_successful_execution():
    prompt = lr.PROMPT.format(scraper="s.py", nights=2, doc="d.md")
    assert "2 trailing zero entries" in prompt
    assert "missing status\nis unknown" in prompt
    assert "Every other site" not in prompt
    assert "exits 0" not in prompt


def test_noop_retains_worker_explanation(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "run_agent", lambda *a, **k: "Search is legitimately empty; no selector edit justified.")
    monkeypatch.setattr(lr, "changed_files", lambda *a: [])
    monkeypatch.setattr(lr, "_run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, stdout=""))
    ok, _, why, touched, rounds = lr.attempt_repair(tmp_path, "guardian", "scraper_guardian.py", 2, set())
    assert not ok and not touched and rounds == lr.MAX_ROUNDS
    assert "legitimately empty" in why


def test_malformed_staging_does_not_count_as_valid_jobs(tmp_path):
    folder = tmp_path / "00_saved"
    folder.mkdir()
    (folder / "_raw_guardian_fixture.json").write_text(json.dumps([
        None, "bad", {"url": "https://", "title": "A"},
        {"url": "https://jobs.example/1", "title": ""},
        {"url": "https://jobs.example/2", "title": "Designer"},
    ]))
    assert lr.inspect_staged(tmp_path, "guardian")[:2] == (5, 1)


@pytest.mark.parametrize("code", [2, 3, 5])
def test_unmeasurable_pytest_exit_is_not_a_green_baseline(tmp_path, monkeypatch, code):
    monkeypatch.setattr(lr, "_run", lambda cmd, **kw:
                        subprocess.CompletedProcess(cmd, code, stdout="no tests ran", stderr=""))
    red, why = lr.failing_tests(tmp_path)
    assert red == {"__unmeasurable__"}
    assert f"exited {code}" in why
