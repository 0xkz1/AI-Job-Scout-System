"""A composite is computed from the CONFIG's weights, never the job's snapshot.

`match["weights"]` records what the weights were when a job was last fully
scored. Every pass that rewrites a composite used to read them back from there —
llm_context_backfill, rescore_context, and run.py's --llm-context loop — so the
moment config.yaml changed, those passes carried on scoring with the superseded
numbers and the database split into two populations that could not be compared
against each other.

That is not hypothetical. The 2026-08-24 reweighting moved skills 0.20 -> 0.45
and context 0.64 -> 0.40, and Lloyds Banking Group's Software Engineer report
still read "Skills 20% | Role Fit 64%" days later over a composite computed from
them. llm_context_backfill's own fallback was a third set again — skills 0.4,
experience 0.25 — matching neither the config nor DEFAULT_WEIGHTS.
"""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matcher  # noqa: E402

SHIPPED = {"skills": 0.45, "experience": 0.05, "location": 0.10,
           "salary": 0.00, "context": 0.40}


# --- the helper ---

def test_the_config_supplies_the_weights():
    assert matcher.composite_weights({"weights": SHIPPED}) == SHIPPED


def test_a_job_s_stored_weights_are_not_consulted():
    """The helper takes a config, not a job. There is deliberately no way to
    hand it match["weights"] by accident."""
    got = matcher.composite_weights({"weights": SHIPPED})
    stale = {"skills": 0.20, "experience": 0.05, "location": 0.10,
             "salary": 0.01, "context": 0.64}
    assert got != stale


def test_an_absent_config_falls_back_to_one_named_default():
    assert matcher.composite_weights({}) == matcher.composite_weights(None)
    assert matcher.composite_weights({})["skills"] == \
        matcher.DEFAULT_WEIGHTS["skills"]


def test_a_partial_config_is_filled_in_not_rejected():
    got = matcher.composite_weights({"weights": {"skills": 0.9}})
    assert got["skills"] == 0.9
    assert set(got) == set(SHIPPED)


def test_an_explicit_override_still_wins():
    """A grid search scoring against something other than the shipped weights is
    the one legitimate caller, and has to stay possible."""
    other = dict(SHIPPED, skills=0.10, context=0.75)
    assert matcher.composite_weights({"weights": SHIPPED}, override=other) == other


# --- the passes that rewrite a composite ---

@pytest.mark.parametrize("module", ["llm_context_backfill", "rescore_context"])
def test_the_nightly_passes_use_the_helper(module):
    source = (ROOT / f"{module}.py").read_text(encoding="utf-8")
    assert "composite_weights(config)" in source, (
        f"{module} builds its own weight dict again — a config change will not "
        "reach it"
    )


@pytest.mark.parametrize("module", ["llm_context_backfill", "rescore_context"])
def test_no_pass_reads_the_weights_off_the_job(module):
    """`m["weights"]` / `m.get("weights")` on the READ side is the bug."""
    tree = ast.parse((ROOT / f"{module}.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        # m["weights"] as a value, not as an assignment target
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and node.slice.value == "weights" and isinstance(node.ctx, ast.Load):
            pytest.fail(f"{module} still reads weights off the job")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and node.args \
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == "weights":
            pytest.fail(f"{module} still reads weights off the job via .get")


@pytest.mark.parametrize("module", ["llm_context_backfill", "rescore_context"])
def test_the_pass_records_what_it_scored_with(module):
    """Rewriting a composite without updating match["weights"] leaves the report
    printing one set of numbers over a total computed from another."""
    source = (ROOT / f"{module}.py").read_text(encoding="utf-8")
    assert 'm["weights"] = w' in source


def test_analyze_match_goes_through_the_same_helper():
    source = (ROOT / "matcher.py").read_text(encoding="utf-8")
    assert "weights = composite_weights(config, override=weights)" in source, (
        "analyze_match has its own copy again — two definitions will drift"
    )
