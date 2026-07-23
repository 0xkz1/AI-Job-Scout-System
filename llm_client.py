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

import json
import os
import time
import requests
from typing import Optional

from dotenv import load_dotenv

# Load the project .env so MISTRAL_API_KEY / ANALYSIS_PROVIDER etc. work
# without manually sourcing the file. Existing shell env vars take precedence.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


call_llm_counter = 0  # module-level call counter for structured logging


def _quarantine_filter_chain(chain: list[str]) -> list[str]:
    """Skip providers currently sidelined by key_quarantine (import kept lazy so
    llm_client still works if the module is absent)."""
    try:
        from key_quarantine import filter_chain
        return filter_chain(chain)
    except Exception:
        return chain


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
    # Rate limits, server errors, network issues
    markers = [
        "429", "rate limit", "too many requests", "quota",
        "502", "503", "504", "500", "bad gateway", "service unavailable",
        "timeout", "timed out", "connection", "eof", "refused", "reset",
        "401", "403", "unauthorized", "forbidden",
    ]
    return any(m in err_str for m in markers)


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

    errors: list[str] = []
    for i, prov in enumerate(chain):
        is_last = i == len(chain) - 1
        try:
            return _call_provider(prov, messages, system_prompt, temperature, max_tokens, retries, model)
        except ValueError as e:
            # Missing API key — skip to the next provider in the chain
            if is_last:
                raise RuntimeError("; ".join(errors + [f"{prov}: {e}"]))
            errors.append(f"{prov}: {e}")
            print(f"[llm_client #{cid}] {prov} unavailable ({e}), trying next fallback")
        except RuntimeError as e:
            if not _is_transient_error(e) or is_last:
                if errors:
                    raise RuntimeError("; ".join(errors + [f"{prov}: {e}"]))
                raise  # non-transient (or nothing left) → propagate
            errors.append(f"{prov}: {e}")
            _maybe_quarantine(prov, str(e))
            print(f"[llm_client #{cid}] {prov} transient failure, trying next fallback: {e}")


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
    if provider == "mistral":
        return _call_mistral(messages, system_prompt, temperature, max_tokens, retries, model)
    elif provider == "mistral-backup":
        return _call_mistral(messages, system_prompt, temperature, max_tokens, retries, model,
                              key_env="MISTRAL_API_KEY_BACKUP")
    elif provider == "mistral-tertiary":
        return _call_mistral(messages, system_prompt, temperature, max_tokens, retries, model,
                              key_env="MISTRAL_API_KEY_TERTIARY")
    elif provider == "stepfun":
        return _call_stepfun(messages, system_prompt, temperature, max_tokens, retries, model)
    elif provider == "openrouter":
        return _call_openrouter(messages, system_prompt, temperature, max_tokens, retries, model)
    elif provider in _OPENAI_COMPAT:
        return _call_openai_compat(provider, messages, system_prompt, temperature, max_tokens, retries, model)
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
                timeout=60,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"].get("content") or ""
            if not content.strip():
                raise RuntimeError(
                    f"mistral/{model} returned empty content (max_tokens={max_tokens})")
            return content
        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Mistral API error after {retries+1} attempts: {e}")


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
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"StepFun API error after {retries+1} attempts: {e}")


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
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"OpenRouter API error after {retries+1} attempts: {e}")


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
    "nvidia":   ("https://integrate.api.nvidia.com/v1", ("NVIDIA_API_KEY",), "NVIDIA_MODEL"),
    "zai":      ("https://api.z.ai/api/paas/v4", ("ZAI_API_KEY", "ZAI_CODING_API_KEY"), "ZAI_MODEL"),
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
                timeout=120,
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
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"{provider} API error after {retries+1} attempts: {e}")


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
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Ollama API error after {retries+1} attempts: {e}")


def _build_messages(messages: list[dict], system_prompt: str) -> list[dict]:
    """Build message list, prepending system prompt if provided."""
    if not system_prompt:
        return messages
    return [{"role": "system", "content": system_prompt}] + messages
