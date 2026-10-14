"""Important reviews keep their model and see the complete document."""

import pytest

import key_quarantine
import reviewer


@pytest.fixture
def review_inputs(monkeypatch, tmp_path):
    monkeypatch.delenv("REVIEW_FALLBACKS", raising=False)
    monkeypatch.setattr(key_quarantine, "is_quarantined", lambda _provider: False)
    monkeypatch.setattr(reviewer, "_load_review_facts", lambda: "facts")
    monkeypatch.setattr(reviewer, "_load_skills_md", lambda: "skills")
    monkeypatch.setattr(reviewer, "_load_decisions", lambda: "decisions")
    monkeypatch.setattr(reviewer, "REVIEWS_DIR", tmp_path / "reviews")
    monkeypatch.setattr(reviewer, "PRISTINE_DIR", tmp_path / "pristine")
    monkeypatch.setattr(reviewer, "ARCHIVE_DIR", tmp_path / "archive")
    doc = tmp_path / "Example_CV.md"
    doc.write_text("# Candidate\n" + "Relevant work experience.\n" * 350
                   + "## Education\nTAIL_EDUCATION_SENTINEL\n")
    return doc


def test_default_review_chain_uses_only_the_strong_alias(review_inputs):
    assert reviewer._review_chain() == [
        ("litellm-gateway", f"review-strong-glm53-key{i}") for i in range(1, 8)
    ]


def test_review_prompt_contains_the_document_tail(monkeypatch, review_inputs):
    captured = []

    def fake_llm(**kwargs):
        captured.append(kwargs)
        raise RuntimeError("probe stopped before writing")

    monkeypatch.setattr(reviewer, "call_llm", fake_llm)
    with pytest.raises(RuntimeError, match="probe stopped"):
        reviewer.run_review("CV", review_inputs, {"title": "Designer"})

    assert len(captured) == 7
    prompt = captured[0]["messages"][0]["content"]
    assert "Relevant work experience.\n" * 350 in prompt
    assert "TAIL_EDUCATION_SENTINEL" in prompt
    assert captured[0]["provider"] == "litellm-gateway"
    assert captured[0]["model"] == "review-strong-glm53-key1"
    assert captured[0]["use_fallbacks"] is False


@pytest.mark.parametrize("failure", ["exception", "empty", "off_format"])
def test_failed_strong_review_keeps_existing_review(monkeypatch, review_inputs, failure):
    directory = reviewer.REVIEWS_DIR
    directory.mkdir()
    old_review = directory / "Example_CV_review.md"
    original = "---\nreview_model: previous-model\n---\nPrevious review.\n"
    old_review.write_text(original)
    calls = []

    def fake_llm(**kwargs):
        calls.append((kwargs["provider"], kwargs["model"]))
        if failure == "exception":
            raise RuntimeError("upstream unavailable")
        return "" if failure == "empty" else "Unstructured response. " * 30

    monkeypatch.setattr(reviewer, "call_llm", fake_llm)
    with pytest.raises(RuntimeError, match="All review providers failed"):
        reviewer.run_review("CV", review_inputs, {})

    assert calls == [("litellm-gateway", f"review-strong-glm53-key{i}")
                     for i in range(1, 8)]
    assert old_review.read_text() == original
    assert list(directory.iterdir()) == [old_review]
