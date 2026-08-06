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
# NOTE: page count is a RENDERING property, not a generation one. It is fixed in
# app.py's PDF CSS (the page margin), and _convert_pdf_versioned already hashes
# that function's source — so a layout fix needs no bump here. Measured
# 2026-08-01: at the old 13mm margin 9 of 15 CVs ran to three pages; at 10mm
# none do.
GEN_SPEC_VERSION = "2026-08-02.1"  # letter head: no company in the salutation, no county in the address, date moved to render time

# Data files whose CONTENT feeds every pair, regardless of role.
_GLOBAL_FILES = [
    PROFILE_DIR / "ethos.md",
    PROFILE_DIR / "about.md",
    PROFILE_DIR / "profile.md",
    PROFILE_DIR / "interests.md",
    PROFILE_DIR / "skills.md",
]
# "experience" holds the employment records, which used to sit in "projects".
# It must be listed: an employment entry edited outside this list changes every
# CV while leaving every fingerprint identical, so nothing rebuilds and the
# stale documents keep reporting themselves as current.
_GLOBAL_DIRS = [CV_ROOT / "projects", CV_ROOT / "experience", CV_ROOT / "skill-toolkit"]


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


def role_of(text: str) -> str:
    """The role a generated doc was built for, read from its own frontmatter.

    A CV names its profile (`source_profile`), a cover letter its template
    (`source_template`); both end in the role name. Falls back to "general",
    which is what generation itself falls back to.
    """
    import re
    m = re.search(r'^source_(?:profile|template):\s*"?\[\[[^\]]*?([\w-]+)\]\]',
                  text, re.MULTILINE)
    return m.group(1) if m else "general"


# ---------------------------------------------------------------------------
# Staleness: is this document's BODY built to the current shape?
#
# The fingerprint answers this exactly, but only for documents that carry one —
# and 489 of 554 CVs predate stamping. Most of them are fine: patch scripts
# (patch_toolkit_lines, patch_add_project_urls) rewrite bodies in place without
# stamping, so "unstamped" says nothing either way. Silently treating them as
# current is what let a three-page, pre-taifunome CV render as a finished PDF on
# 2026-08-06; refusing all 489 would block half the corpus over a missing line.
#
# So an unstamped CV falls back to reading its own structure. Each marker below
# is one shape change, named with the commit that made it, and the check is
# deliberately shallow: it looks only at things generation ALWAYS produces, so a
# per-job difference (which projects were picked, how many write-ups fit the two
# pages) never reads as staleness. Add a marker here when the CV shape changes.
# ---------------------------------------------------------------------------

_HEADER_RE = r'^# .+\n\*\*.+\*\*\n(.+)$'
_PROJECTS_RE = r'^## SELECTED PROJECTS\n(.*?)(?=^## |\Z)'


def _cv_shape_faults(text: str) -> list[str]:
    """Shape changes this CV body predates, newest spec first. Empty when current."""
    import re
    faults = []

    # 029cd13: the header lost its second line (role_tagline), so the line under
    # the job title is the contact line and nothing else.
    m = re.search(_HEADER_RE, text, re.MULTILINE)
    if m and not m.group(1).lstrip().startswith(("Edinburgh", "[")):
        faults.append("header still carries the retired role_tagline line")

    body = re.search(_PROJECTS_RE, text, re.MULTILINE | re.DOTALL)
    if not body:
        # No "## SELECTED PROJECTS" at all: the pre-heading generation, which
        # wrote plain-text section names and the filename as the H1.
        faults.append("no '## SELECTED PROJECTS' section (pre-heading generation)")
    else:
        writeups = [l for l in body.group(1).splitlines()
                    if l.startswith("**") and not l.startswith("**Other projects")]
        # e99bac4: TAIFUNOME leads the section on every CV — it is the studio the
        # candidate runs, and it was being demoted to the "other projects" line.
        if writeups and "TAIFUNOME" not in writeups[0]:
            faults.append("TAIFUNOME is not the first project write-up")

    # cfa29ad: EDUCATION and LANGUAGES merged into one section to win back the
    # space that was pushing CVs onto a third page.
    if "## EDUCATION & LANGUAGES" not in text:
        faults.append("EDUCATION and LANGUAGES are still separate sections")
    return faults


def staleness_reason(text: str, is_cv: bool = True) -> str | None:
    """Why this document's body is not built to the current spec, or None.

    Checked in the order the evidence is trustworthy: a fingerprint that
    disagrees is conclusive, an absent one sends a CV to its own structure, and
    an unstamped cover letter has no structure worth reading — its shape is one
    template, so there is nothing to compare against.
    """
    role = role_of(text)
    stamped = read_fingerprint(text)
    if stamped is not None:
        current = fingerprint(role)
        if stamped != current:
            return f"gen_fingerprint {stamped} != current {current} (role: {role})"
        return None
    if not is_cv:
        return None
    faults = _cv_shape_faults(text)
    if faults:
        return "no gen_fingerprint, and the body predates: " + "; ".join(faults)
    return None


# ---------------------------------------------------------------------------
# Locks: when a CV/CL must be left exactly as it is.
#
# Three reasons, in two scopes. The scope matters, because it decides whether a
# lock can fire before the document exists:
#
#   document-scoped  updated_by_hand  a human edited THIS file; a script must
#                                     not roll over their words.
#   job-scoped       applied          the job was applied to, so the files on
#                                     disk ARE the record of what was actually
#                                     submitted. They must stop moving even as
#                                     the profile / projects / templates do.
#   job-scoped       expired          the posting has closed. Regenerating or
#                                     reviewing it spends LLM budget on a job
#                                     that can no longer be applied to.
#
# The job-scoped ones hold whether or not a CV/CL is on disk yet — that is the
# point for `expired`: a closed posting must not receive a FIRST CV either.
# ---------------------------------------------------------------------------

# Spellings a human or Obsidian's Properties UI writes for a ticked checkbox.
# Matches matcher.read_expired_flag, which has read the `expired` tick this way
# since before these locks existed.
_TRUTHY = ("true", "yes", "on")


def _frontmatter_bool(text: str, key: str) -> bool:
    """True when frontmatter `key:` holds a ticked-checkbox value."""
    import re
    m = re.search(rf'^{key}:\s*(\S+)', text, re.MULTILINE)
    return bool(m) and m.group(1).strip().strip('"').lower() in _TRUTHY


def doc_lock_reason(doc_text: str | None) -> str | None:
    """Why this specific document is frozen, or None. Document-scoped only."""
    if doc_text and _frontmatter_bool(doc_text, "updated_by_hand"):
        return "hand-edited"
    return None


def job_lock_reason(base: str, match_dir: Path) -> str | None:
    """Why this JOB is frozen, or None — read from its match report.

    Independent of whether a CV/CL exists yet, so an expired posting is refused
    a first document as firmly as it is refused a rewrite.
    """
    report = match_dir / f"{base}.md"
    if not report.exists():
        return None
    try:
        fm = report.read_text(encoding="utf-8")
    except OSError:
        return None  # unreadable report is not evidence of a lock
    if _frontmatter_bool(fm, "applied"):
        return "applied"
    if _frontmatter_bool(fm, "expired"):
        return "expired"
    return None


def lock_reason(base: str, doc_text: str | None, match_dir: Path) -> str | None:
    """Why base's CV/CL must not be regenerated, patched, or reviewed."""
    return doc_lock_reason(doc_text) or job_lock_reason(base, match_dir)


def is_locked(base: str, doc_text: str | None, match_dir: Path) -> bool:
    """True when base's CV/CL must not be regenerated, patched, or reviewed."""
    return lock_reason(base, doc_text, match_dir) is not None


def pair_lock_reason(base: str, docs, match_dir: Path) -> str | None:
    """lock_reason for a CV/CL pair — a lock on either half freezes both.

    Rebuilding only the unlocked half is precisely the CV/CL drift the paired
    rebuild exists to prevent, so the pair moves together or not at all.
    `docs` are the pair's paths; ones not yet on disk are simply skipped, which
    still leaves the job-scoped locks to answer for them.
    """
    for p in docs:
        try:
            if p.exists():
                reason = doc_lock_reason(p.read_text(encoding="utf-8"))
                if reason:
                    return reason
        except OSError:
            continue
    return job_lock_reason(base, match_dir)
