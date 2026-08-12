"""The persona the scorer sees must be the persona that was assembled.

It was truncated twice. `_load_persona_summary` capped each file and joined
them to 25,429 characters; the context prompt then cut the result at 14,000.
Nothing declared that second cut, and the per-file limits summed well past it,
so three files — about.md, interests.md and cover-letter-evidence.md — were
read from disk, capped, joined and then discarded in full, and ethos.md
arrived at 16% of itself. cover-letter-evidence.md is the file that exists to
evidence what the candidate has actually done, and `role_fit` is the axis that
asks exactly that, carrying 0.64 of the composite. It was answered without it.

The failure was invisible from either end: the loader looked correct because
it read every file, and the prompt looked correct because it capped a string.
Only their product was wrong. So the guard is on the product — assemble the
real persona, render the real prompt, and assert every file's marker survives
into the text that is sent.
"""
import re

import matcher
import pytest


@pytest.fixture(autouse=True)
def clear_persona_cache():
    matcher._persona_cache = None
    yield
    matcher._persona_cache = None


def _rendered_prompt(monkeypatch) -> str:
    """The prompt string _ollama_context_score actually hands to the LLM."""
    sent = {}

    def capture(messages, **_kw):
        sent["prompt"] = messages[0]["content"]
        raise RuntimeError("stop after capture")

    import llm_client
    monkeypatch.setattr(llm_client, "call_llm", capture)
    matcher._ollama_context_score("A job description. " * 40,
                                  matcher._load_persona_summary(), brief=True)
    return sent["prompt"]


def test_every_persona_file_survives_into_the_prompt(monkeypatch):
    persona = matcher._load_persona_summary()
    markers = re.findall(r"--- ([\w\-.]+\.md) ---", persona)
    assert markers, "persona assembled no files at all"

    prompt = _rendered_prompt(monkeypatch)
    missing = [m for m in markers if f"--- {m} ---" not in prompt]
    assert not missing, (
        f"assembled but never sent: {missing}. The prompt is truncating the "
        f"persona a second time (persona is {len(persona)} chars)."
    )


def test_persona_is_not_cut_between_assembly_and_prompt(monkeypatch):
    """Not just the headers — the bodies too.

    A cut that lands inside the last file would leave every marker present and
    still drop the evidence under it.
    """
    persona = matcher._load_persona_summary()
    prompt = _rendered_prompt(monkeypatch)
    assert persona in prompt, (
        f"persona is {len(persona)} chars but arrives in the prompt truncated"
    )


def test_no_persona_file_is_silently_halved():
    """Per-file limits exist to stop one runaway file starving the rest, not to
    trim files that fit. skills.md lost 5,628 of 12,128 characters to a 6,500
    limit nobody had sized against it.

    Covers the portfolio subset too. Those files carry the design and art work
    delivered, which is the evidence role_fit was missing when it undershot
    graphic_designer postings by 23 points — the one category a persona built
    only from the profile documents does not show.
    """
    persona = matcher._load_persona_summary()
    halved = []
    named = [(matcher.USER_PROFILE_DIR / f) for f in
             ["profile.md", "skills.md", "timeline.md", "education.md", "ethos.md",
              "about.md", "interests.md", "cover-letter-evidence.md"]]
    named += [(matcher.PORTFOLIO_DIR / f) for f in
              ["logo-design-for-myself.md",
               "connecting-the-dots-a-personal-graph-of-creative-practice.md",
               "taifunome.md", "hive-floral-pod-3d-conceptual-art.md",
               "so-close-yet-so-far-encounter-with-a-fox.md"]]
    for fpath in named:
        if not fpath.exists():
            continue
        content = fpath.read_text(encoding="utf-8").strip()
        if content and content not in persona:
            halved.append(f"{fpath.name} ({len(content)} chars)")
    assert not halved, f"truncated out of the persona: {halved}"


def test_persona_budget_admits_the_assembled_persona():
    """The two numbers that were allowed to disagree.

    This assertion used to read `len(_load_persona_summary()) <=
    PERSONA_CHAR_BUDGET`, which compares the cut string against the size it was
    cut to — true by construction, and it duly passed while the persona sat at
    exactly the budget with the portfolio files falling off the end. Assert on
    the length BEFORE the cut, which is the only number that can disagree.
    """
    matcher._load_persona_summary()
    assembled = matcher._persona_assembled_chars
    assert assembled > 0, "persona assembled nothing"
    assert assembled <= matcher.PERSONA_CHAR_BUDGET, (
        f"assembled persona is {assembled} chars but PERSONA_CHAR_BUDGET is "
        f"{matcher.PERSONA_CHAR_BUDGET} — {assembled - matcher.PERSONA_CHAR_BUDGET} "
        f"characters are being dropped off the tail"
    )


def test_job_description_budget_covers_a_normal_posting(monkeypatch):
    """A 9,608-character agency posting was cut at 5,000, so role_fit was
    scored on the generic first half."""
    long_desc = "X" * 9608
    sent = {}

    def capture(messages, **_kw):
        sent["prompt"] = messages[0]["content"]
        raise RuntimeError("stop after capture")

    import llm_client
    monkeypatch.setattr(llm_client, "call_llm", capture)
    matcher._ollama_context_score(long_desc, matcher._load_persona_summary(),
                                  brief=True)
    assert long_desc in sent["prompt"], (
        f"a {len(long_desc)}-char posting is truncated at "
        f"{matcher.JOB_DESC_CHAR_BUDGET}"
    )
