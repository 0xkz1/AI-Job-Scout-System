"""A reply cut off after the scores still carries the scores.

The context prompt asks for `ethos` and `role_fit` first and the long bilingual
reasoning last. The parser looked for `{...}`, which needs a closing brace, so a
reply truncated mid-sentence matched nothing and the call was recorded as a
failure — discarding two complete, correct numbers because the prose after them
was incomplete.

Moth's Creative Technologist posting — the flagship target title — did exactly
this: the model returned ethos 88 and role_fit 72 and was cut mid-word, and the
posting was left on a TF-IDF 0.25 and then on `unscored`, reading 28% overall.
Sampled over nine live calls, four came back truncated.

The cause is prompt size, not the provider: the persona summary alone is 55k
characters and the whole request runs to ~61.5k, so the completion budget is
what gives. Raising max_tokens was already tried against this same symptom
(300 -> 600/900) and cannot fix a prompt that keeps growing.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import matcher  # noqa: E402


CUT = ('{\n  "ethos": 88,\n  "role_fit": 72,\n'
       '  "role_requirement": "Building prototypes from quantum research",\n'
       '  "reasoning_en": "Kazuki\'s philosophy of merging art and technology align')


# --- the salvage itself ---

def test_the_complete_pairs_survive_a_cut_reply():
    out = matcher._close_truncated_json(CUT)
    assert out is not None
    import json
    data = json.loads(matcher._repair_json(out), strict=False)
    assert data["role_fit"] == 72
    assert data["ethos"] == 88
    assert data["role_requirement"].startswith("Building prototypes")


def test_the_incomplete_pair_is_dropped_not_guessed():
    import json
    data = json.loads(matcher._repair_json(matcher._close_truncated_json(CUT)), strict=False)
    assert "reasoning_en" not in data, "half a sentence was kept as if it were the reasoning"


def test_a_complete_reply_is_left_to_the_ordinary_path():
    assert matcher._close_truncated_json('{"role_fit": 70, "ethos": 80}') is None


def test_a_reply_with_no_object_at_all_is_not_invented():
    assert matcher._close_truncated_json("I am sorry, I cannot help with that") is None


def test_a_reply_cut_before_any_complete_pair_yields_nothing():
    assert matcher._close_truncated_json('{\n  "ethos": 8') is None


# --- it must not cut in the wrong place ---

def test_a_comma_inside_a_string_is_not_a_pair_boundary():
    out = matcher._close_truncated_json('{"a": "x, y", "b": "unterminated')
    assert out == '{"a": "x, y"}'


def test_an_escaped_quote_does_not_end_the_string():
    out = matcher._close_truncated_json(r'{"a": "he said \"no\", loudly", "b": "cut')
    assert out == r'{"a": "he said \"no\", loudly"}'


def test_a_comma_inside_a_nested_object_is_not_a_boundary():
    out = matcher._close_truncated_json('{"a": {"x": 1, "y": 2}, "b": "cut')
    assert out == '{"a": {"x": 1, "y": 2}}'


# --- end to end ---

def _score(monkeypatch, reply):
    monkeypatch.setattr("llm_client.call_llm", lambda **kw: reply)
    return matcher._ollama_context_score("a job description, long enough to pass",
                                         "a persona summary", brief=True)


def test_a_truncated_reply_now_produces_a_score(monkeypatch):
    out = _score(monkeypatch, CUT)
    assert out is not None, "a reply carrying both scores was still recorded as a failure"
    assert out["score"] == 0.72
    assert out["ethos"] == 0.88


def test_the_salvaged_score_carries_no_invented_reasoning(monkeypatch):
    out = _score(monkeypatch, CUT)
    assert out["reasoning_en"] == ""


def test_a_complete_reply_is_unchanged(monkeypatch):
    out = _score(monkeypatch, '{"ethos": 80, "role_fit": 65, "reasoning_en": "Fits well."}')
    assert out["score"] == 0.65
    assert out["reasoning_en"] == "Fits well."


def test_an_unusable_reply_is_still_a_failure(monkeypatch):
    """"Could not tell" has to stay reachable — see the unscored path."""
    assert _score(monkeypatch, "the model refused") is None
