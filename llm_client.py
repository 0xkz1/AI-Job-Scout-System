"""Unified LLM client — supports Ollama (local), Mistral, and OpenRouter (cloud).

Provider selection:
  env ANALYSIS_PROVIDER  = "mistral" | "openrouter" | "ollama" (default)
  env FALLBACK_PROVIDER  = provider to try when primary hits rate limit / 5xx
                            (default: "" = no fallback)
  env CLOUD_MODEL       = model name override (defaults vary by provider)
  env CLOUD_API_KEY     = optional override (else uses MISTRAL_API_KEY or OPENROUTER_API_KEY)

Two-tier fallback:
  call_llm() first tries primary provider; if it fails with a transient error
  (429 rate limit, 5xx server error, timeout), it automatically retries the
  fallback provider.  Set FALLBACK_PROVIDER=ollama to spill over when cloud
  is throttled.

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
    fallback = os.environ.get("FALLBACK_PROVIDER", "").strip()

    # Try primary
    try:
        return _call_provider(primary, messages, system_prompt, temperature, max_tokens, retries)
    except RuntimeError as e:
        if not _is_transient_error(e):
            raise  # non-transient → propagate immediately
        # Transient failure — attempt fallback
        if not fallback or fallback == primary:
            raise

        print(f"[llm_client #{cid}] {primary} transient failure, falling back to {fallback}: {e}")
        try:
            return _call_provider(fallback, messages, system_prompt, temperature, max_tokens, retries)
        except RuntimeError as e2:
            raise RuntimeError(
                f"Primary({primary}) failed: {e}; "
                f"Fallback({fallback}) also failed: {e2}"
            )


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

    model = os.environ.get("CLOUD_MODEL", "mistral-tiny")
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

    model = os.environ.get("CLOUD_MODEL", "google/gemini-2.0-flash-lite-preview-02-05")
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
