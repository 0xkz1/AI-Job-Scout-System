"""A Cloudflare challenge is only worth a headed retry if someone can solve it.

The scraper already refused the headed relaunch when no X server was reachable,
because the cron job inherits DISPLAY from the desktop that spawned it. On this
machine the socket IS reachable — the scheduler runs on the desktop — so the
check passed, a real browser window opened for every search at 02:00, and the
scraper polled for thirty seconds waiting for a keypress.

Measured on 2026-09-23: 2,046 seconds across 18 searches, 38% of the night's
scrape budget, for zero jobs.
"""
import sys

import scraper_indeed


def test_no_terminal_means_nobody_is_watching(monkeypatch):
    class _NotATty:
        def isatty(self): return False
    monkeypatch.setattr(sys, "stdin", _NotATty())
    assert scraper_indeed._a_human_is_watching() is False


def test_a_terminal_means_someone_might_be(monkeypatch):
    class _Tty:
        def isatty(self): return True
    monkeypatch.setattr(sys, "stdin", _Tty())
    assert scraper_indeed._a_human_is_watching() is True


def test_closed_stdin_is_not_a_person(monkeypatch):
    """A detached process can raise on isatty rather than answering it."""
    class _Closed:
        def isatty(self): raise ValueError("I/O operation on closed file")
    monkeypatch.setattr(sys, "stdin", _Closed())
    assert scraper_indeed._a_human_is_watching() is False


def test_a_live_display_alone_does_not_authorise_a_headed_retry(monkeypatch):
    """The exact case that cost the 2,046 seconds: window can open, nobody there."""
    class _NotATty:
        def isatty(self): return False
    monkeypatch.setattr(sys, "stdin", _NotATty())
    monkeypatch.setattr(scraper_indeed, "_headed_display_available", lambda: True)
    assert scraper_indeed._can_solve_challenge() is False


def test_both_conditions_allow_the_retry(monkeypatch):
    class _Tty:
        def isatty(self): return True
    monkeypatch.setattr(sys, "stdin", _Tty())
    monkeypatch.setattr(scraper_indeed, "_headed_display_available", lambda: True)
    assert scraper_indeed._can_solve_challenge() is True
