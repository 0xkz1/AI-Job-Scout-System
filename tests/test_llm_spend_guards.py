"""LLM calls must not be spent on postings the pipeline has already rejected.

analyze_match calls the model once per job for context scoring. run.py used to
run it over `_enriched + _drop` — every scraped job, including the ones
filter_jobs had just excluded on title, level or salary. Measured on the
2026-08-05 run: 181 of 677 jobs, 27% of that pass, went to postings that could
never reach a CV.

The rejects stay in the DB on purpose (loosening a filter keyword later must not
require a re-scrape), so they still get a composite — from TF-IDF, which costs
nothing.
"""
import ast
import pathlib

import pytest

import matcher

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def counted_llm(monkeypatch):
    """Count context-scoring calls instead of making them."""
    calls = []

    def fake(description, persona):
        calls.append(description)
        return {"score": 0.9, "reasoning": "looks relevant", "top_terms": ["design"]}

    monkeypatch.setattr(matcher, "_ollama_context_score", fake)
    monkeypatch.setattr(matcher, "_load_persona_summary", lambda: "a designer")
    return calls


def _job():
    return {
        "title": "Product Designer",
        "company": "Acme",
        "location": "Edinburgh",
        "description": "design systems, figma, prototyping, user research " * 20,
        "salary": "",
        "analysis": {},
    }


def test_skip_llm_context_makes_no_model_call(counted_llm):
    matcher.analyze_match(_job(), {}, skip_llm_context=True)
    assert counted_llm == []


def test_default_still_scores_context_with_the_model(counted_llm):
    matcher.analyze_match(_job(), {})
    assert len(counted_llm) == 1


def test_skipped_job_still_gets_a_composite(counted_llm):
    # The DB must not grow holes: everything downstream reads composite_score,
    # and filter_jobs keeps rejects so a loosened keyword needs no re-scrape.
    result = matcher.analyze_match(_job(), {}, skip_llm_context=True)
    assert isinstance(result.get("composite_score"), float)
    assert result.get("context_source") == "tfidf"


def test_stored_llm_context_is_reused_not_discarded(counted_llm):
    # A job already scored by the model keeps that score even when the flag is
    # set — the flag suppresses new spend, it does not throw away old spend.
    job = _job()
    job["match"] = {"context_source": "llm", "context_score": 0.77,
                    "context_reasoning": "prior verdict"}
    result = matcher.analyze_match(job, {}, skip_llm_context=True)
    assert counted_llm == []
    assert result["context_score"] == 0.77
    assert result["context_source"] == "llm"


def test_context_backfill_skips_filtered_out_jobs():
    """The second half of the same leak.

    llm_context_backfill ranks by composite and takes the top N. A rejected
    posting is usually rejected on its TITLE while scoring well on everything
    else, so it ranks high: 85 of the top 250 (34%) failed passes_filter when
    measured. Worse, run.py now leaves rejects on a cheap TF-IDF context score —
    exactly what this pass hunts for — so without the gate it would re-buy every
    call run.py just avoided, nightly.
    """
    source = (ROOT / "llm_context_backfill.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    called = {n.func.id for n in ast.walk(main)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "passes_filter" in called, (
        "llm_context_backfill.main() no longer gates on passes_filter — the "
        "config's rejects are back at the front of the scoring queue"
    )


def test_run_py_does_not_send_filtered_out_jobs_to_the_llm():
    """The wiring, not just the flag: run.py must score the two groups apart.

    A single `match_all(new_analyzed, config)` over `_enriched + _drop` is the
    regression this guards — it type-checks, runs clean, and quietly pays for
    every reject.
    """
    tree = ast.parse((ROOT / "run.py").read_text(encoding="utf-8"))
    match_all_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "match_all"
    ]
    assert match_all_calls, "match_all is no longer called from run.py"

    for call in match_all_calls:
        first = call.args[0] if call.args else None
        if isinstance(first, ast.Name) and first.id == "new_analyzed":
            pytest.fail(
                "run.py scores `new_analyzed` (_enriched + _drop) in one pass, "
                "which spends an LLM context call on every filtered-out posting"
            )
        # Any pass over the rejects must say so explicitly.
        if isinstance(first, ast.Name) and first.id == "_drop":
            kwargs = {k.arg for k in call.keywords}
            assert "skip_llm_context" in kwargs, (
                "_drop is matched without skip_llm_context — the rejects are "
                "paying for context scoring again"
            )
