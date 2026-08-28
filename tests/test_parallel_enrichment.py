"""Enriching several jobs at once, without losing a key to its own rate limit.

The pass waits on providers: ~15s per posting, almost none of it computing. Run
one at a time, 1543 jobs is an overnight job by itself, which is how two nights
of analysis came to be killed mid-pass.

Concurrency here is not free, and the thing it can break is not the speed:

  - every call walks the fallback chain from the top, so N workers open N calls
    against the SAME first provider. Past its requests-per-second that earns a
    429, and a 429 sidelines a WORKING key for 15 minutes.
  - the quarantine file is read-modify-write. Two providers failing together
    race, and the loser's entry vanishes — the key stays in the chain and costs
    a full round of retries on every later call.
  - `last_provider` is one module global. Two threads finishing together read
    each other's, and a score is stamped with the provider that did not produce
    it — the exact confusion that field exists to prevent.
"""
import json
import threading
import inspect

import pytest

import key_quarantine
import llm_client
import run
import selection


# --- the width itself ---

def test_workers_are_configured():
    n = selection.load_config().get("analysis_workers")
    assert n, "analysis_workers must be set, or the pass runs serial"
    assert isinstance(n, int)


def test_the_width_stays_under_the_live_key_count():
    """Workers all start at chain[0]. More of them than there are keys to fall
    through to means a throttled provider has nowhere to spill."""
    n = selection.load_config()["analysis_workers"]
    keys = len(llm_client._OPENAI_COMPAT) if hasattr(llm_client, "_OPENAI_COMPAT") else 0
    assert 1 <= n <= 8, "a wide pool buys 429s, not throughput"
    if keys:
        assert n < keys


# --- what the enrichment loop must keep doing ---

def _analyze_all_source():
    src = inspect.getsource(run.main)
    start = src.index("def _analyze_all")
    return src[start:src.index("🎯 MATCHING AGAINST")]


def test_the_enrichment_runs_in_a_pool():
    assert "ThreadPoolExecutor" in _analyze_all_source()


def test_the_cheap_pass_stays_serial():
    """It touches no network, so a pool adds contention and buys nothing."""
    assert "workers = 1 if skip_llm else" in _analyze_all_source()


def test_results_are_placed_by_index_not_appended():
    """Completion order is not submission order once the calls overlap. Appending
    would shuffle the batch, and the caller matches and persists it positionally."""
    src = _analyze_all_source()
    assert "out[idx] = res" in src
    assert "out.append" not in src


def test_a_failed_job_is_still_returned():
    """A posting that fails enrichment is kept unenriched. Dropping it would make
    the chunk shorter than the batch it was cut from and lose the job silently."""
    assert "return idx, jobs[idx], (e," in _analyze_all_source()


def test_the_traceback_is_captured_on_the_raising_thread():
    """format_exc() on the main thread after the worker returned reports nothing:
    the frame is gone, and the message alone does not say which field was bad."""
    src = _analyze_all_source()
    assert "traceback.format_exc" in src
    body = src[src.index("def _run"):src.index("def _record")]
    assert "format_exc" in body


# --- provider provenance under threads ---

def test_current_provider_is_per_thread():
    llm_client.last_provider = None
    llm_client._provider_tls.name = "mistral"
    seen = {}

    def other():
        llm_client._provider_tls.name = "groq"
        seen["other"] = llm_client.current_provider()

    t = threading.Thread(target=other)
    t.start()
    t.join()

    assert seen["other"] == "groq"
    assert llm_client.current_provider() == "mistral"


def test_current_provider_falls_back_to_the_global():
    """Single-threaded callers, and tests that set the global directly, still
    read the value they set."""
    llm_client._provider_tls.name = None
    llm_client.last_provider = "ollama"
    assert llm_client.current_provider() == "ollama"


def test_the_score_records_the_provider_through_the_accessor():
    import matcher
    src = inspect.getsource(matcher)
    assert '"provider": _lc.current_provider()' in src
    assert '"provider": _lc.last_provider' not in src


# --- the quarantine file under threads ---

@pytest.fixture
def state(tmp_path, monkeypatch):
    f = tmp_path / ".key_quarantine.json"
    monkeypatch.setattr(key_quarantine, "STATE_FILE", f)
    return f


def test_concurrent_quarantines_all_survive(state):
    """Read-modify-write from several threads. Without the lock the last writer
    wins and the others' keys quietly stay in the chain."""
    names = [f"mistral-{i}" for i in range(12)]
    barrier = threading.Barrier(len(names))

    def go(n):
        barrier.wait()
        key_quarantine.quarantine(n, reason="429 rate limit")

    threads = [threading.Thread(target=go, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stored = json.loads(state.read_text(encoding="utf-8"))
    assert set(stored) == set(names)


def test_the_state_write_is_atomic(state):
    key_quarantine.quarantine("mistral", reason="429 rate limit")
    assert json.loads(state.read_text(encoding="utf-8"))
    assert not state.with_suffix(state.suffix + ".tmp").exists()


def test_a_partial_write_never_reaches_the_file(state, monkeypatch):
    """_load answers {} to unparseable JSON — which releases every sidelined key
    at once. A truncated write must not be able to happen."""
    key_quarantine.quarantine("mistral", reason="429 rate limit")
    before = state.read_text(encoding="utf-8")

    def explode(*_a, **_k):
        raise KeyboardInterrupt("killed mid-write")

    monkeypatch.setattr(key_quarantine.json, "dumps", explode)
    with pytest.raises(KeyboardInterrupt):
        key_quarantine.quarantine("groq", reason="429 rate limit")
    assert state.read_text(encoding="utf-8") == before


def test_a_rate_limit_costs_minutes_not_days():
    """The cascade this guards against: N workers hit one key, it throttles, and
    a five-day cooldown would take a live key out of the pool for the week."""
    assert key_quarantine.cooldown_for("429 rate limit") < 1
    assert key_quarantine.cooldown_for("401 unauthorized") >= 1


# --- the matching half ---

def test_matching_runs_in_a_pool_too():
    """Measured on the backlog, matching a chunk took LONGER than enriching it.
    Leaving it serial caps the chunk at its slower half and wastes the pool."""
    src = inspect.getsource(run.match_all)
    assert "ThreadPoolExecutor" in src


def test_matching_uses_the_same_configured_width():
    """One pool size for both halves: they draw on the same keys, and two
    independent widths would together exceed what the chain can absorb."""
    assert 'get("analysis_workers")' in inspect.getsource(run.match_all)


def test_the_failure_count_is_guarded():
    """`failures += 1` from several threads loses increments, and the count is
    what tells the reader how much of the batch went unscored."""
    src = inspect.getsource(run.match_all)
    body = src[src.index("def _score"):src.index("if workers > 1")]
    assert "with lock:" in body


def test_a_job_gets_its_score_only_once_the_call_returned():
    """Assigning into job['match'] before analyze_match returns would leave a
    half-built score behind when the provider chain dies mid-batch."""
    src = inspect.getsource(run.match_all)
    body = src[src.index("def _score"):src.index("if workers > 1")]
    assert body.index("m = analyze_match") < body.index('job["match"] = m')


def test_the_casing_registry_is_locked():
    """canonical_company is read-modify-write over a shared dict AND a single
    shared temp path. Sorting the dict while another thread inserts raises, and
    two writers on one temp file can publish a truncated registry."""
    import matcher
    src = inspect.getsource(matcher.canonical_company)
    assert "with _casing_lock:" in src


def test_concurrent_company_registration_keeps_every_name(tmp_path, monkeypatch):
    import matcher
    monkeypatch.setattr(matcher, "_COMPANY_CASING_PATH", tmp_path / "_company_casing.json")
    monkeypatch.setattr(matcher, "_company_casing", {})
    names = [f"Company {i}" for i in range(24)]
    barrier = threading.Barrier(len(names))

    def go(n):
        barrier.wait()
        matcher.canonical_company(n)

    threads = [threading.Thread(target=go, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stored = json.loads((tmp_path / "_company_casing.json").read_text(encoding="utf-8"))
    assert set(stored.values()) == set(names)


# --- spreading load over interchangeable keys ---

def test_the_leading_family_rotates():
    """The chain is walked from the top by every call, so without this one key
    answers everything and the rest are standby. Measured 2026-08-21: of 4138
    calls across 12 groq keys, the only provider ever rate-limited was chain[0]."""
    chain = ["groq", "groq-back", "groq-tertiary", "mistral"]
    seen = {llm_client._rotate_interchangeable_head(chain)[0] for _ in range(30)}
    assert seen == {"groq", "groq-back", "groq-tertiary"}


def test_rotation_keeps_every_provider():
    chain = ["groq", "groq-back", "groq-tertiary", "mistral", "ollama"]
    for _ in range(12):
        out = llm_client._rotate_interchangeable_head(chain)
        assert sorted(out) == sorted(chain)
        assert len(out) == len(chain)


def test_providers_after_the_head_keep_their_order():
    """Position past the head encodes preference — a different model, a slower
    one, a paid one. Only the interchangeable keys may move."""
    chain = ["groq", "groq-back", "mistral", "mistral-backup", "ollama"]
    for _ in range(12):
        assert llm_client._rotate_interchangeable_head(chain)[2:] == \
            ["mistral", "mistral-backup", "ollama"]


def test_a_single_leading_provider_is_left_alone():
    for chain in (["mistral", "groq", "groq-back"], ["groq"], []):
        assert llm_client._rotate_interchangeable_head(chain) == chain


def test_the_family_is_the_name_before_the_first_dash():
    assert llm_client._provider_family("groq-duodenary") == "groq"
    assert llm_client._provider_family("mistral") == "mistral"
    assert llm_client._provider_family("litellm-gateway") == "litellm"


def test_rotation_happens_after_quarantine_filtering():
    """A sidelined key must not be rotated back into the lead."""
    src = inspect.getsource(llm_client.call_llm)
    assert src.index("_quarantine_filter_chain") < src.index("_rotate_interchangeable_head")
