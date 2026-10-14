"""A strong review is accepted only after the stream completes."""

import json

import pytest
import requests

import llm_client


def chunk(text="", finish=None, **extra):
    return b"data: " + json.dumps({"choices": [{"index": 0,
        "delta": {"content": text, **extra}, "finish_reason": finish}]}).encode()


class Response:
    headers = {"x-litellm-model-group": "review-strong-glm53",
               "x-litellm-model-name": "openai/z-ai/glm-5.3"}

    def __init__(self, lines):
        self.lines = lines
        self.closed = False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        for line in self.lines:
            if isinstance(line, Exception):
                raise line
            yield line

    def close(self):
        self.closed = True


def call(monkeypatch, lines):
    monkeypatch.setenv("LITELLM_GATEWAY_API_KEY", "test-placeholder")
    monkeypatch.setenv("LITELLM_GATEWAY_URL", "http://localhost:4001")
    response = Response(lines)
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(llm_client.requests, "post", post)
    return response, calls


def run():
    return llm_client._call_litellm_gateway(
        [{"role": "user", "content": "Review this CV."}], "", 0.2, 4000, 2,
        model="review-strong-glm53")


def test_completed_review_buffers_text_without_reasoning(monkeypatch):
    response, calls = call(monkeypatch, [b": keepalive", b"",
        chunk(reasoning_content="private reasoning"), chunk("first "),
        chunk("second", "stop"), b"data: [DONE]"])
    assert run() == "first second"
    assert response.closed
    assert len(calls) == 1
    url, options = calls[0]
    assert url == "http://127.0.0.1:4001/v1/chat/completions"
    assert options["stream"] is True
    assert options["json"]["stream"] is True
    assert options["json"]["num_retries"] == 0
    assert llm_client.current_served_model() == "review-strong-glm53:openai/z-ai/glm-5.3"


@pytest.mark.parametrize("lines", [
    [chunk("partial")],
    [chunk("partial", "length"), b"data: [DONE]"],
    [chunk("partial", "stop")],
    [chunk("", "stop"), b"data: [DONE]"],
    [b'data: {"error": {"message": "upstream failed"}}'],
    [b"data: invalid-json"],
    [chunk("partial"), requests.ConnectionError("connection reset")],
])
def test_incomplete_or_failed_stream_never_returns_partial_text(monkeypatch, lines):
    response, calls = call(monkeypatch, lines)
    with pytest.raises(RuntimeError):
        run()
    assert len(calls) == 1
    assert response.closed


def test_total_stream_time_is_bounded(monkeypatch):
    response, calls = call(monkeypatch, [chunk("partial"), chunk("late", "stop"),
                                      b"data: [DONE]"])
    times = iter([0, 1, llm_client._GATEWAY_READ_TIMEOUT + 1])
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: next(times))
    with pytest.raises(RuntimeError, match="timed out"):
        run()
    assert response.closed
    assert len(calls) == 1
