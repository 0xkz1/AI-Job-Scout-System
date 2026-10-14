"""Surgically rewrite ONLY the `## EXPERIENCE` (employment) block of existing
CVs, in place, without touching anything else.

Why this instead of regen_top_docs.py: the employment section is fully
deterministic — it is `_bold_experience_titles(get_employment_section(role))`
with no LLM involved — so a change to its ordering / field layout (see
career/cv/projects/*.md, cv_generator._period_end_key) can be applied by
splicing the freshly-computed block between the CV's `## EXPERIENCE` and
`## SELECTED PROJECTS` headings. The LLM-authored SELECTED PROJECTS section,
the cover letters, and every other line are left byte-for-byte untouched.

Scope: only current-format CVs (those that HAVE both `## EXPERIENCE` and
`## SELECTED PROJECTS` markdown headings). Older-template CVs that lack a
separate employment section are skipped — they never contained this block.

Role per CV is read from its `source_profile:` frontmatter, so a
camera_assistant CV correctly keeps its extra tagged entry, etc.

Usage:
  .venv/bin/python3 patch_experience_section.py            # dry-run (default)
  .venv/bin/python3 patch_experience_section.py --write     # actually write
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from cv_generator import get_employment_section, _bold_experience_titles  # noqa: E402
import gen_version  # noqa: E402

CV_DIR = ROOT / "10_output" / "10_cvs"
MATCH_DIR = ROOT / "10_output" / "00_matches"

# Splice target: the text between the EXPERIENCE heading and the next section
# heading (SELECTED PROJECTS). Captures the two anchors so they are preserved
# exactly; only the middle is replaced.
_SECTION_RE = re.compile(
    r"(^## EXPERIENCE[ \t]*\n)(.*?)(\n## SELECTED PROJECTS)",
    re.DOTALL | re.MULTILINE,
)
_PROFILE_RE = re.compile(r'^source_profile:\s*"?\[\[career/cv/profile/([^\]"]+)\]\]"?',
                         re.MULTILINE)
# Old header carried the studio label inline ("## SELECTED PROJECTS — Taifunomé
# (Independent Studio, 2023 – Present)"); now that Taifunomé is a first-class
# EXPERIENCE entry, that suffix is redundant. Strip it back to the bare header.
_OLD_PROJECTS_HEADER_RE = re.compile(
    r"^## SELECTED PROJECTS —[^\n]*", re.MULTILINE)


def _role_of(text: str) -> str:
    m = _PROFILE_RE.search(text)
    return m.group(1) if m else "general"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="write changes (default is a read-only dry-run)")
    ap.add_argument("--dir", default=str(CV_DIR),
                    help="directory of *_CV.md to patch (default: 10_output/10_cvs; "
                         "pass 10_output/31_emails_cvs for the email-outreach CVs)")
    args = ap.parse_args()
    cv_dir = Path(args.dir)

    changed = skipped_nomatch = unchanged = locked = 0
    for f in sorted(cv_dir.glob("*_CV.md")):
        text = f.read_text(encoding="utf-8")
        if gen_version.is_locked(f.stem[:-3], text, MATCH_DIR):
            locked += 1
            continue
        m = _SECTION_RE.search(text)
        if not m:
            skipped_nomatch += 1
            continue
        role = _role_of(text)
        new_block = _bold_experience_titles(get_employment_section(role))
        new_text = text[:m.start(2)] + new_block + text[m.end(2):]
        # Normalise the now-redundant projects header ("— Taifunomé …") too.
        new_text = _OLD_PROJECTS_HEADER_RE.sub("## SELECTED PROJECTS", new_text)
        if new_text == text:
            unchanged += 1
            continue
        changed += 1
        if args.write:
            f.write_text(new_text, encoding="utf-8")
        else:
            print(f"  would patch: {f.name}  [{role}]")

    verb = "patched" if args.write else "would patch"
    print(f"\n{verb}: {changed}  |  既に最新: {unchanged}  |  "
          f"対象外(職歴セクション無し): {skipped_nomatch}  |  ロック済み: {locked}")
    if not args.write and changed:
        print("dry-run — 反映するには --write を付けて再実行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
