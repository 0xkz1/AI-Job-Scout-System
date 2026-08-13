"""A provider that is not answering must not cost three minutes to skip.

The fallback chain is 44 providers deep and works: on 2026-08-13 six Mistral
keys hit 429, were quarantined, and the chain moved to NVIDIA exactly as
designed. The review run still stalled for 19 minutes after writing a review
every 75 seconds, and the quarantine notices in the log made it look like a key
problem. It was not.

Every provider call used `timeout=60` — applied to BOTH the connect and read
phases — inside `for attempt in range(retries + 1)` with exponential backoff. So:

    a provider returning 429   0 + 1 + 0 + 2 + 0    =   3s   (cheap, correct)
    a provider not answering  60 + 1 + 60 + 2 + 60  = 183s   (three minutes)

Six unresponsive providers in a row is 18 minutes of silence. Retrying a host
that did not complete a TCP handshake twice more spends two minutes confirming
what the first attempt established, and the next provider in a 44-deep chain is
a far better use of that time. A 429 or 5xx is the opposite case — the provider
is alive and busy, and a moment later it may answer.
"""
import time

import llm_client
import pytest
import requests


@pytest.fixture
def mistral_key(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "dummy")


def _call(**_kw):
    return llm_client._call_mistral(
        [{"role": "user", "content": "x"}], "", 0.1, 512, 2)


def test_connect_and_read_budgets_are_separate():
    """One number for both phases means a host that never completes a handshake
    is given the same budget as one streaming a long answer."""
    assert isinstance(llm_client._HTTP_TIMEOUT, tuple), (
        "timeout must be (connect, read); a scalar applies the read budget to "
        "the connect phase"
    )
    connect, read = llm_client._HTTP_TIMEOUT
    assert connect <= 10, "a hosted API that has not accepted a connection is not coming"
    assert read >= 30, "a real review answer needs room to arrive"


@pytest.mark.parametrize("error,expected,why", [
    (requests.exceptions.ConnectTimeout("timed out"), False, "nothing is coming"),
    (requests.exceptions.ReadTimeout("Read timed out"), False, "nothing is coming"),
    (requests.exceptions.ConnectionError("Connection refused"), False, "nothing is coming"),
    (RuntimeError("429 Client Error: Too Many Requests"), True, "alive, just busy"),
    (RuntimeError("503 Server Error: Service Unavailable"), True, "alive, transient"),
    (RuntimeError("returned empty content"), True, "answered, badly"),
])
def test_only_a_live_provider_earns_a_second_attempt(error, expected, why):
    assert llm_client._retry_same_provider(error) is expected, why


def test_an_unresponsive_provider_is_abandoned_after_one_attempt(mistral_key, monkeypatch):
    attempts = []

    def never_answers(*_a, **_k):
        attempts.append(1)
        raise requests.exceptions.ConnectTimeout("Connection to api.mistral.ai timed out")

    monkeypatch.setattr(llm_client.requests, "post", never_answers)
    start = time.time()
    with pytest.raises(RuntimeError):
        _call()
    assert len(attempts) == 1, (
        f"tried {len(attempts)} times against a host that is not answering; each "
        f"extra attempt is a full timeout the chain waits through"
    )
    assert time.time() - start < 1.0, "no backoff should be spent on a dead host"


def test_a_rate_limited_provider_still_gets_its_retries(mistral_key, monkeypatch):
    """The opposite case must not regress: a busy provider is worth waiting for,
    and burning a key over one 429 wastes a limited monthly allowance."""
    attempts = []

    class RateLimited:
        status_code = 429

        def raise_for_status(self):
            raise requests.HTTPError("429 Client Error: Too Many Requests")

        def json(self):
            return {}

    def busy(*_a, **_k):
        attempts.append(1)
        return RateLimited()

    monkeypatch.setattr(llm_client.requests, "post", busy)
    with pytest.raises(RuntimeError):
        _call()
    assert len(attempts) == 3, "a 429 should still be retried on the same provider"


def test_the_error_reports_attempts_actually_made(mistral_key, monkeypatch):
    """It used to interpolate retries+1 regardless, so a single-attempt
    abandonment still claimed "after 3 attempts" — which is what made the stall
    read as a key problem rather than a timeout one."""
    monkeypatch.setattr(llm_client.requests, "post", lambda *_a, **_k: (_ for _ in ()).throw(
        requests.exceptions.ConnectTimeout("timed out")))
    with pytest.raises(RuntimeError, match="after 1 attempts"):
        _call()


def test_ollama_keeps_a_long_read_budget():
    """Local, and may be loading a model off disk. Only the connect phase is
    short, because localhost either accepts at once or is not running."""
    assert llm_client._OLLAMA_CONNECT_TIMEOUT <= 10
    source = __import__("inspect").getsource(llm_client._call_ollama)
    assert "_OLLAMA_CONNECT_TIMEOUT, timeout" in source, (
        "ollama should pair a short connect with its own long read budget"
    )
