"""Unified LLM client — supports Ollama (local), Mistral, and OpenRouter (cloud).

Provider selection:
  env ANALYSIS_PROVIDER   = "mistral" | "openrouter" | "ollama" (default)
  env FALLBACK_PROVIDERS  = comma-separated chain to try in order when the
                            primary hits rate limit / 5xx / missing API key,
                            e.g. "openrouter,ollama"
  env FALLBACK_PROVIDER   = legacy single-provider form (used when
                            FALLBACK_PROVIDERS is unset)
  env MISTRAL_MODEL       = model for the mistral provider (else CLOUD_MODEL, else mistral-tiny)
  env OPENROUTER_MODEL    = model for the openrouter provider (else CLOUD_MODEL,
                            else stepfun/step-3.5-flash)
  env OLLAMA_MODEL        = model for the ollama provider
  env CLOUD_MODEL         = shared model override (legacy)
  env CLOUD_API_KEY       = optional key override (else MISTRAL_API_KEY / OPENROUTER_API_KEY)

Chained fallback:
  call_llm() tries the primary provider; on a transient error (429 rate limit,
  5xx server error, timeout) or a missing API key it moves down the fallback
  chain. Set FALLBACK_PROVIDERS=openrouter,ollama to spill over to a cheap
  cloud model first and local Ollama last.

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


def _is_transient_error(e: Exception) -> bool:
    """Check if a RuntimeError is a transient (retryable) failure."""
    err_str = str(e).lower()
    # Rate limits, server errors, network issues
    markers = [
        "429", "rate limit", "too many requests", "quota",
        "502", "503", "504", "500", "bad gateway", "service unavailable",
        "timeout", "connection", "eof", "refused", "reset",
    ]
    return any(m in err_str for m in markers)


def call_llm(
    messages: list[dict],
    system_prompt: str = "",
    temperature: float = 0.1,
    max_tokens: int = 512,
    provider: Optional[str] = None,
    retries: int = 2,
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

    Returns:
        Response text string.
    """
    global call_llm_counter
    call_llm_counter += 1
    cid = call_llm_counter  # short alias for log prefix

    primary = provider or os.environ.get("ANALYSIS_PROVIDER", "ollama")
    fallbacks_env = os.environ.get("FALLBACK_PROVIDERS") or os.environ.get("FALLBACK_PROVIDER", "")
    chain = [primary] + [
        p.strip() for p in fallbacks_env.split(",")
        if p.strip() and p.strip() != primary
    ]

    errors: list[str] = []
    for i, prov in enumerate(chain):
        is_last = i == len(chain) - 1
        try:
            return _call_provider(prov, messages, system_prompt, temperature, max_tokens, retries)
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
            print(f"[llm_client #{cid}] {prov} transient failure, trying next fallback: {e}")


def _call_provider(
    provider: str,
    messages: list[dict],
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    retries: int,
) -> str:
    """Route to the appropriate provider implementation."""
    if provider == "mistral":
        return _call_mistral(messages, system_prompt, temperature, max_tokens, retries)
    elif provider == "openrouter":
        return _call_openrouter(messages, system_prompt, temperature, max_tokens, retries)
    else:
        return _call_ollama(messages, system_prompt, temperature, max_tokens, retries)


def _call_mistral(
    messages: list[dict],
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    retries: int,
) -> str:
    api_key = os.environ.get("MISTRAL_API_KEY") or os.environ.get("CLOUD_API_KEY")
    if not api_key:
        raise ValueError("MISTRAL_API_KEY not set (nor CLOUD_API_KEY)")

    model = os.environ.get("MISTRAL_MODEL") or os.environ.get("CLOUD_MODEL", "mistral-tiny")
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
            return resp.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Mistral API error after {retries+1} attempts: {e}")


def _call_openrouter(
    messages: list[dict],
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    retries: int,
) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not set")

    model = os.environ.get("OPENROUTER_MODEL") or os.environ.get("CLOUD_MODEL", "stepfun/step-3.5-flash")
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


def _call_ollama(
    messages: list[dict],
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    retries: int,
) -> str:
    endpoint = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434/api/chat")
    model = os.environ.get("OLLAMA_MODEL", "gemma-4-26b-a4b-it-gguf")
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
