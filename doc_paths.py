"""Listing the markdown in a directory, without the copies Syncthing left there.

Every directory this repository reads — 10_output/00_matches, 10_output/10_cvs,
career/cv/projects, 00_saved/email-targets — lives inside a Syncthing folder
shared with a Mac, a second Ubuntu box, a phone and an iPad. When two devices
touch the same file between syncs, Syncthing keeps both: the loser is renamed
to `<stem>.sync-conflict-<date>-<device><suffix>` and left beside the winner.

For the patterns that name a document kind that is harmless — a CV conflict is
`X_CV.sync-conflict-....md`, which `*_CV.md` does not match. `glob("*.md")` has
no such protection, and twelve conflict copies had accumulated in the vault by
2026-09-04. Four of them sat in 00_matches, where every caller below reads a
directory listing as "the postings": check_expired.py was spending a live HTTP
request on each one, run.py counted them in its archive sweep, and the frontmatter
stampers wrote flags into files nothing would ever read again.

Filtering at each call site would mean twenty copies of the same substring test,
which is the second-source-of-truth failure the rest of this codebase keeps
finding the hard way. So it is one function, and the rule lives in one place.

Deliberately NOT deleting anything: a conflict copy is the only surviving record
of what the other device had, and deciding which side wins is a judgement about
content, not a listing concern.
"""
from __future__ import annotations

from pathlib import Path

# Syncthing's own marker, from its docs: the loser of a conflict is renamed with
# `.sync-conflict-<YYYYMMDD>-<HHMMSS>-<device-id-prefix>` inserted before the
# extension. Matching the literal is enough — nothing else in the vault carries
# it, and a date-shaped regex would only fail differently if the format changed.
CONFLICT_MARKER = ".sync-conflict-"


def is_conflict_copy(path: Path) -> bool:
    """True for a file Syncthing set aside as the losing side of a conflict."""
    return CONFLICT_MARKER in path.name


def md_files(directory: Path, pattern: str = "*.md", *,
             recursive: bool = False) -> list[Path]:
    """Sorted markdown in `directory`, minus Syncthing conflict copies.

    Sorted because several callers stamp or renumber in listing order, and an
    unsorted glob makes that order depend on the filesystem. Missing directories
    return empty rather than raising: a caller reading an output directory that
    has not been generated yet wants "nothing there", not a traceback.
    """
    if not directory.is_dir():
        return []
    found = directory.rglob(pattern) if recursive else directory.glob(pattern)
    return sorted(p for p in found if p.is_file() and not is_conflict_copy(p))
