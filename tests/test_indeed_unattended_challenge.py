"""A Cloudflare challenge nobody can answer must stop the run, not be retried.

Indeed spent 2,046 seconds a night producing zero jobs: the cron job inherits a live
X socket from the desktop that spawned the scheduler, so the headed relaunch fired,
opened a real browser window per search and polled thirty seconds for a keypress.
Reproduced under `xvfb-run` with stdin closed: 49.3s per search, 36 searches.

The first attempt at this fix raised the ordinary CloudflareBlocked, which lands in
the retry loop — the 30s wait came back as 45s retry pauses and the night went from
2,046s/exit 0 to 2,400s/exit 124. Hence a distinct exception that is NOT a subclass,
and a caller that breaks. Measured after: 5.2s for the whole run.
"""
import sys

import pytest

import scraper_indeed
from scraper_indeed import CloudflareBlocked, CloudflareUnattended


class _Tty:
    def isatty(self): return True


class _NotATty:
    def isatty(self): return False


class _Closed:
    def isatty(self): raise ValueError("I/O operation on closed file")


def test_no_terminal_means_nobody_is_watching(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _NotATty())
    assert scraper_indeed._a_human_is_watching() is False


def test_a_terminal_means_someone_might_be(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Tty())
    assert scraper_indeed._a_human_is_watching() is True


def test_closed_stdin_is_not_a_person(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Closed())
    assert scraper_indeed._a_human_is_watching() is False


def test_a_live_display_alone_does_not_authorise_a_headed_retry(monkeypatch):
    """The exact case that cost the 2,046 seconds: a window can open, nobody is there."""
    monkeypatch.setattr(sys, "stdin", _NotATty())
    monkeypatch.setattr(scraper_indeed, "_headed_display_available", lambda: True)
    assert scraper_indeed._can_solve_challenge() is False


def test_both_conditions_allow_the_retry(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Tty())
    monkeypatch.setattr(scraper_indeed, "_headed_display_available", lambda: True)
    assert scraper_indeed._can_solve_challenge() is True


def test_unattended_is_not_retryable():
    """The regression guard. If CloudflareUnattended were a CloudflareBlocked it
    would be swallowed by the retry handler and earn 45s pauses instead of a stop."""
    assert not issubclass(CloudflareUnattended, CloudflareBlocked)
    with pytest.raises(CloudflareUnattended):
        try:
            raise CloudflareUnattended("no terminal")
        except CloudflareBlocked:  # must NOT catch it
            pytest.fail("the retry handler swallowed a structural block")
