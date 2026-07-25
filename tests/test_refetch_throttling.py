"""An empty extraction is throttling, not a plain miss.

Adzuna's block page renders with HTTP 200 and no visible notice, so _page_state
reports "ok" and then the selectors find nothing. Counting that as an ordinary miss
reset the consecutive-block counter, so an alternating block/empty sequence never
reached MAX_CONSECUTIVE_BLOCKS: the run kept hammering a site that had already
stopped answering — 0 recoveries in 5 attempts, immediately after 7 of 12 had
succeeded — which deepens the block for the next attempt.

Tested as the decision itself rather than by driving refetch() through a fake
browser: mocking async_playwright convincingly enough took more scaffolding than
the logic under test, and a half-mocked version launched a real browser and hung.
"""
import refetch_unscoreable as rf


def classify(desc: str) -> str:
    """The branch order inside refetch's loop, for a page that answered 200.

    Kept in step with the loop by the tests below; if the loop's order changes and
    this does not, test_loop_still_checks_empty_before_length fails.
    """
    if not desc:
        return "throttled"
    if len(desc) < 400 or rf.is_junk_description(desc):
        return "miss"
    return "recovered"


def test_empty_extraction_is_treated_as_throttling():
    assert classify("") == "throttled"


def test_short_result_is_a_miss_not_throttling():
    """A thin posting must not trigger the backoff, or a run of genuinely short
    postings would read as a block and stop the batch early."""
    assert classify("short but real prose " * 5) == "miss"


def test_javascript_result_is_a_miss():
    assert classify("window.addEventListener('load', function(e) {" + "x" * 500) == "miss"


def test_full_description_is_recovered():
    assert classify("Real posting prose. " * 40) == "recovered"


def test_loop_still_checks_empty_before_length(monkeypatch):
    """Guards the branch ORDER in the source: the empty check has to come first, or
    an empty string falls into the `len(desc) < 400` miss branch and the counter
    resets again — exactly the original bug."""
    import inspect

    src = inspect.getsource(rf.refetch)
    empty_at = src.find("if not desc:")
    length_at = src.find("if len(desc) < 400")
    assert empty_at != -1, "the empty-extraction branch is gone"
    assert length_at != -1
    assert empty_at < length_at, "empty must be classified before the length bar"


def test_empty_branch_increments_the_block_counter():
    """It must share the counter with real 403s, not keep a separate one — that is
    what makes alternating block/empty reach the stop threshold."""
    import inspect

    src = inspect.getsource(rf.refetch)
    branch = src[src.find("if not desc:"):src.find("if len(desc) < 400")]
    assert "blocks += 1" in branch
    assert "MAX_CONSECUTIVE_BLOCKS" in branch
    assert "break" in branch, "hitting the threshold must stop the run"
    assert "BLOCKED_BACKOFF_MS" in branch, "and back off before continuing"


def test_default_batch_is_small():
    """The cap exists because one long run fails where repeated small ones succeed:
    7 of 12 recovered, then 0 of 5 in an uncapped run straight after."""
    assert 1 <= rf.DEFAULT_BATCH <= 20


def test_backoff_is_long_enough_to_matter():
    assert rf.BLOCKED_BACKOFF_MS >= 30000
    assert rf.SETTLE_MS >= 4000
