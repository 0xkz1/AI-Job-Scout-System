"""classify_experience_work_style_ollama must not crash on a malformed LLM answer.

Observed in a real run on 2026-08-05 (10_output/_nightly_scout.log):

    ⚠ enriched failed for UI/UX Designer: TypeError: unhashable type: 'list'
      File "analyzer.py", line 640, in classify_experience_work_style_ollama
        "experience_level": exp_level if exp_level in valid_exp else "unknown",
    TypeError: unhashable type: 'list'

The model answered with a list (e.g. ["mid"]) instead of a string, and
`x in some_set` raises for any unhashable x rather than returning False. 1 of
496 enriched jobs failed this way that night; match_all() catches the
exception so the run survives, but the job is left with no score at all.
"""
import analyzer


def _patch(monkeypatch, response):
    monkeypatch.setattr(analyzer, "_ollama_chat", lambda *a, **k: response)


def test_list_value_is_recovered_not_crashed(monkeypatch):
    # The formatting slip actually observed: a single-element list instead of
    # a bare string. Worth keeping, not discarding.
    _patch(monkeypatch, {"experience_level": ["mid"], "work_style": ["remote"]})
    result = analyzer.classify_experience_work_style_ollama("UI/UX Designer", "desc")
    assert result == {"experience_level": "mid", "work_style": "remote"}


def test_multi_element_list_takes_the_first_element(monkeypatch):
    # No principled way to disambiguate several options, but the model puts
    # its best guess first — same convention _ollama_chat's own array-mode
    # callers already rely on — so this is still information worth keeping
    # rather than a value to discard.
    _patch(monkeypatch, {"experience_level": ["mid", "senior"], "work_style": "remote"})
    result = analyzer.classify_experience_work_style_ollama("UI/UX Designer", "desc")
    assert result["experience_level"] == "mid"
    assert result["work_style"] == "remote"


def test_dict_value_does_not_crash(monkeypatch):
    # Any other unhashable shape must degrade the same way as a list, not raise.
    _patch(monkeypatch, {"experience_level": {"level": "mid"}, "work_style": "onsite"})
    result = analyzer.classify_experience_work_style_ollama("UI/UX Designer", "desc")
    assert result == {"experience_level": "unknown", "work_style": "onsite"}


def test_none_value_does_not_crash(monkeypatch):
    _patch(monkeypatch, {"experience_level": None, "work_style": None})
    result = analyzer.classify_experience_work_style_ollama("UI/UX Designer", "desc")
    assert result == {"experience_level": "unknown", "work_style": "unknown"}


def test_valid_string_still_passes_through(monkeypatch):
    # The guard must not turn a normal, well-formed answer into "unknown".
    _patch(monkeypatch, {"experience_level": "senior", "work_style": "hybrid"})
    result = analyzer.classify_experience_work_style_ollama("UI/UX Designer", "desc")
    assert result == {"experience_level": "senior", "work_style": "hybrid"}


def test_unrecognised_string_still_falls_back(monkeypatch):
    # A string outside the allowed set was already handled correctly before
    # this fix — must stay that way.
    _patch(monkeypatch, {"experience_level": "expert", "work_style": "hybrid"})
    result = analyzer.classify_experience_work_style_ollama("UI/UX Designer", "desc")
    assert result["experience_level"] == "unknown"
