"""Temporarily sideline providers whose key hit a limit, then let them back in.

A key that has exhausted its monthly quota is not dead — it is dead *until the
quota resets*. Deleting it from FALLBACK_PROVIDERS loses a working key; leaving
it in place burns ~6s of retries on every single call (3 attempts with backoff)
before the chain moves on.

So the chain itself is never edited. Providers are recorded here with a cooldown,
call_llm skips them while the cooldown is live, and when it expires they return
to exactly the position they always occupied in FALLBACK_PROVIDERS.

CLI:
  .venv/bin/python3 key_quarantine.py --list
  .venv/bin/python3 key_quarantine.py --quarantine mistral --days 30 --reason "monthly quota"
  .venv/bin/python3 key_quarantine.py --release mistral
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent / "10_output" / ".key_quarantine.json"

# Every mutation here is read-modify-write on one small file, and the enrichment
# pass now calls it from several threads at once. Without the lock two providers
# failing together race, and the second write drops the first one's entry — the
# key stays in the chain and keeps costing a full round of retries per call.
_STATE_LOCK = threading.RLock()

# Auth failures usually mean a revoked key, but Mistral also answers 401 once a
# free-tier allowance is spent — indistinguishable from the outside, so both get
# a cooldown rather than being written off. Kept short deliberately: a key that
# is still spent just fails once on release and is quarantined again for another
# 5 days, so retrying cheaply beats guessing when the quota actually resets.
DEFAULT_COOLDOWN_DAYS = 5

# A 429 is NOT the same failure as a 401, and treating them alike sidelined seven
# working keys for five days. Mistral answers 429 both for a spent monthly
# allowance (retry in weeks) and for exceeding requests-per-second (retry in
# seconds). Six freshly created keys were quarantined within a 10-second window,
# each "after 1 attempts", while iterating the chain — throttling, not exhaustion;
# with 3s between calls all seven answered normally.
#
# So a rate-limit response gets minutes, not days. If the allowance really is gone
# the key fails again on release and is re-quarantined, which costs one wasted call
# — far cheaper than losing a live key for five days.
RATE_LIMIT_COOLDOWN_MINUTES = 15
_RATE_LIMIT_MARKERS = ("429", "rate limit", "too many requests")
_AUTH_MARKERS = (
    "401", "402", "403", "unauthorized", "forbidden", "quota", "insufficient",
    "payment required", "exceeded balance",
)
_QUOTA_MARKERS = _RATE_LIMIT_MARKERS + _AUTH_MARKERS


def is_quota_or_auth_error(err: str) -> bool:
    """True when the failure looks like an exhausted or rejected key."""
    e = (err or "").lower()
    return any(m in e for m in _QUOTA_MARKERS)


def is_rate_limit_error(err: str) -> bool:
    """True for throttling (retry in minutes) rather than a spent/rejected key.

    Checked before the auth markers so a message carrying both reads as the
    recoverable one — the cost of guessing "throttled" wrongly is one failed call,
    while guessing "exhausted" wrongly costs the key for days.
    """
    e = (err or "").lower()
    return any(m in e for m in _RATE_LIMIT_MARKERS)


def cooldown_for(err: str) -> float:
    """Cooldown in days appropriate to the failure in `err`."""
    if is_rate_limit_error(err):
        return RATE_LIMIT_COOLDOWN_MINUTES / (24 * 60)
    return DEFAULT_COOLDOWN_DAYS


def _load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(state: dict) -> None:
    # Written via a temp file and renamed: a crash (or a kill) part way through
    # a direct write leaves unparseable JSON, and _load answers {} to that —
    # silently releasing every quarantined key at once.
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"  ⚠ could not write quarantine state: {e}")


def quarantine(provider: str, reason: str = "", cooldown_days: float | None = None) -> None:
    """Sideline `provider`. Re-quarantining refreshes the clock.

    cooldown_days defaults to a length chosen from `reason` (see cooldown_for), so
    throttling costs minutes and a spent key costs days. Pass a number to override.
    """
    if cooldown_days is None:
        cooldown_days = cooldown_for(reason)
    with _STATE_LOCK:
        state = _load()
        now = datetime.now(timezone.utc)
        state[provider] = {
            "quarantined_at": now.isoformat(),
            "until": (now + timedelta(days=cooldown_days)).isoformat(),
            "reason": (reason or "")[:200],
        }
        _save(state)
    span = (f"{cooldown_days * 24 * 60:.0f}min" if cooldown_days < 1
            else f"{cooldown_days:g}d")
    print(f"  🔒 {provider} quarantined for {span} ({reason[:60]})")


def release(provider: str) -> bool:
    with _STATE_LOCK:
        state = _load()
        if provider in state:
            del state[provider]
            _save(state)
            return True
        return False


def is_quarantined(provider: str) -> bool:
    """True while the cooldown is live. Expired entries are dropped on read."""
    with _STATE_LOCK:
        state = _load()
        entry = state.get(provider)
        if not entry:
            return False
        try:
            until = datetime.fromisoformat(entry["until"])
        except Exception:
            del state[provider]
            _save(state)
            return False
        if datetime.now(timezone.utc) >= until:
            # Cooldown served — the provider returns to its chain position.
            del state[provider]
            _save(state)
            print(f"  🔓 {provider} cooldown expired, restored to fallback chain")
            return False
        return True


def filter_chain(chain: list[str]) -> list[str]:
    """Drop quarantined providers, preserving order.

    Never returns empty: if every provider is sidelined, the original chain is
    used anyway — a call that might fail beats no call at all.
    """
    active = [p for p in chain if not is_quarantined(p)]
    return active or chain


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--quarantine", metavar="PROVIDER")
    ap.add_argument("--release", metavar="PROVIDER")
    ap.add_argument("--days", type=int, default=DEFAULT_COOLDOWN_DAYS)
    ap.add_argument("--reason", default="manual")
    args = ap.parse_args()

    if args.quarantine:
        quarantine(args.quarantine, args.reason, args.days)
        return 0
    if args.release:
        print(f"released {args.release}" if release(args.release)
              else f"{args.release} was not quarantined")
        return 0

    state = _load()
    if not state:
        print("隔離中のプロバイダ: なし")
        return 0
    now = datetime.now(timezone.utc)
    print("隔離中のプロバイダ:")
    for prov, entry in state.items():
        try:
            until = datetime.fromisoformat(entry["until"])
            left = until - now
            remaining = f"あと{left.days}日" if left.total_seconds() > 0 else "期限切れ(次回呼び出しで復帰)"
        except Exception:
            remaining = "?"
        print(f"  {prov:16s} {remaining:28s} {entry.get('reason','')[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
