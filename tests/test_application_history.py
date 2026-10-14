"""History must count Obsidian flags and never invent dates for manual ticks."""
import json
from datetime import date
from urllib.parse import parse_qs, urlparse

from application_history import history_counts, history_events, history_rows, load_history


def report(output, name, *, applied=False, expired=False, url="https://example.test/job/1",
           applied_at=None, company="Example", nested=False):
    folder = output / "00_matches"
    if nested:
        folder /= "job"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    front = f'company: "{company}"\ntitle: "Designer"\nurl: "{url}"\n'
    front += f"applied: {str(applied).lower()}\nexpired: {str(expired).lower()}\n"
    if applied_at is not None:
        front += f"applied_at: {applied_at}\n"
    path.write_text(f"---\n{front}---\nJob description\n", encoding="utf-8")
    return path


def expiry_state(output, entries):
    (output / "_expiry_checks.json").write_text(json.dumps(entries), encoding="utf-8")


def test_duplicate_reports_and_conflicts_do_not_inflate_totals(tmp_path):
    report(tmp_path, "one.md", applied=True, applied_at="2026-09-08")
    report(tmp_path, "duplicate.md", applied=True, expired=True, applied_at="2026-09-12", nested=True)
    report(tmp_path, "one.sync-conflict-20260908-device.md", applied=True, url="https://example.test/conflict")
    report(tmp_path, "unchecked.md", applied_at="2026-09-01", url="https://example.test/unchecked")
    jobs, warnings = load_history(tmp_path)
    assert not warnings
    assert len(jobs) == 1
    assert jobs[0]["applied_date"] == date(2026, 9, 8)
    assert len(jobs[0]["report_paths"]) == 2
    assert history_counts(jobs, date(2026, 9, 30)) == {
        "applied": 1, "this_month": 1, "expired": 1, "applied_undated": 0, "expired_undated": 1,
    }


def test_undated_ticks_count_without_borrowing_file_mtime_or_live_check(tmp_path):
    report(tmp_path, "manual.md", applied=True, expired=True, applied_at="not-a-date")
    expiry_state(tmp_path, {"https://example.test/job/1": {
        "verdict": "live", "checked_at": "2026-09-01T01:00:00+00:00",
    }})
    jobs, _ = load_history(tmp_path)
    counts = history_counts(jobs, date(2026, 9, 1))
    assert counts["applied"] == counts["applied_undated"] == 1
    assert counts["expired"] == counts["expired_undated"] == 1
    assert counts["this_month"] == 0
    assert history_events(jobs) == []


def test_confirmation_is_converted_before_assigning_calendar_day(tmp_path):
    report(tmp_path, "gone.md", expired=True)
    expiry_state(tmp_path, {"https://example.test/job/1": {
        "verdict": "gone", "checked_at": "2026-08-31T18:28:42.339582+00:00",
    }})
    jobs, _ = load_history(tmp_path)
    assert history_events(jobs, "Asia/Tokyo")[0]["date"] == date(2026, 9, 1)
    assert history_events(jobs, "Europe/London")[0]["date"] == date(2026, 8, 31)
    assert history_rows(jobs)[0]["期限切れ確認日時"] == "2026-09-01 03:28:42"


def test_cache_cannot_add_expired_status_to_an_unchecked_report(tmp_path):
    report(tmp_path, "applied.md", applied=True, applied_at="2026-09-08")
    expiry_state(tmp_path, {"https://example.test/job/1": {
        "verdict": "gone", "checked_at": "2026-09-01T01:00:00Z",
    }})
    jobs, _ = load_history(tmp_path)
    assert not jobs[0]["expired"]
    assert jobs[0]["expired_checked_at"] is None
    assert [e["kind"] for e in history_events(jobs)] == ["applied"]


def test_invalid_cache_does_not_hide_checked_jobs(tmp_path):
    report(tmp_path, "gone.md", expired=True)
    (tmp_path / "_expiry_checks.json").write_text('{"partial":', encoding="utf-8")
    jobs, warnings = load_history(tmp_path)
    assert len(jobs) == 1
    assert history_counts(jobs, date(2026, 9, 1))["expired_undated"] == 1
    assert warnings


def test_missing_urls_do_not_merge_unrelated_jobs(tmp_path):
    report(tmp_path, "first.md", applied=True, url="")
    report(tmp_path, "second.md", applied=True, url="", company="Other")
    jobs, _ = load_history(tmp_path)
    assert history_counts(jobs, date(2026, 9, 1))["applied"] == 2


def test_invalid_or_timezone_missing_confirmation_is_unknown(tmp_path):
    report(tmp_path, "gone.md", expired=True)
    for timestamp in [None, "broken", "2026-09-01T01:00:00"]:
        expiry_state(tmp_path, {"https://example.test/job/1": {"verdict": "gone", "checked_at": timestamp}})
        jobs, _ = load_history(tmp_path)
        assert jobs[0]["expired_checked_at"] is None


def test_loading_never_writes_to_the_vault(tmp_path):
    report(tmp_path, "applied.md", applied=True, applied_at="2026-09-08")
    expiry_state(tmp_path, {})
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    jobs, _ = load_history(tmp_path)
    history_events(jobs)
    history_counts(jobs, date(2026, 9, 1))
    history_rows(jobs)
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


def test_obsidian_links_use_vault_paths_for_other_synced_devices(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    output = tmp_path / "career" / "Job-Intelligence-System" / "10_output"
    report(output, "Example Designer.md", applied=True)
    jobs, _ = load_history(output)
    uri = history_rows(jobs)[0]["求人ノート"]
    assert uri.startswith("obsidian://open?")
    assert parse_qs(urlparse(uri).query) == {
        "vault": [tmp_path.name],
        "file": ["career/Job-Intelligence-System/10_output/00_matches/Example Designer.md"],
    }
