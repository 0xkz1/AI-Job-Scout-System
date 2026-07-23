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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent / "10_output" / ".key_quarantine.json"

# Auth failures usually mean a revoked key, but Mistral also answers 401 once a
# free-tier allowance is spent — indistinguishable from the outside, so both get
# a cooldown rather than being written off. Kept short deliberately: a key that
# is still spent just fails once on release and is quarantined again for another
# 5 days, so retrying cheaply beats guessing when the quota actually resets.
DEFAULT_COOLDOWN_DAYS = 5
_QUOTA_MARKERS = (
    "429", "rate limit", "too many requests", "quota", "insufficient",
    "401", "403", "unauthorized", "forbidden",
)


def is_quota_or_auth_error(err: str) -> bool:
    """True when the failure looks like an exhausted or rejected key."""
    e = (err or "").lower()
    return any(m in e for m in _QUOTA_MARKERS)


def _load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  ⚠ could not write quarantine state: {e}")


def quarantine(provider: str, reason: str = "", cooldown_days: int = DEFAULT_COOLDOWN_DAYS) -> None:
    """Sideline `provider` for `cooldown_days`. Re-quarantining refreshes the clock."""
    state = _load()
    now = datetime.now(timezone.utc)
    state[provider] = {
        "quarantined_at": now.isoformat(),
        "until": (now + timedelta(days=cooldown_days)).isoformat(),
        "reason": (reason or "")[:200],
    }
    _save(state)
    print(f"  🔒 {provider} quarantined for {cooldown_days}d ({reason[:60]})")


def release(provider: str) -> bool:
    state = _load()
    if provider in state:
        del state[provider]
        _save(state)
        return True
    return False


def is_quarantined(provider: str) -> bool:
    """True while the cooldown is live. Expired entries are dropped on read."""
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
        # Cooldown served — the provider returns to its original chain position.
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
