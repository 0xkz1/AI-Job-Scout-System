"""A fingerprint of everything that shapes a generated CV/CL pair.

Every spec change used to force rebuilding all selected documents, even the ones
already made under the current rules. Stamping each pair with a fingerprint of
its generation inputs lets a rebuild skip whatever is already current, so tuning
on a small sample and then scaling up costs only the genuinely stale documents.

Two kinds of input feed the fingerprint:

  * Data files — persona (ethos/about/profile), the project records, skills, and
    the per-role cover-letter template. These change often; hashing their bytes
    picks that up automatically.
  * Generation logic — the opening-hook prompt, the fabrication gate, the
    projects-digest shape. Code, not data, so a hand-bumped GEN_SPEC_VERSION
    stands in for it: bump the constant whenever that logic changes.

The fingerprint is role-scoped: it folds in only the template for the pair's own
role, so editing one role's template invalidates just that role's documents, not
all of them. Global inputs (persona, projects) still invalidate everything, which
is correct — they really do affect every letter.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROFILE_DIR = Path("/media/kz003/atelier/00_Kazuki")
CV_ROOT = PROFILE_DIR / "career" / "cv"
TEMPLATE_DIR = PROFILE_DIR / "career" / "cover-letter"

# Bump when generation LOGIC changes (prompt wording, a gate rule, the digest
# shape) — anything not captured by hashing the data files below. Keep a short
# note so the reason for each bump is legible.
# NOTE on role-detection changes: they do NOT need a version bump. The
# fingerprint already folds in the pair's own role template, and --stale-only
# checks against the role detect_role_type returns NOW — so if a fix reassigns a
# job to a different role, that pair's fingerprint changes on its own and only
# it rebuilds. Bump this only for logic that the data-file hashes cannot see
# (prompt wording, a gate rule, the digest shape).
GEN_SPEC_VERSION = "2026-07-24.1"  # salvage over-long but honest openings instead of falling back to template

# Data files whose CONTENT feeds every pair, regardless of role.
_GLOBAL_FILES = [
    PROFILE_DIR / "ethos.md",
    PROFILE_DIR / "about.md",
    PROFILE_DIR / "profile.md",
    PROFILE_DIR / "interests.md",
    PROFILE_DIR / "skills.md",
]
_GLOBAL_DIRS = [CV_ROOT / "projects", CV_ROOT / "skill-toolkit"]


def _hash_file(h, path: Path) -> None:
    try:
        h.update(path.read_bytes())
    except Exception:
        h.update(b"\0")  # missing file is itself a state worth fingerprinting


def _global_digest(h) -> None:
    for f in _GLOBAL_FILES:
        _hash_file(h, f)
    for d in _GLOBAL_DIRS:
        if d.exists():
            for f in sorted(d.glob("*.md")):
                _hash_file(h, f)


def fingerprint(role_type: str = "general") -> str:
    """Short fingerprint of the generation inputs for a pair of the given role."""
    h = hashlib.sha256()
    h.update(GEN_SPEC_VERSION.encode())
    _global_digest(h)
    _hash_file(h, TEMPLATE_DIR / f"{role_type}.md")
    return h.hexdigest()[:10]


def stamp_line(role_type: str = "general") -> str:
    """The frontmatter line to write into a generated doc."""
    return f'gen_fingerprint: "{fingerprint(role_type)}"'


def read_fingerprint(text: str) -> str | None:
    """Extract a stamped fingerprint from a document's frontmatter, if present."""
    import re
    m = re.search(r'^gen_fingerprint:\s*"?([0-9a-f]+)"?', text, re.MULTILINE)
    return m.group(1) if m else None


def is_current(text: str, role_type: str = "general") -> bool:
    """True when the document was generated under the current inputs."""
    return read_fingerprint(text) == fingerprint(role_type)
