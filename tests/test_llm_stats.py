"""Per-stage LLM cost accounting, and the reasons it has to be cheap and quiet.

The tiering decision — which stage gets a fast model and which gets a careful
one — was about to be made from stage names. That is how url-list "extraction"
nearly ended up on a 20B model: it reads 15,000 characters and reproduces a
whole job description at max_tokens=4096, and the name gives none of that away.
So the stages are measured instead.

This sits in front of every LLM call in the pipeline, which sets the two
constraints these pin: it must cost nothing when nobody asked for it, and it
must never be able to break a scrape.
"""
import os

import pytest

import llm_client
import llm_stats


@pytest.fixture
def stats_file(tmp_path, monkeypatch):
    path = tmp_path / "stats.tsv"
    monkeypatch.setenv("JIS_LLM_STATS_FILE", str(path))
    return path


def test_a_call_is_recorded_as_one_row(stats_file):
    llm_client.record_llm_call("matcher", "groq-fast", 0.62, 900, 280, "ok")
    assert stats_file.read_text() == "matcher\tgroq-fast\t0.62\t900\t280\tok\n"


def test_nothing_is_written_when_no_file_is_named(tmp_path, monkeypatch):
    """An interactive run must not pay for bookkeeping nobody asked for."""
    monkeypatch.delenv("JIS_LLM_STATS_FILE", raising=False)
    llm_client.record_llm_call("matcher", "groq-fast", 0.6, 900, 280, "ok")
    assert list(tmp_path.iterdir()) == []


def test_an_unwritable_path_does_not_raise(monkeypatch):
    """A statistics file that can break a scrape is worse than no statistics
    file. This runs in front of every LLM call in the pipeline."""
    monkeypatch.setenv("JIS_LLM_STATS_FILE", "/proc/definitely/not/writable")
    llm_client.record_llm_call("matcher", "groq-fast", 0.6, 900, 280, "ok")


def test_the_caller_is_named_not_llm_client(stats_file):
    """Every row would say `llm_client` if the frame walk stopped at the first
    one, which would make the whole file useless for the question it exists to
    answer."""
    import types
    mod = types.ModuleType("matcher")
    mod.__dict__["llm_client"] = llm_client
    exec("def go():\n    return llm_client._calling_stage()", mod.__dict__)
    assert mod.go() == "matcher"


def test_rows_that_are_not_six_fields_are_skipped(stats_file):
    stats_file.write_text(
        "matcher\tgroq-fast\t0.6\t900\t280\tok\n"
        "half a line\n"
        "reviewer\tdeep-review\tnot-a-float\t900\t280\tok\n"
        "reviewer\tdeep-review\t38.0\t98000\t4000\tok\n")
    rows = llm_stats.load(stats_file)
    assert len(rows) == 2
    assert {r["stage"] for r in rows} == {"matcher", "reviewer"}


def test_a_missing_file_reads_as_no_rows(tmp_path):
    assert llm_stats.load(tmp_path / "never-written.tsv") == []


def test_failed_calls_are_recorded_too(stats_file):
    """A chain that falls through is the cost nobody sees — the failed attempt
    is paid for in full before the next provider is tried. On 2026-08-17 seven
    NVIDIA keys were each abandoned at 45s on every review, 315s a review, while
    the provider itself was healthy."""
    llm_client.record_llm_call("reviewer", "nvidia-nim", 45.0, 98000, 4000, "transient")
    llm_client.record_llm_call("reviewer", "mistral-medium", 25.1, 98000, 4000, "ok")
    rows = llm_stats.load(stats_file)
    assert [r["outcome"] for r in rows] == ["transient", "ok"]
    assert sum(r["elapsed"] for r in rows if r["outcome"] != "ok") == 45.0


def test_the_summary_survives_an_empty_file(stats_file, capsys):
    stats_file.write_text("")
    llm_stats.summarise(llm_stats.load(stats_file), "stage")
    assert "no rows" in capsys.readouterr().out


def test_the_summary_ranks_by_total_time_not_call_count(stats_file, capsys):
    """"Where did the night go" is a sum. Ranking by calls would put matcher —
    hundreds of sub-second calls — above the reviewer that spent minutes."""
    for _ in range(50):
        llm_client.record_llm_call("matcher", "groq-fast", 0.6, 900, 280, "ok")
    llm_client.record_llm_call("reviewer", "deep-review", 400.0, 98000, 4000, "ok")
    llm_stats.summarise(llm_stats.load(stats_file), "stage")
    out = capsys.readouterr().out
    assert out.index("reviewer") < out.index("matcher")
