"""A 429 must not cost a key five days.

Mistral answers 429 both for a spent monthly allowance (retry in weeks) and for
exceeding requests-per-second (retry in seconds). Treating them alike sidelined
seven working keys: six freshly created ones were quarantined inside a 10-second
window, each "after 1 attempts", while the chain was iterated — throttling, not
exhaustion. With 3s between calls all seven answered a full-size request normally.

The asymmetry drives the choice: guessing "throttled" wrongly costs one failed
call, guessing "exhausted" wrongly costs a live key for days.
"""
import key_quarantine as kq
import pytest


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(kq, "STATE_FILE", tmp_path / "q.json")


def test_rate_limit_gets_minutes_not_days():
    assert kq.cooldown_for("429 Client Error: Too Many Requests") < 1
    minutes = kq.cooldown_for("429 rate limit") * 24 * 60
    assert minutes == pytest.approx(kq.RATE_LIMIT_COOLDOWN_MINUTES)


def test_spent_or_revoked_key_gets_days():
    assert kq.cooldown_for("401 Client Error: Unauthorized") == kq.DEFAULT_COOLDOWN_DAYS
    assert kq.cooldown_for("402 You exceeded your balance") == kq.DEFAULT_COOLDOWN_DAYS
    assert kq.cooldown_for("quota exceeded") == kq.DEFAULT_COOLDOWN_DAYS


def test_message_with_both_signals_reads_as_recoverable():
    """A 429 body that also says "quota" must take the short cooldown — the cheap
    mistake is retrying too early, not losing the key."""
    assert kq.cooldown_for("429 Too Many Requests: quota") < 1


def test_unrecognised_failure_gets_the_conservative_default():
    assert kq.cooldown_for("connection reset by peer") == kq.DEFAULT_COOLDOWN_DAYS


def test_quarantine_picks_the_cooldown_from_the_reason():
    kq.quarantine("mistral-denary", "429 Client Error: Too Many Requests")
    kq.quarantine("mistral-backup", "401 Client Error: Unauthorized")
    state = kq._load()
    from datetime import datetime

    def hours(entry):
        a = datetime.fromisoformat(entry["quarantined_at"])
        b = datetime.fromisoformat(entry["until"])
        return (b - a).total_seconds() / 3600

    assert hours(state["mistral-denary"]) < 1
    assert hours(state["mistral-backup"]) > 24


def test_explicit_cooldown_still_overrides():
    kq.quarantine("mistral", "429 rate limit", cooldown_days=30)
    from datetime import datetime

    e = kq._load()["mistral"]
    days = (datetime.fromisoformat(e["until"])
            - datetime.fromisoformat(e["quarantined_at"])).days
    assert days == 30


def test_a_rate_limited_key_returns_to_the_chain_after_its_cooldown(monkeypatch):
    """The behaviour that matters: a throttled key is usable again the same run,
    not five days later."""
    kq.quarantine("mistral-denary", "429 rate limit")
    chain = ["mistral-denary", "ollama"]
    assert kq.filter_chain(chain) == ["ollama"]

    # Simulate the cooldown expiring.
    from datetime import datetime, timedelta, timezone
    state = kq._load()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    state["mistral-denary"]["until"] = past
    kq._save(state)
    assert kq.filter_chain(chain) == ["mistral-denary", "ollama"]
