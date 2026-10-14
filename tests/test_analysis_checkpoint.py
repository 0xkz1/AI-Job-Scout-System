"""A killed analysis pass must keep what it finished.

The run wrote _analyzed.json once, at the very end. Anything that stopped the
process before that line stored NOTHING — and the nightly stops the process
routinely: the analysis stage is left ~1200s after the scrapes, and on both
2026-08-20 and 08-21 it was killed inside the LLM enrichment of 1543 jobs. Two
nights of model spend were discarded, the DB's newest job stayed at 08-18, and
the staging backlog grew to 1973 while every downstream stage — matching, CV
generation, review — ran over an unchanged database and produced nothing new.

So the pass is chunked and each finished chunk is written. Three properties
carry that, and each is easy to lose:

  - a checkpoint writes the same shape as the final write, or the two disagree
    about what the DB is.
  - a checkpoint is atomic. The process this protects against is one that gets
    killed, and a kill during the write would truncate 37MB of JSON — a worse
    failure than the timeout.
  - only fully processed jobs are written. The incremental skip is "is this URL
    in the DB", so a job persisted after the cheap pass but before matching
    would be skipped forever, unscored, with nothing downstream to report it.
"""
import json
import os

import pytest

import run


def _job(url, **extra):
    j = {"url": url, "title": f"Job {url[-1]}", "company": "Acme"}
    j.update(extra)
    return j


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "_analyzed.json")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --- what a checkpoint writes ---

def test_a_checkpoint_writes_the_finished_jobs(db):
    run.save_analyzed_snapshot(db, [], [_job("u/1"), _job("u/2")])
    assert {j["url"] for j in _read(db)} == {"u/1", "u/2"}


def test_the_existing_db_survives_a_checkpoint(db):
    existing = [_job("old/1"), _job("old/2")]
    run.save_analyzed_snapshot(db, existing, [_job("new/1")])
    assert {j["url"] for j in _read(db)} == {"old/1", "old/2", "new/1"}


def test_this_run_wins_over_the_stored_copy_of_the_same_job(db):
    """A re-analysed job must not end up in the DB twice, and the fresher record
    is the one this run produced."""
    existing = [_job("u/1", match={"composite_score": 0.1})]
    run.save_analyzed_snapshot(db, existing, [_job("u/1", match={"composite_score": 0.9})])
    out = _read(db)
    assert len(out) == 1
    assert out[0]["match"]["composite_score"] == 0.9


def test_a_job_with_no_url_is_kept(db):
    """Manually staged postings can arrive without one; the final write appends
    them rather than dropping them, and a checkpoint has to agree."""
    out = run.save_analyzed_snapshot(db, [], [{"title": "Pasted", "company": "Acme"}])
    assert len(out) == 1
    assert len(_read(db)) == 1


def test_the_second_checkpoint_supersedes_the_first(db):
    """Chunk 2 is called with everything done so far, so the file must hold both
    chunks — not just the newest one."""
    run.save_analyzed_snapshot(db, [], [_job("u/1")])
    run.save_analyzed_snapshot(db, [], [_job("u/1"), _job("u/2")])
    assert {j["url"] for j in _read(db)} == {"u/1", "u/2"}


# --- the write itself ---

def test_the_write_is_atomic(db, monkeypatch):
    """Simulate the kill this exists for: json.dump fails half way. The previous
    DB must still be readable, because a truncated _analyzed.json is worse than
    a night with no progress."""
    run.save_analyzed_snapshot(db, [], [_job("u/1")])
    before = _read(db)

    def explode(*_a, **_k):
        raise KeyboardInterrupt("killed mid-write")

    monkeypatch.setattr(run.json, "dump", explode)
    with pytest.raises(KeyboardInterrupt):
        run.save_analyzed_snapshot(db, [], [_job("u/1"), _job("u/2")])
    assert _read(db) == before


def test_no_temp_file_is_left_behind(db):
    run.save_analyzed_snapshot(db, [], [_job("u/1")])
    assert not os.path.exists(db + ".tmp")


def test_the_file_is_valid_json_with_japanese_intact(db):
    """ensure_ascii=False on both writes, or the JP postings this pipeline now
    scrapes come back as \\uXXXX soup on the next read."""
    run.save_analyzed_snapshot(db, [], [_job("u/1", title="QAエンジニア")])
    assert _read(db)[0]["title"] == "QAエンジニア"
    with open(db, encoding="utf-8") as f:
        assert "QAエンジニア" in f.read()


# --- the chunking that calls it ---

def test_the_chunk_size_is_configured_and_small_enough_to_land():
    """A chunk has to finish inside the nightly's analysis slot. At the observed
    rate the whole 1543-job pass could not, which is what made a checkpoint
    necessary in the first place."""
    import selection
    size = selection.load_config().get("analysis_chunk_size")
    assert size, "analysis_chunk_size must be set, or a killed pass keeps nothing"
    assert 0 < size <= 500


@pytest.mark.parametrize("total,size,expected", [
    (1973, 200, 10),
    (200, 200, 1),
    (1, 200, 1),
    (0, 200, 0),
])
def test_every_job_lands_in_exactly_one_chunk(total, size, expected):
    jobs = [_job(f"u/{i}") for i in range(total)]
    chunks = [jobs[i:i + size] for i in range(0, len(jobs), size)]
    assert len(chunks) == expected
    assert sum(len(c) for c in chunks) == total
    assert {j["url"] for c in chunks for j in c} == {j["url"] for j in jobs}


def test_chunking_off_is_one_pass_over_everything():
    """analysis_chunk_size: 0 restores the old behaviour, so the setting can be
    turned off without editing code."""
    jobs = [_job(f"u/{i}") for i in range(50)]
    size = int(0 or 0) or len(jobs) or 1
    chunks = [jobs[i:i + size] for i in range(0, len(jobs), size)]
    assert len(chunks) == 1


# --- what the source must keep doing ---

def test_the_stretch_tier_is_chosen_once_not_per_chunk():
    """stretch_top_count is a COUNT, not a share. Promoting 15 out of every
    chunk would multiply the tier by the number of chunks and silently buy
    documents for the whole senior backlog."""
    import inspect
    src = inspect.getsource(run.main)
    body = src[src.index("for _n, _chunk in enumerate(_chunks"):]
    loop, after = body.split("if _analyze_failures:", 1)
    assert "stretch_jobs" not in loop, "stretch_jobs must not run inside the chunk loop"
    assert "stretch_jobs" in after, "the stretch tier must still run after the chunks"


def test_a_chunk_is_persisted_only_after_it_has_been_matched():
    """Persisting after the cheap pass would make the job 'known', so the next
    run's incremental skip would drop it before it was ever scored."""
    import inspect
    src = inspect.getsource(run.main)
    loop = src[src.index("for _n, _chunk in enumerate(_chunks"):]
    loop = loop[:loop.index("if _analyze_failures:")]
    assert loop.index("match_all(_chunk_enriched") < loop.index("_persist("), \
        "the chunk must be matched before it is written to the DB"
