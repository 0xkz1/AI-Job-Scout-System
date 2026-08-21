"""Unified LLM client — supports Ollama (local), Mistral, and OpenRouter (cloud).

Provider selection:
  env ANALYSIS_PROVIDER   = "mistral" | "stepfun" | "openrouter" | "ollama" (default)
  env FALLBACK_PROVIDERS  = comma-separated chain to try in order when the
                            primary hits rate limit / 5xx / missing API key,
                            e.g. "stepfun,ollama"
  env FALLBACK_PROVIDER   = legacy single-provider form (used when
                            FALLBACK_PROVIDERS is unset)
  env MISTRAL_MODEL       = model for the mistral provider (else CLOUD_MODEL, else mistral-tiny)
  env STEPFUN_MODEL       = model for the stepfun provider (else CLOUD_MODEL, else step-3.5-flash)
  env STEPFUN_API_KEY     = StepFun direct API key (native endpoint, not OpenRouter)
  env STEPFUN_REGION      = "international" (default, api.stepfun.ai) | "china" (api.stepfun.com)
  env OPENROUTER_MODEL    = model for the openrouter provider (else CLOUD_MODEL)
  env OLLAMA_MODEL        = model for the ollama provider
  env CLOUD_MODEL         = shared model override (legacy)
  env CLOUD_API_KEY       = optional key override (else MISTRAL_API_KEY / OPENROUTER_API_KEY)

Chained fallback:
  call_llm() tries the primary provider; on a transient error (429 rate limit,
  5xx server error, timeout) or a missing API key it moves down the fallback
  chain. Set FALLBACK_PROVIDERS=stepfun,ollama to spill over to a cheap cloud
  model first and local Ollama last.

Usage:
  from llm_client import call_llm

  text = call_llm(
      messages=[{"role": "user", "content": "Hello"}],
      system_prompt="You are a helpful assistant.",
      temperature=0.1,
      max_tokens=512,
      provider="mistral",  # optional, overrides env
  )
"""

import itertools
import json
import os
import sys
import threading
import time
import requests
from typing import Optional

from dotenv import load_dotenv

# Load the project .env so MISTRAL_API_KEY / ANALYSIS_PROVIDER etc. work
# without manually sourcing the file. Existing shell env vars take precedence.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


call_llm_counter = 0  # module-level call counter for structured logging

# Provider that answered the most recent successful call_llm. Callers that store a
# model's judgement alongside it read this to record WHICH model judged.
#
# Needed because the chain silently changes what produced a score. On 2026-07-26
# all ten Mistral keys hit their monthly limit mid-run, so context scores began
# coming from ollama and TF-IDF instead — recorded identically, since
# context_source only distinguishes "llm" from "tfidf". With context carrying 0.64
# of the composite weight, a DB can end up holding scores from three different
# models with no way to tell them apart, and `--reanalyze --llm-context` skips
# anything already tagged "llm", so the weaker ones are never refreshed.
#
# Module-level rather than a changed return type: call_llm returns a plain string
# to a dozen call sites, and widening that signature to thread one optional field
# through all of them would be a worse trade.
last_provider: str | None = None

# The enrichment pass runs several jobs at once, and a bare module global cannot
# say which provider answered *this* call: two threads finishing a few
# milliseconds apart would each read the other's provider and stamp the wrong
# name onto a score. The per-thread value is the truthful one; the global stays
# for single-threaded callers and for tests that set it directly.
_provider_tls = threading.local()


def current_provider() -> str | None:
    """The provider that answered the most recent call *on this thread*."""
    return getattr(_provider_tls, "name", None) or last_provider

# provider name -> env var holding its key. One Mistral account per key, each with
# its own monthly allowance, so depth here is throughput: a single bulk day (182
# reviews plus analysis) drained three keys, nvidia and stepfun.
#
# A table rather than an if/elif per key: adding one used to mean editing this
# dispatch AND reviewer's chain list, and the review chain silently kept working
# while the analysis chain in .env lagged a key behind. Keep the ORDER — reviewer
# and key_quarantine both treat it as priority, best first.
MISTRAL_PROVIDERS = {
    "mistral": "MISTRAL_API_KEY",
    "mistral-backup": "MISTRAL_API_KEY_BACKUP",
    "mistral-tertiary": "MISTRAL_API_KEY_TERTIARY",
    "mistral-quaternary": "MISTRAL_API_KEY_QUATERNARY",
    "mistral-quinary": "MISTRAL_API_KEY_QUINARY",
    "mistral-senary": "MISTRAL_API_KEY_SENARY",
    "mistral-septenary": "MISTRAL_API_KEY_SEPTENARY",
    "mistral-octonary": "MISTRAL_API_KEY_OCTONARY",
    "mistral-nonary": "MISTRAL_API_KEY_NONARY",
    "mistral-denary": "MISTRAL_API_KEY_DENARY",
    # Added 2026-08-17, after 6 of the 10 above were sitting on 402. Verified
    # per-key that day that the allowances really are independent — 4 alive and
    # 6 spent at the same moment — so these add throughput rather than sharing
    # a pool (which is what makes the Z.AI keys worthless in bulk). They land
    # in reviewer's chain automatically: it builds from this table, which is
    # why the table exists.
    "mistral-undenary": "MISTRAL_API_KEY_UNDENARY",
    "mistral-duodenary": "MISTRAL_API_KEY_DUODENARY",
    "mistral-tredenary": "MISTRAL_API_KEY_TREDENARY",
    "mistral-quattuordenary": "MISTRAL_API_KEY_QUATTUORDENARY",
    "mistral-quindenary": "MISTRAL_API_KEY_QUINDENARY",
}

# Multi-key pools for OpenAI-compatible providers. Same pattern as MISTRAL_PROVIDERS:
# one account per key, each with its own rate limit / monthly quota, so depth =
# throughput. The actual base-URL + key-env lookup lives in _OPENAI_COMPAT below;
# these dicts are kept for code that enumerates available keys (e.g. tests that
# count providers, or future dynamic chain construction). Provider names here must
# match the keys in _OPENAI_COMPAT.
#
# Key source for nvidia keys:
#   nvidia       — OpenCode auth.json nvidia.key (nvapi-jps...)
#   nvidia-back  — Hermes profiles/researcher .env (nvapi-UQ1...)
# Key source for groq keys:
#   groq         — original key, shared with .env GROQ_API_KEY (gsk_Z6zh...)
#   groq-back    — second key provided by user 2026-08-09 (gsk_REJM...)

NVIDIA_PROVIDERS = {
    "nvidia":            "NVIDIA_API_KEY",
    "nvidia-back":       "NVIDIA_BACKUP_API_KEY",
    "nvidia-tertiary":   "NVIDIA_TERTIARY_API_KEY",
    "nvidia-quaternary": "NVIDIA_QUATERNARY_API_KEY",
    "nvidia-quinary":    "NVIDIA_QUINARY_API_KEY",
    "nvidia-senary":     "NVIDIA_SENARY_API_KEY",
    "nvidia-septenary":  "NVIDIA_SEPTENARY_API_KEY",
}

GROQ_PROVIDERS = {
    "groq":            "GROQ_API_KEY",
    "groq-back":       "GROQ_BACKUP_API_KEY",
    "groq-tertiary":   "GROQ_TERTIARY_API_KEY",
    "groq-quaternary": "GROQ_QUATERNARY_API_KEY",
    "groq-quinary":    "GROQ_QUINARY_API_KEY",
    "groq-senary":     "GROQ_SENARY_API_KEY",
    "groq-septenary":  "GROQ_SEPTENARY_API_KEY",
    "groq-octonary":   "GROQ_OCTONARY_API_KEY",
    "groq-nonary":     "GROQ_NONARY_API_KEY",
    "groq-denary":     "GROQ_DENARY_API_KEY",
    "groq-undenary":   "GROQ_UNDENARY_API_KEY",
    "groq-duodenary":  "GROQ_DUODECENARY_API_KEY",
}

# Z.AI (GLM-5.2) — 11 keys from Hermes credential pool.
#   zai            = ZAI_API_KEY (env-sourced, label=GLM_API_KEY)
#   zai-back       = api-key-cao (exhausted in Hermes, quarantine auto-handles)
#   zai-tertiary   = api-key-bak (exhausted in Hermes)
#   zai-quaternary = api-key-comp (ok)
#   zai-quinary    = api-key-gei (ok) ... zai-undenary = api-key-terra (ok)
ZAI_PROVIDERS = {
    "zai":            "ZAI_API_KEY",
    "zai-back":       "ZAI_BACKUP_API_KEY",
    "zai-tertiary":   "ZAI_TERTIARY_API_KEY",
    "zai-quaternary": "ZAI_QUATERNARY_API_KEY",
    "zai-quinary":    "ZAI_QUINARY_API_KEY",
    "zai-senary":     "ZAI_SENARY_API_KEY",
    "zai-septenary":  "ZAI_SEPTENARY_API_KEY",
    "zai-octonary":   "ZAI_OCTONARY_API_KEY",
    "zai-nonary":     "ZAI_NONARY_API_KEY",
    "zai-denary":     "ZAI_DENARY_API_KEY",
    "zai-undenary":   "ZAI_UNDENARY_API_KEY",
}


# Interchangeable keys are a QUEUE, not a pool: every call walks the chain from
# the top, so the first provider answers nearly everything and the rest sit idle
# as standby. Measured on the 2026-08-21 backlog with 8 workers and 12 groq keys:
# 4138 calls, and the ONLY provider ever rate-limited was chain[0] — twice. The
# other eleven keys absorbed 7 failures between them because they were barely
# reached. Adding more keys to a queue like that buys nothing; the load has to
# move sideways instead.
#
# So the leading run of same-family providers is rotated per call. They are the
# same account family and the same model, so order among them carries no quality
# meaning — unlike the chain as a whole, where position encodes preference and
# must not be shuffled.
_rr_counter = itertools.count()


def _provider_family(provider: str) -> str:
    """groq, groq-back, groq-tertiary -> "groq". Keys of one account family."""
    return provider.split("-", 1)[0]


def _rotate_interchangeable_head(chain: list[str]) -> list[str]:
    """Start this call at a different key of the leading family."""
    if len(chain) < 2:
        return chain
    family = _provider_family(chain[0])
    head = 1
    while head < len(chain) and _provider_family(chain[head]) == family:
        head += 1
    if head < 2:
        return chain
    # next() on an itertools.count is atomic, so no lock is needed for the
    # several worker threads sharing it.
    offset = next(_rr_counter) % head
    return chain[offset:head] + chain[:offset] + chain[head:]


def _quarantine_filter_chain(chain: list[str]) -> list[str]:
    """Skip providers currently sidelined by key_quarantine (import kept lazy so
    llm_client still works if the module is absent)."""
    try:
        from key_quarantine import filter_chain
        return filter_chain(chain)
    except Exception:
        return chain


# A per-provider cap on REQUEST BODY size, which is not the same thing as a
# context window. Groq's models all advertise a 131k-token context, and all of
# them still answer 413 Payload Too Large well below it — the limit is on the
# account's request size, so no model swap escapes it. Bisected 2026-08-17:
# 21,812 prompt chars accepted, 22,281 refused, identically on gpt-oss-120b,
# gpt-oss-20b, qwen3.6-27b and compound-mini. 21,000 leaves margin for the JSON
# envelope the chars are wrapped in.
#
# Checked BEFORE the call rather than handled after, because 413 is not a
# transient error: retrying it, or walking 12 groq keys that will each refuse
# the same body, is pure latency. Skipping is also what lets groq sit at the
# FRONT of the chain — it is the fastest provider here by an order of magnitude
# (0.4-0.6s vs mistral's several seconds), and the two call sites it cannot
# serve (reviewer's ~98k prompt, matcher's ~63k role_fit prompt) now route past
# it automatically instead of needing their own hand-maintained chains.
_PROVIDER_MAX_PROMPT_CHARS = {p: 21000 for p in GROQ_PROVIDERS}


def _size_filter_chain(chain: list[str], messages: list[dict],
                       system_prompt: str) -> list[str]:
    """Drop providers that cannot accept a prompt this large, preserving order.

    Never returns empty: if every provider is too small, the original chain is
    tried anyway, so a wrong cap degrades to today's behaviour (one 413) rather
    than to no call at all.
    """
    size = sum(len(m.get("content", "") or "") for m in messages) + len(system_prompt or "")
    kept = [p for p in chain if size <= _PROVIDER_MAX_PROMPT_CHARS.get(p, float("inf"))]
    return kept or chain


def _maybe_quarantine(provider: str, err: str) -> None:
    """Sideline a provider whose key looks exhausted or rejected."""
    try:
        from key_quarantine import is_quota_or_auth_error, quarantine
        if is_quota_or_auth_error(err):
            quarantine(provider, err[:160])
    except Exception:
        pass


def _is_transient_error(e: Exception) -> bool:
    """Check if a RuntimeError is a transient (retryable) failure."""
    err_str = str(e).lower()
    # Rate limits, server errors, network issues (excluding 401/403 which are fatal auth failures)
    markers = [
        "429", "rate limit", "too many requests", "quota",
        "402", "502", "503", "504", "500", "payment required", "bad gateway", "service unavailable",
        "timeout", "timed out", "connection", "eof", "refused", "reset",
        # A reasoning model that spent its whole max_tokens budget on hidden
        # reasoning and returned HTTP 200 with no content. The raise site says
        # it exists so "the caller's provider chain [can] fall through to the
        # next model" — but without this marker the chain treated it as fatal
        # and stopped at the provider that produced it. groq/gpt-oss-120b does
        # this deterministically on short-output calls, and groq leads the
        # chain, so every cover-letter bridge died on the FIRST provider while
        # eight Mistral keys sat live and unreached. It is transient in the only
        # sense that matters here: another model answers it.
        "returned empty content",
    ]
    return any(m in err_str for m in markers)



def _calling_stage() -> str:
    """Which module asked for this call, for the stats file.

    Walks out of llm_client rather than using inspect.stack(), which builds a
    full FrameInfo for every frame and is far too slow to sit in front of every
    LLM call in the pipeline.
    """
    try:
        f = sys._getframe(1)
        while f is not None:
            name = f.f_globals.get("__name__", "")
            if name and name != __name__:
                return name.rsplit(".", 1)[-1]
            f = f.f_back
    except Exception:
        pass
    return "unknown"


def record_llm_call(stage: str, provider: str, elapsed: float, prompt_chars: int,
                    max_tokens: int, outcome: str) -> None:
    """Append one line to the file named by JIS_LLM_STATS_FILE, if set.

    Off unless the environment names a file, so an interactive run costs
    nothing and only the nightly collects. One line per call rather than a
    running aggregate: the questions worth asking later — which stage is slow,
    which provider answers it, how often the chain falls through — are all
    group-bys over the raw rows, and none of them can be recovered from a
    counter that has already summed them.

    Never raises. A statistics file that can break a scrape is worse than no
    statistics file.
    """
    path = os.environ.get("JIS_LLM_STATS_FILE")
    if not path:
        return
    try:
        with open(path, "a") as fh:
            fh.write(f"{stage}\t{provider}\t{elapsed:.2f}\t{prompt_chars}"
                     f"\t{max_tokens}\t{outcome}\n")
    except Exception:
        pass


def call_llm(
    messages: list[dict],
    system_prompt: str = "",
    temperature: float = 0.1,
    max_tokens: int = 512,
    provider: Optional[str] = None,
    retries: int = 2,
    model: Optional[str] = None,
    use_fallbacks: bool = True,
) -> str:
    """Call LLM with automatic primary → fallback provider chain.

    Tries primary provider first; if it fails with a transient error (rate
    limit, server error, timeout) and FALLBACK_PROVIDER is set, retries on the
    fallback provider automatically.

    Args:
        messages: List of {"role": "user"/"assistant", "content": str}.
        system_prompt: System prompt (prepended if non-empty).
        temperature: Sampling temperature.
        max_tokens: Max output tokens.
        provider: Override env ANALYSIS_PROVIDER ("ollama", "mistral", "openrouter").
        retries: Max retries on transient failure PER PROVIDER.
        model: Override the provider's env-configured model for THIS call.
        use_fallbacks: When False, only the primary provider is tried and the
            global FALLBACK_PROVIDERS chain is ignored. Callers that manage their
            own (provider, model) fallback list use this — a single `model` name
            is provider-specific, so it cannot be reused across the global chain.

    Returns:
        Response text string.
    """
    global call_llm_counter
    call_llm_counter += 1
    cid = call_llm_counter  # short alias for log prefix

    primary = provider or os.environ.get("ANALYSIS_PROVIDER", "ollama")
    fallbacks_env = os.environ.get("FALLBACK_PROVIDERS") or os.environ.get("FALLBACK_PROVIDER", "")
    chain = [primary] + ([
        p.strip() for p in fallbacks_env.split(",")
        if p.strip() and p.strip() != primary
    ] if use_fallbacks else [])
    # A provider whose key is spent stays in the chain but is skipped until its
    # cooldown expires — otherwise every call burns the full retry budget on a
    # key that cannot answer, and deleting it would lose the key once its quota
    # resets. Order is untouched, so it returns to its original position.
    chain = _quarantine_filter_chain(chain)
    # Spread the load over the interchangeable keys at the head before anything
    # else looks at the chain, so the pressure does not all land on one account.
    chain = _rotate_interchangeable_head(chain)
    # Then drop whoever cannot physically accept a body this big, so an
    # oversized prompt never spends a 413 (see _PROVIDER_MAX_PROMPT_CHARS).
    chain = _size_filter_chain(chain, messages, system_prompt)

    errors: list[str] = []
    stage = _calling_stage()
    prompt_chars = sum(len(str(m.get("content") or "")) for m in messages) + len(system_prompt)
    for i, prov in enumerate(chain):
        is_last = i == len(chain) - 1
        started = time.time()
        try:
            out = _call_provider(prov, messages, system_prompt, temperature, max_tokens,
                                 retries, model)
            global last_provider
            last_provider = prov
            _provider_tls.name = prov
            record_llm_call(stage, prov, time.time() - started, prompt_chars,
                            max_tokens, "ok")
            return out
        except ValueError as e:
            # Missing API key — skip to the next provider in the chain
            record_llm_call(stage, prov, time.time() - started, prompt_chars,
                            max_tokens, "no-key")
            if is_last:
                raise RuntimeError("; ".join(errors + [f"{prov}: {e}"]))
            errors.append(f"{prov}: {e}")
            print(f"[llm_client #{cid}] {prov} unavailable ({e}), trying next fallback")
        except RuntimeError as e:
            # Record an exhausted or rate-limited key even when it is the last
            # candidate in this call.  The old ordering returned/raised first
            # for the final provider, so a one-provider probe (or the tail of
            # the fallback chain) could repeatedly spend its retry budget on
            # the same bad key without ever placing it in quarantine.
            _maybe_quarantine(prov, str(e))
            record_llm_call(stage, prov, time.time() - started, prompt_chars, max_tokens,
                            "transient" if _is_transient_error(e) else "error")
            if not _is_transient_error(e) or is_last:
                if errors:
                    raise RuntimeError("; ".join(errors + [f"{prov}: {e}"]))
                raise  # non-transient (or nothing left) → propagate
            errors.append(f"{prov}: {e}")
            print(f"[llm_client #{cid}] {prov} transient failure, trying next fallback: {e}")


# (connect, read). A hosted chat API that has not accepted a TCP connection in 5
# seconds is not going to answer this call. The single 60 these replaced was
# applied to both phases.
#
# 45s is the read budget for an ORDINARY call and is deliberately short: the
# point of splitting these was to stop a dead provider costing 183s. It is the
# wrong budget for a big prompt, though, and that cost more than it saved.
# Measured 2026-08-17 on the real 98,577-char review prompt:
# nemotron-super-49b answers it in 128.3s, so all seven NVIDIA keys were being
# abandoned at 45s on every review — 315s per review spent on calls that could
# not have succeeded, while the provider itself was healthy (HTTP 200 on
# /v1/models, valid keys). Mistral answers the same prompt in 25.1s, so the
# review path fell to a chain of guaranteed timeouts whenever Mistral's keys
# were spent, which is 6 of 10 right now.
_HTTP_TIMEOUT = (5, 45)

# Above this the read budget starts growing, because the time a model needs
# scales with what it was given. 20k chars is just above the largest ORDINARY
# call site (cv_generator's 15,065; the cover-letter bridge's 12,644), so the
# common path keeps exactly the 45s it has now.
_TIMEOUT_GROWTH_FROM_CHARS = 20_000
# One extra second per 400 chars over that. On the 98,577-char review prompt
# this gives 241s, roughly double the 128.3s measured — headroom for a slower
# key without ever letting a hung connection sit for the old 183s-style cost.
_TIMEOUT_CHARS_PER_SECOND = 400
_TIMEOUT_READ_CEILING = 300

# The gateway is a chain, not a provider, so the budget that fits one model's
# response time cuts it off mid-chain. A single call there can walk several
# deployments (its router_settings.num_retries is 2) and then several models
# (its fallbacks run mistral-medium → nvidia-nim → groq-fast → zai-glm →
# ollama-gemma) before anything answers.
#
# Measured 2026-08-18: an ordinary 14,947-char prompt comes back in 1.28s when
# the first deployment takes it. But sixteen of the ninety-two CVs generated
# that morning hit the 45s ceiling instead — and the gateway logged 200 OK for
# them afterwards. So the timeout was not saving anything: JIS was walking away
# from answers it had already paid for, then spending a second key on the same
# work. A hung gateway now costs one 300s wait instead of one 45s wait, and
# _retry_same_provider already refuses to try a timed-out provider twice, so
# that cost is paid once per call rather than three times.
_GATEWAY_READ_TIMEOUT = int(os.environ.get("LITELLM_GATEWAY_READ_TIMEOUT", "300"))


def _http_timeout_for(messages: list[dict], system_prompt: str = "") -> tuple[int, int]:
    """(connect, read) sized to this prompt — see _HTTP_TIMEOUT.

    Connect stays fixed: accepting a TCP connection does not get harder with a
    longer body. Only the read budget grows.
    """
    connect, read = _HTTP_TIMEOUT
    size = sum(len(m.get("content", "") or "") for m in messages) + len(system_prompt or "")
    if size > _TIMEOUT_GROWTH_FROM_CHARS:
        read = min(_TIMEOUT_READ_CEILING,
                   read + (size - _TIMEOUT_GROWTH_FROM_CHARS) // _TIMEOUT_CHARS_PER_SECOND)
    return (connect, read)

# Ollama is local and can be loading a model off disk, so it keeps a long read
# budget; only the connect phase is short, because localhost either accepts
# immediately or is not running.
_OLLAMA_CONNECT_TIMEOUT = 5


def _retry_same_provider(exc: Exception) -> bool:
    """Whether a second attempt at the SAME provider is worth the wait.

    A 429 or a 5xx says the provider is alive and busy; a moment later it may
    answer, and the fallback chain is long enough that burning a key over one
    rate limit is wasteful. A timeout or a refused connection says nothing is
    coming, and retrying it twice more costs 2 minutes to learn what the first
    attempt already established.

    That distinction is what made a stalled review run look like a quarantine
    problem. Measured on 2026-08-13: Mistral's 429s cost ~3s each and fell
    through correctly, while every unresponsive provider cost 60+1+60+2+60 =
    183s before the chain moved on. Six of those in a row is 18 minutes of a run
    that had otherwise been writing a review every 75 seconds.
    """
    text = str(exc).lower()
    dead = ("timeout", "timed out", "connection", "refused", "reset", "eof")
    return not any(marker in text for marker in dead)


def _call_provider(
    provider: str,
    messages: list[dict],
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    retries: int,
    model: Optional[str] = None,
) -> str:
    """Route to the appropriate provider implementation. `model` overrides the
    provider's env-configured model for this call only (e.g. a stronger model
    for document review)."""
    if provider in MISTRAL_PROVIDERS:
        return _call_mistral(messages, system_prompt, temperature, max_tokens, retries, model,
                              key_env=MISTRAL_PROVIDERS[provider])
    elif provider == "stepfun":
        return _call_stepfun(messages, system_prompt, temperature, max_tokens, retries, model)
    elif provider == "openrouter":
        return _call_openrouter(messages, system_prompt, temperature, max_tokens, retries, model)
    elif provider in _OPENAI_COMPAT:
        return _call_openai_compat(provider, messages, system_prompt, temperature, max_tokens, retries, model)
    elif provider == "litellm-gateway":
        return _call_litellm_gateway(messages, system_prompt, temperature, max_tokens, retries, model)
    else:
        return _call_ollama(messages, system_prompt, temperature, max_tokens, retries, model)


def _call_mistral(
    messages: list[dict],
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    retries: int,
    model: Optional[str] = None,
    key_env: str = "MISTRAL_API_KEY",
) -> str:
    api_key = os.environ.get(key_env) or os.environ.get("CLOUD_API_KEY")
    if not api_key:
        raise ValueError(f"{key_env} not set (nor CLOUD_API_KEY)")

    model = model or (os.environ.get("MISTRAL_MODEL") or os.environ.get("CLOUD_MODEL", "mistral-tiny"))
    full_messages = _build_messages(messages, system_prompt)

    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": full_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=_http_timeout_for(full_messages),
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"].get("content") or ""
            if not content.strip():
                raise RuntimeError(
                    f"mistral/{model} returned empty content (max_tokens={max_tokens})")
            return content
        except requests.HTTPError as e:
            if resp.status_code in (401, 403):
                raise ValueError(f"Mistral API key invalid or unauthorized (HTTP {resp.status_code})") from e
            if attempt < retries and _retry_same_provider(e):
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Mistral API error after {attempt+1} attempts: {e}")
        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            if attempt < retries and _retry_same_provider(e):
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Mistral API error after {attempt+1} attempts: {e}")


def _call_stepfun(
    messages: list[dict],
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    retries: int,
    model: Optional[str] = None,
) -> str:
    """StepFun native API (OpenAI-compatible) — not routed via OpenRouter."""
    api_key = os.environ.get("STEPFUN_API_KEY") or os.environ.get("CLOUD_API_KEY")
    if not api_key:
        raise ValueError("STEPFUN_API_KEY not set (nor CLOUD_API_KEY)")

    region = os.environ.get("STEPFUN_REGION", "international").strip().lower()
    base_url = "https://api.stepfun.com/v1" if region == "china" else "https://api.stepfun.ai/v1"
    model = model or (os.environ.get("STEPFUN_MODEL") or os.environ.get("CLOUD_MODEL", "step-3.5-flash"))
    full_messages = _build_messages(messages, system_prompt)

    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": full_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=_http_timeout_for(full_messages),
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            if attempt < retries and _retry_same_provider(e):
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"StepFun API error after {attempt+1} attempts: {e}")


def _call_litellm_gateway(
    messages: list[dict],
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    retries: int,
    model: Optional[str] = None,
) -> str:
    """Route through atelier/forge/litellm-gateway instead of one JIS-managed key.

    Added 2026-08-15, additive: nothing above this function changed, and no
    existing provider chain (FALLBACK_PROVIDERS, reviewer._review_chain) calls
    it yet. It exists to be tried standalone first.

    The gateway holds its own model-level fallback chain (router_settings in
    its config.yaml — mistral-medium falls to nvidia-nim, then groq-fast, then
    zai-glm, then ollama-gemma) and its own retry/cooldown handling, so a call
    here gets that behavior for free rather than needing key_quarantine.py's
    44-entry table reimplemented a second time. Verified end to end 2026-08-15:
    a mistral-medium request returned content from llama-3.1-8b-instant
    (groq-fast) in 1.71s — the gateway's own fallback firing mid-call, invisibly
    to the caller.

    Auth is a Virtual Key scoped to this project's registered models
    (LITELLM_GATEWAY_API_KEY), not the gateway's master key — a leaked or
    runaway JIS key then cannot spend against another project's budget or reach
    a model this project was never given.
    """
    base_url = os.environ.get("LITELLM_GATEWAY_URL", "http://localhost:4001")
    api_key = os.environ.get("LITELLM_GATEWAY_API_KEY")
    if not api_key:
        raise ValueError("LITELLM_GATEWAY_API_KEY not set")

    model = model or os.environ.get("LITELLM_GATEWAY_MODEL", "mistral-medium")
    full_messages = _build_messages(messages, system_prompt)

    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": full_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                # Not _http_timeout_for alone: that sizes a budget to one
                # model's response time, and this endpoint is a whole chain
                # behind one request. See _GATEWAY_READ_TIMEOUT. The
                # prompt-scaled value still wins when it is the larger of the
                # two, so a review-sized body keeps the headroom it was given.
                timeout=(_HTTP_TIMEOUT[0],
                         max(_http_timeout_for(full_messages)[1],
                             _GATEWAY_READ_TIMEOUT)),
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"].get("content") or ""
            if not content.strip():
                raise RuntimeError(
                    f"litellm-gateway/{model} returned empty content (max_tokens={max_tokens})")
            return content
        except (requests.RequestException, KeyError, json.JSONDecodeError, RuntimeError) as e:
            if attempt < retries and _retry_same_provider(e):
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"litellm-gateway API error after {attempt+1} attempts: {e}")


def _call_openrouter(
    messages: list[dict],
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    retries: int,
    model: Optional[str] = None,
) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not set")

    model = model or (os.environ.get("OPENROUTER_MODEL") or os.environ.get("CLOUD_MODEL", "stepfun/step-3.5-flash"))
    full_messages = _build_messages(messages, system_prompt)

    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://local.hermes",
                },
                json={
                    "model": model,
                    "messages": full_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=_http_timeout_for(full_messages),
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            if attempt < retries and _retry_same_provider(e):
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"OpenRouter API error after {attempt+1} attempts: {e}")


# OpenAI-compatible providers reachable with just a base URL + bearer key.
# (provider -> (base_url, api-key env vars tried in order, default model env)).
# Used for the review fallback chain: independent providers that offer
# small/medium models comparable to mistral-medium. Model is normally passed
# explicitly per call (reviewer._review_chain), so the default env is optional.
_OPENAI_COMPAT = {
    # OpenCode Zen free tier (only *-free / big-pickle usable; paid models 401).
    "opencode": ("https://opencode.ai/zen/v1", ("OPENCODE_API_KEY",), "OPENCODE_MODEL"),
    # OpenCode Zen "go" = same key, PAID endpoint — unlocks the paid catalog
    # (glm-5, deepseek-v4, qwen3.x …). Reuses the opencode key if no go-specific one.
    "opencode-go": ("https://opencode.ai/zen/go/v1", ("OPENCODE_GO_API_KEY", "OPENCODE_API_KEY"), "OPENCODE_GO_MODEL"),
    # NVIDIA NIM — one entry per key for independent rate-limit pools.
    #   nvidia         = nvapi-jps... (OpenCode auth.json + JIS .env, env:NVIDIA_API_KEY)
    #   nvidia-back    = nvapi--XQ... (Hermes auth.json, api-key-cao)
    #   nvidia-tertiary= nvapi-cbu... (Hermes auth.json, api-key-com)
    #   nvidia-quaternary = nvapi-epV... (Hermes, api-key-kaso)
    #   nvidia-quinary = nvapi-y12... (Hermes, api-key-kazukiyunome)
    #   nvidia-senary  = nvapi-kt_... (Hermes, api-key-gei)
    #   nvidia-septenary = nvapi-78O... (Hermes, yunome0505)
    "nvidia":              ("https://integrate.api.nvidia.com/v1", ("NVIDIA_API_KEY",), "NVIDIA_MODEL"),
    "nvidia-back":         ("https://integrate.api.nvidia.com/v1", ("NVIDIA_BACKUP_API_KEY",), "NVIDIA_MODEL"),
    "nvidia-tertiary":     ("https://integrate.api.nvidia.com/v1", ("NVIDIA_TERTIARY_API_KEY",), "NVIDIA_MODEL"),
    "nvidia-quaternary":   ("https://integrate.api.nvidia.com/v1", ("NVIDIA_QUATERNARY_API_KEY",), "NVIDIA_MODEL"),
    "nvidia-quinary":      ("https://integrate.api.nvidia.com/v1", ("NVIDIA_QUINARY_API_KEY",), "NVIDIA_MODEL"),
    "nvidia-senary":       ("https://integrate.api.nvidia.com/v1", ("NVIDIA_SENARY_API_KEY",), "NVIDIA_MODEL"),
    "nvidia-septenary":    ("https://integrate.api.nvidia.com/v1", ("NVIDIA_SEPTENARY_API_KEY",), "NVIDIA_MODEL"),
    "zai":          ("https://api.z.ai/api/paas/v4", ("ZAI_API_KEY",), "ZAI_MODEL"),
    "zai-back":     ("https://api.z.ai/api/paas/v4", ("ZAI_BACKUP_API_KEY",), "ZAI_MODEL"),
    "zai-tertiary": ("https://api.z.ai/api/paas/v4", ("ZAI_TERTIARY_API_KEY",), "ZAI_MODEL"),
    "zai-quaternary": ("https://api.z.ai/api/paas/v4", ("ZAI_QUATERNARY_API_KEY",), "ZAI_MODEL"),
    "zai-quinary":  ("https://api.z.ai/api/paas/v4", ("ZAI_QUINARY_API_KEY",), "ZAI_MODEL"),
    "zai-senary":    ("https://api.z.ai/api/paas/v4", ("ZAI_SENARY_API_KEY",), "ZAI_MODEL"),
    "zai-septenary": ("https://api.z.ai/api/paas/v4", ("ZAI_SEPTENARY_API_KEY",), "ZAI_MODEL"),
    "zai-octonary":  ("https://api.z.ai/api/paas/v4", ("ZAI_OCTONARY_API_KEY",), "ZAI_MODEL"),
    "zai-nonary":    ("https://api.z.ai/api/paas/v4", ("ZAI_NONARY_API_KEY",), "ZAI_MODEL"),
    "zai-denary":    ("https://api.z.ai/api/paas/v4", ("ZAI_DENARY_API_KEY",), "ZAI_MODEL"),
    "zai-undenary":  ("https://api.z.ai/api/paas/v4", ("ZAI_UNDENARY_API_KEY",), "ZAI_MODEL"),
    # Groq — ultra-low-latency inference, OpenAI-compatible. One entry per key.
    #   groq            = gsk_Z6zh... (original, shared with OpenCode auth.json)
    #   groq-back       = gsk_REJM... (second key, added 2026-08-09)
    #   groq-tertiary..undenary = 9 valid keys provided by user 2026-08-09
    "groq":            ("https://api.groq.com/openai/v1", ("GROQ_API_KEY",), "GROQ_MODEL"),
    "groq-back":       ("https://api.groq.com/openai/v1", ("GROQ_BACKUP_API_KEY",), "GROQ_MODEL"),
    "groq-tertiary":   ("https://api.groq.com/openai/v1", ("GROQ_TERTIARY_API_KEY",), "GROQ_MODEL"),
    "groq-quaternary": ("https://api.groq.com/openai/v1", ("GROQ_QUATERNARY_API_KEY",), "GROQ_MODEL"),
    "groq-quinary":    ("https://api.groq.com/openai/v1", ("GROQ_QUINARY_API_KEY",), "GROQ_MODEL"),
    "groq-senary":     ("https://api.groq.com/openai/v1", ("GROQ_SENARY_API_KEY",), "GROQ_MODEL"),
    "groq-septenary":  ("https://api.groq.com/openai/v1", ("GROQ_SEPTENARY_API_KEY",), "GROQ_MODEL"),
    "groq-octonary":   ("https://api.groq.com/openai/v1", ("GROQ_OCTONARY_API_KEY",), "GROQ_MODEL"),
    "groq-nonary":     ("https://api.groq.com/openai/v1", ("GROQ_NONARY_API_KEY",), "GROQ_MODEL"),
    "groq-denary":     ("https://api.groq.com/openai/v1", ("GROQ_DENARY_API_KEY",), "GROQ_MODEL"),
    "groq-undenary":   ("https://api.groq.com/openai/v1", ("GROQ_UNDENARY_API_KEY",), "GROQ_MODEL"),
    "groq-duodenary":  ("https://api.groq.com/openai/v1", ("GROQ_DUODECENARY_API_KEY",), "GROQ_MODEL"),
    # Together AI — OpenAI-compatible, hosts open models (Llama, Qwen, Deepseek).
    # Add TOGETHER_API_KEY to .env to activate.
    "together":  ("https://api.together.xyz/v1", ("TOGETHER_API_KEY",), "TOGETHER_MODEL"),
}


def _call_openai_compat(
    provider: str,
    messages: list[dict],
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    retries: int,
    model: Optional[str] = None,
) -> str:
    """Generic OpenAI-compatible chat call (OpenCode Zen, Nvidia NIM, Z.ai …).

    `model` is required (explicitly or via the provider's *_MODEL env); these
    providers host many models with no sensible single default. Reasoning models
    (e.g. deepseek-v4-flash) spend part of max_tokens on hidden reasoning, so a
    generous timeout and token budget are used."""
    base_url, key_envs, model_env = _OPENAI_COMPAT[provider]
    api_key = next((os.environ[e] for e in key_envs if os.environ.get(e)), None)
    if not api_key:
        raise ValueError(f"{key_envs[0]} not set")
    model = model or os.environ.get(model_env)
    if not model:
        raise ValueError(f"no model specified for provider '{provider}' (set {model_env})")
    full_messages = _build_messages(messages, system_prompt)

    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": full_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=_http_timeout_for(full_messages),
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"].get("content") or ""
            if not content.strip():
                # Reasoning models (e.g. deepseek-v4-flash) can spend the whole
                # max_tokens budget on hidden reasoning and return HTTP 200 with
                # an empty content string (finish_reason=length). Raising here
                # lets the caller's provider chain fall through to the next model
                # instead of silently persisting an empty result.
                raise RuntimeError(
                    f"{provider}/{model} returned empty content "
                    f"(reasoning-token exhaustion at max_tokens={max_tokens}?)")
            return content
        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            if attempt < retries and _retry_same_provider(e):
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"{provider} API error after {attempt+1} attempts: {e}")


def _call_ollama(
    messages: list[dict],
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    retries: int,
    model: Optional[str] = None,
) -> str:
    endpoint = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434/api/chat")
    model = model or (os.environ.get("OLLAMA_MODEL", "gemma-4-26b-a4b-it-gguf"))
    timeout = int(os.environ.get("OLLAMA_TIMEOUT", "180"))
    keep_alive = os.environ.get("OLLAMA_KEEP_ALIVE", "5m")
    full_messages = _build_messages(messages, system_prompt)

    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                endpoint,
                json={
                    "model": model,
                    "messages": full_messages,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                    "keep_alive": keep_alive,
                },
                timeout=(_OLLAMA_CONNECT_TIMEOUT, timeout),
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            if attempt < retries and _retry_same_provider(e):
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Ollama API error after {attempt+1} attempts: {e}")


def _build_messages(messages: list[dict], system_prompt: str) -> list[dict]:
    """Build message list, prepending system prompt if provided."""
    if not system_prompt:
        return messages
    return [{"role": "system", "content": system_prompt}] + messages
