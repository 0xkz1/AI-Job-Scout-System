"""A big prompt needs a bigger read budget than a small one.

The 45s read timeout was introduced to stop a dead provider costing 183s, and
it does that well for ordinary calls. On the review path it did the opposite:
measured 2026-08-17 against the real 98,577-char review prompt,
nemotron-super-49b answers in 128.3s, so every one of the seven NVIDIA keys was
abandoned at 45s on every review — 315s per review spent on calls that could
not succeed, against a provider that was healthy (HTTP 200 on /v1/models).
"""
import llm_client
import pytest


def _msgs(n_chars):
    return [{"role": "user", "content": "x" * n_chars}]


def test_an_ordinary_call_keeps_the_short_budget():
    """The common sites (analyzer ~6-8k, CL bridge 12.6k, CV 15.1k) must not
    gain any extra patience — that budget is what makes a dead provider cheap."""
    for size in (500, 6_000, 15_065, 20_000):
        assert llm_client._http_timeout_for(_msgs(size)) == llm_client._HTTP_TIMEOUT, size


def test_a_review_sized_prompt_gets_more_than_the_measured_latency():
    """98,577 chars answered in 128.3s, so the budget has to exceed that."""
    _connect, read = llm_client._http_timeout_for(_msgs(98_577))
    assert read > 128.3, f"read budget {read}s would still abandon a real review"
    assert read <= llm_client._TIMEOUT_READ_CEILING


def test_the_read_budget_is_capped():
    _connect, read = llm_client._http_timeout_for(_msgs(5_000_000))
    assert read == llm_client._TIMEOUT_READ_CEILING


def test_the_connect_budget_never_grows():
    """A longer body does not make a TCP handshake slower, and a provider that
    will not accept a connection must stay cheap to skip."""
    want = llm_client._HTTP_TIMEOUT[0]
    for size in (500, 98_577, 5_000_000):
        assert llm_client._http_timeout_for(_msgs(size))[0] == want


def test_the_system_prompt_counts_toward_the_size():
    small = llm_client._http_timeout_for(_msgs(19_000))
    with_system = llm_client._http_timeout_for(_msgs(19_000), "y" * 40_000)
    assert small == llm_client._HTTP_TIMEOUT
    assert with_system[1] > small[1]


def test_the_budget_grows_with_the_prompt():
    reads = [llm_client._http_timeout_for(_msgs(n))[1]
             for n in (20_000, 40_000, 60_000, 98_577)]
    assert reads == sorted(reads)
    assert len(set(reads)) == len(reads), "each step should widen the budget"


def test_every_hosted_provider_uses_the_scaled_timeout():
    """A provider left on the bare constant would keep timing out on reviews
    while the others no longer do — the failure this whole change removes.

    Counts the call to _http_timeout_for rather than the whole `timeout=...`
    expression: litellm-gateway wraps it in a max() against a floor, because
    one request there fans out across the gateway's own retries and model
    fallbacks and so needs more than any single model's budget. That is still
    a scaled timeout — it is the bare constant this test exists to catch.
    """
    import inspect
    src = inspect.getsource(llm_client)
    assert "timeout=_HTTP_TIMEOUT" not in src, \
        "a requests call still uses the unscaled constant"
    assert src.count("_http_timeout_for(full_messages)") >= 5


def test_the_gateway_outwaits_a_single_provider():
    """The gateway is a chain behind one request, so a budget sized to one
    model's response cut it off mid-chain — measured 2026-08-18, sixteen of
    ninety-two CV calls timed out at 45s against a gateway that logged 200 OK
    for them afterwards, which is a paid-for answer thrown away.
    """
    ordinary = llm_client._http_timeout_for(_msgs(14_947))[1]
    assert llm_client._GATEWAY_READ_TIMEOUT > ordinary, \
        "the gateway floor must exceed the ordinary per-provider budget"
