"""The two-page budget, and what gives when a CV will not fit inside it.

A CV that spills onto a third page is not a longer CV, it is a broken one — the
reader gets a page carrying four lines. cv_generator pads a short body and trims
a long one; these cover the trimming side, which had a floor it could not get
under.
"""
def test_trimmer_drops_bullets_once_it_hits_the_entry_floor():
    """Dropping whole write-ups stops at _CV_MIN_ENTRIES, and before this the
    CV simply shipped long — 1188 words against a 1120 ceiling, measured
    2026-08-18. Below the floor the unit of removal has to get finer."""
    import cv_generator as g
    body = (
        "**A | Role | 2026**\n• one alpha\n• two beta\n• three gamma\n\n"
        "**B | Role | 2025**\n• one delta\n• two epsilon\n\n"
        "**C | Role | 2024**\n• one zeta\n• two eta"
    )
    before = len(body.split())
    out = g._trim_experience_body(body, excess_words=8, min_entries=3)
    assert len(out.split()) < before, "hit the floor and gave up"
    assert out.count("**") == 6, "all three write-ups must survive"


def test_trimmer_never_touches_the_first_entry():
    """gen_version pins TAIFUNOME as the first write-up on every CV; trimming
    its bullets would quietly undo that."""
    import cv_generator as g
    body = (
        "**A | Role | 2026**\n• one alpha\n• two beta\n• three gamma\n\n"
        "**B | Role | 2025**\n• one delta\n• two epsilon"
    )
    out = g._trim_experience_body(body, excess_words=999, min_entries=2)
    for kept in ("one alpha", "two beta", "three gamma"):
        assert kept in out, f"first entry lost {kept!r}"


def test_every_entry_keeps_at_least_one_bullet():
    """A title line with nothing under it reads as a project someone forgot to
    describe — worse than not writing it up at all."""
    import cv_generator as g
    body = (
        "**A | Role | 2026**\n• one alpha\n\n"
        "**B | Role | 2025**\n• one delta\n• two epsilon\n\n"
        "**C | Role | 2024**\n• one zeta\n• two eta\n• three theta"
    )
    out = g._trim_experience_body(body, excess_words=999, min_entries=3)
    for block in out.split("\n\n"):
        assert block.count("•") >= 1, f"entry stripped bare: {block!r}"
