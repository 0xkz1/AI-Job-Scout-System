"""Exercise review -> client -> streamed HTTP with key-specific failures."""

import json

import pytest
import requests

import key_quarantine
import llm_client
import reviewer

MODELS = [f"review-strong-glm53-key{i}" for i in range(1, 8)]
GOOD = ("```yaml\nrubric:\n  - requirement: design\n    evidence: Weak\n```\n\n"
        "### ❗ 事実\n問題なし\n\n### 🎯 求人適合\n"
        + "検証済みの経験を求人票の要件と照合して、具体的な根拠を確認する。\n" * 10
        + "\n### ✍️ 文体\n問題なし\n\n### 総評\n人間が最終確認する。\n")


class Response:
    def __init__(self, model, status=200, content=GOOD, done=True):
        self.status_code = status
        self.content = content
        self.done = done
        self.closed = False
        self.headers = {"x-litellm-model-group": model,
                        "x-litellm-model-name": "openai/z-ai/glm-5.3"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} rejected key", response=self)

    def iter_lines(self):
        yield b"data: " + json.dumps({"choices": [{"index": 0,
            "delta": {"content": self.content},
            "finish_reason": "stop" if self.done else None}]}).encode()
        if self.done:
            yield b"data: [DONE]"

    def close(self):
        self.closed = True


@pytest.fixture
def inputs(monkeypatch, tmp_path):
    monkeypatch.delenv("REVIEW_FALLBACKS", raising=False)
    monkeypatch.setenv("LITELLM_GATEWAY_API_KEY", "test-placeholder")
    monkeypatch.setenv("LITELLM_GATEWAY_URL", "http://127.0.0.1:4001")
    monkeypatch.setattr(key_quarantine, "STATE_FILE", tmp_path / "quarantine.json")
    monkeypatch.setattr(reviewer, "_load_review_facts", lambda: "facts")
    monkeypatch.setattr(reviewer, "_load_skills_md", lambda: "skills")
    monkeypatch.setattr(reviewer, "_load_decisions", lambda: "decisions")
    for name in ["REVIEWS_DIR", "PRISTINE_DIR", "ARCHIVE_DIR"]:
        monkeypatch.setattr(reviewer, name, tmp_path / name.lower())
    doc = tmp_path / "Example_CV.md"
    doc.write_text("# Candidate\nVerified work experience.\n")
    return doc


def install_http(monkeypatch, outcome):
    calls, responses = [], []

    def post(_url, **kwargs):
        model = kwargs["json"]["model"]
        calls.append(model)
        assert kwargs["stream"] is True
        assert kwargs["json"]["num_retries"] == 0
        response = outcome(model)
        responses.append(response)
        return response

    monkeypatch.setattr(llm_client.requests, "post", post)
    return calls, responses


@pytest.mark.parametrize("status", [401, 402, 403, 429])
def test_rejected_first_key_advances_and_is_skipped_next_time(monkeypatch, inputs, status):
    calls, responses = install_http(monkeypatch, lambda model:
        Response(model, status=status if model == MODELS[0] else 200))

    output = reviewer.run_review("CV", inputs, {})
    assert calls == MODELS[:2]
    assert "review-strong-glm53-key2:openai/z-ai/glm-5.3" in output.read_text()
    assert key_quarantine.is_quarantined("litellm-gateway:" + MODELS[0])
    assert not key_quarantine.is_quarantined("litellm-gateway:" + MODELS[1])
    assert not key_quarantine.is_quarantined("litellm-gateway")
    assert all(response.closed for response in responses)

    calls.clear()
    reviewer.run_review("CV", inputs, {})
    assert calls == [MODELS[1]]


def test_first_six_keys_exhausted_reaches_seventh(monkeypatch, inputs):
    calls, _ = install_http(monkeypatch, lambda model:
        Response(model, status=200 if model == MODELS[-1] else 402))
    output = reviewer.run_review("CV", inputs, {})
    assert calls == MODELS
    assert "review-strong-glm53-key7:openai/z-ai/glm-5.3" in output.read_text()


def test_all_keys_exhausted_preserves_previous_review(monkeypatch, inputs):
    reviewer.REVIEWS_DIR.mkdir()
    previous = reviewer.REVIEWS_DIR / "Example_CV_review.md"
    original = b"Previous accepted review.\n"
    previous.write_bytes(original)
    calls, _ = install_http(monkeypatch, lambda model: Response(model, status=402))
    with pytest.raises(RuntimeError, match="All review providers failed"):
        reviewer.run_review("CV", inputs, {})
    assert calls == MODELS
    assert previous.read_bytes() == original
    assert not reviewer.ARCHIVE_DIR.exists()


@pytest.mark.parametrize("failure", ["partial", "empty", "off_format", "timeout"])
def test_failed_answer_moves_to_next_key_without_saving_partial(monkeypatch, inputs, failure):
    def outcome(model):
        if model != MODELS[0]:
            return Response(model)
        if failure == "timeout":
            raise requests.ReadTimeout("upstream timed out")
        content = "PARTIAL_SENTINEL" if failure != "empty" else ""
        return Response(model, content=content, done=failure != "partial")

    calls, _ = install_http(monkeypatch, outcome)
    output = reviewer.run_review("CV", inputs, {})
    assert calls == MODELS[:2]
    assert "PARTIAL_SENTINEL" not in output.read_text()
    assert not key_quarantine.is_quarantined("litellm-gateway:" + MODELS[0])


def test_old_gateway_quarantine_does_not_poison_independent_key_slots(monkeypatch, inputs):
    key_quarantine.quarantine("litellm-gateway", "402 on another Gateway model")
    calls, _ = install_http(monkeypatch, lambda model: Response(model))
    reviewer.run_review("CV", inputs, {})
    assert calls == MODELS[:1]
    assert key_quarantine.is_quarantined("litellm-gateway")
    assert llm_client.quarantine_scope("litellm-gateway", "mistral-medium") == "litellm-gateway"
    assert llm_client.quarantine_scope("mistral", "mistral-medium-latest") == "mistral"


@pytest.mark.parametrize("all_failed", [False, True])
def test_annotation_dialogue_uses_same_key_chain(monkeypatch, inputs, all_failed):
    reviewer.REVIEWS_DIR.mkdir()
    previous = reviewer.REVIEWS_DIR / "Example_CV_review.md"
    previous.write_text("---\nsubmission_score: 50\n---\n" + GOOD)
    original = previous.read_bytes()
    monkeypatch.setattr(reviewer, "review_is_current", lambda _path: (True, previous))
    monkeypatch.setattr(reviewer, "detect_annotations", lambda _path: ["Please verify this claim"])
    monkeypatch.setattr(reviewer, "trace_finding_sources", lambda _path: [])
    calls, _ = install_http(monkeypatch, lambda model:
        Response(model, status=402 if all_failed or model == MODELS[0] else 200))
    if all_failed:
        with pytest.raises(RuntimeError, match="All providers failed"):
            reviewer.respond_to_annotations("CV", inputs, {})
        assert calls == MODELS
        assert previous.read_bytes() == original
        assert not reviewer.ARCHIVE_DIR.exists()
    else:
        reviewer.respond_to_annotations("CV", inputs, {})
        assert calls == MODELS[:2]
        assert len(list(reviewer.ARCHIVE_DIR.glob("*.md"))) == 1
