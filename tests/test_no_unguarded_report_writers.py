"""No module may rewrite a real match report without carrying the user's ticks.

generate_match_report defaults `expired` and `applied` to False and `carried`
to None. A caller that omits them and writes the result into
10_output/00_matches therefore clears whatever checkbox the user ticked and
drops the cv_pdf/cl_pdf/cv_review/cl_review links — silently, with the scores
still looking correct. That is what happened on 2026-08-06 when
regen_match_reports.py joined the nightly: 179 reports rewritten, 7
applied/expired ticks cleared, 14 link lines dropped.

save_match_report is the guarded path — it reads all three off the file it is
about to overwrite. Any other writer must pass them itself.

These tests read source, not behaviour, on purpose: the bug type-checks, runs
clean, and produces plausible output. Only the call site shows it.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The user's hand-ticked checkboxes. Never optional for a real report writer —
# losing one destroys information no rerun can reconstruct.
REQUIRED_FLAGS = {"expired", "applied"}

# matcher.py defines both functions; save_match_report is the guarded wrapper
# and is allowed to call the raw renderer.
EXEMPT_MODULES = {"matcher.py"}

# run.py passes expired/applied but not `carried`, because it preserves a
# SUPERSET of those keys by hand: PRESERVED_FRONTMATTER_PREFIXES adds
# applied_at:, which matcher._CARRIED_REPORT_KEYS does not include. Switching
# it to carried= would silently drop applied_at, so the exemption is the
# correct call — and test_run_py_preserves_carried_keys_its_own_way below
# holds it to that alternative.
CARRIED_EXEMPT = {"run.py"}


def _writes_to_match_dir(path):
    """Only modules that write into the live report directory can do damage.
    test_gen.py and test_wordsmith.py render into scratch paths instead."""
    return "00_matches" in path.read_text(encoding="utf-8")


def _modules():
    for path in sorted(ROOT.glob("*.py")):
        if path.name in EXEMPT_MODULES:
            continue
        if not _writes_to_match_dir(path):
            continue
        yield path


def _renderer_calls(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name == "generate_match_report":
            out.append((node.lineno, {kw.arg for kw in node.keywords if kw.arg}))
    return out


@pytest.mark.parametrize("path", list(_modules()), ids=lambda p: p.name)
def test_report_writers_carry_the_user_ticks(path):
    required = set(REQUIRED_FLAGS)
    if path.name not in CARRIED_EXEMPT:
        required.add("carried")

    problems = [
        f"{path.name}:{line} calls generate_match_report without "
        f"{sorted(required - passed)}"
        for line, passed in _renderer_calls(path)
        if required - passed
    ]
    assert not problems, (
        "\n".join(problems)
        + "\n\nThis silently clears the user's applied/expired ticks and drops "
          "PDF/review links. Use save_match_report, or pass them explicitly."
    )


def test_run_py_preserves_carried_keys_its_own_way():
    """run.py's exemption is only valid while its manual merge still exists."""
    src = (ROOT / "run.py").read_text(encoding="utf-8")
    assert "PRESERVED_FRONTMATTER_PREFIXES" in src, (
        "run.py is exempt from passing carried= because it merges those keys by "
        "hand. That mechanism is gone — either restore it or pass carried=."
    )
    for key in ("cv_pdf:", "cl_pdf:", "cv_review:", "cl_review:"):
        assert key in src, f"run.py no longer preserves {key}"


def test_save_match_report_passes_all_three():
    """The guarded path everything else is told to defer to."""
    tree = ast.parse((ROOT / "matcher.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "save_match_report")
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "generate_match_report"]
    assert calls, "save_match_report no longer renders a report"
    passed = {kw.arg for kw in calls[0].keywords if kw.arg}
    missing = (REQUIRED_FLAGS | {"carried"}) - passed
    assert not missing, (
        f"save_match_report is the safe wrapper every other module defers to, "
        f"but it is missing {sorted(missing)}"
    )


def test_the_guard_itself_detects_a_bad_call(tmp_path):
    # A guard that cannot fail is worth nothing — prove it catches the shape.
    bad = tmp_path / "bad_writer.py"
    bad.write_text(
        "from matcher import generate_match_report\n"
        "def go(job, match, path):  # writes into 10_output/00_matches\n"
        "    path.write_text(generate_match_report(job, match))\n",
        encoding="utf-8",
    )
    calls = _renderer_calls(bad)
    assert calls, "the guard failed to see the call at all"
    line, passed = calls[0]
    assert (REQUIRED_FLAGS | {"carried"}) - passed == {"expired", "applied", "carried"}
