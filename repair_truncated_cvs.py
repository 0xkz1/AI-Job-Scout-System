"""Restore the cut-off project bullets in CVs already on disk.

cv_generator now repairs a truncated model reply before the CV is written (see
_repair_truncated_entries), but 43 of the CVs in 10_output/10_cvs were written
before that and still carry a sentence that stops mid-word. They do not look
broken: the reply stopped mid-bullet, the body came out short, and the padding
pass filled the page with whole entries rendered from source — so the file is
full-length and correctly formatted, with one bullet in the middle that ends
after two words.

No model is called. The prose was never the model's to write — the experience
prompt asks it to select and order projects and forbids modifying their
descriptions — so the repair is a re-render from career/cv/projects/*.md, which
is where the sentence came from in the first place.

Restoring a bullet makes the CV longer, so the two-page budget is re-applied
afterwards through cv_generator's own trimmer rather than a second copy of that
arithmetic here.

Locked CVs are left alone. `applied` means the file on disk IS the record of
what was submitted, `expired` and a hand edit mean the same as everywhere else —
gen_version.lock_reason decides, not this script.

    python3 repair_truncated_cvs.py --dry-run
    python3 repair_truncated_cvs.py
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import cv_generator as cg  # noqa: E402
import gen_version  # noqa: E402

CVS = ROOT / "10_output" / "10_cvs"
MATCHES = ROOT / "10_output" / "00_matches"

SECTION = re.compile(r"(## SELECTED PROJECTS\n)(.*?)(?=\n## |\Z)", re.DOTALL)
# The breadth line is rebuilt from whatever is not written up, so it has to come
# off before the entries are touched and go back on after.
OTHER_LINE = re.compile(r"^\*\*(?:Other projects|その他のプロジェクト):\*\*.*$",
                        re.MULTILINE)


def repair_text(text: str) -> str | None:
    """The CV with its cut-off bullets restored, or None if there were none."""
    match = SECTION.search(text)
    if not match:
        return None
    section = match.group(2)
    entries_text = OTHER_LINE.sub("", section).strip()
    if not any(cg._bullet_is_unfinished(l) for l in entries_text.split("\n")):
        return None

    repaired = cg._repair_truncated_entries(entries_text)
    if not repaired.strip():
        return None  # nothing identifiable to restore; leave it for a human

    def rebuilt(body: str) -> str:
        return text[:match.start(2)] + cg._finish_experience(body) + "\n" + text[match.end(2):]

    out = rebuilt(repaired)
    # Restoring a sentence adds words. Same ceiling and same trimmer the
    # generator uses, measured the same way: on the whole CV, because only the
    # write-ups are elastic.
    # The ceiling is headroom, not the spill point: cv_generator measured 1145
    # words still landing on two pages and 1159 spilling. One trim pass is what
    # the generator does, so a repair that lands a few words over the target
    # still fits — and matching the generator matters more than the last word.
    body_words = len(out.split("---", 2)[-1].split())
    excess = body_words - cg._CV_MAX_WORDS
    if excess > 0:
        trimmed = cg._trim_experience_body(repaired, excess)
        if trimmed != repaired:
            out = rebuilt(trimmed)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    fixed, locked, unidentifiable = [], [], []
    for path in sorted(CVS.glob("*_CV.md")):
        text = path.read_text(encoding="utf-8")
        section = SECTION.search(text)
        if not section:
            continue
        body = OTHER_LINE.sub("", section.group(2))
        if not any(cg._bullet_is_unfinished(l) for l in body.split("\n")):
            continue

        base = path.name[: -len("_CV.md")]
        reason = gen_version.lock_reason(base, text, MATCHES)
        if reason:
            locked.append((base, reason))
            continue

        out = repair_text(text)
        if out is None:
            unidentifiable.append(base)
            continue
        fixed.append(base)
        if not args.dry_run:
            path.write_text(out, encoding="utf-8")
        if args.limit and len(fixed) >= args.limit:
            break

    for base in fixed:
        print(f"  {'would fix' if args.dry_run else 'fixed'}  {base}")
    for base, reason in locked:
        print(f"  left ({reason})  {base}")
    for base in unidentifiable:
        print(f"  left (no source entry to restore from)  {base}")
    print(f"\n{len(fixed)} repaired, {len(locked)} locked, "
          f"{len(unidentifiable)} left for a human")
    if args.dry_run:
        print("dry run — nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
