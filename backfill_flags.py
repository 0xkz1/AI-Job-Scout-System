#!/usr/bin/env python3
"""Backfill screening_passed / interview_passed flags onto existing match reports.

Adds the new boolean flags to the frontmatter of every report that doesn't
have them yet. Existing reports written before these flags existed render no
checkbox in Obsidian for them; this script inserts the defaults (false) right
after the `applied:` line, matching the position generate_match_report emits.

Idempotent: a report that already has the flag is skipped.

Usage:
    python3 backfill_flags.py             # dry run
    python3 backfill_flags.py --apply     # write flags
"""
import argparse
import re
import sys
from pathlib import Path
from doc_paths import md_files

ROOT = Path(__file__).resolve().parent
MATCH_DIR = ROOT / "10_output" / "00_matches"

NEW_FLAGS = [
    ("screening_passed", "false"),
    ("interview_passed", "false"),
]

# Insert new flags right after the `applied:` line
FLAG_LINE_RE = re.compile(r"^(applied:\s*\S+\s*$)", re.MULTILINE)


def backfill_one(path: Path, apply: bool) -> str | None:
    """Insert missing flags. Returns a description string, or None if no change."""
    text = path.read_text(encoding="utf-8")
    fm_m = re.match(r"\A---\n(.*?)\n---", text, re.DOTALL)
    if not fm_m:
        return None

    body = fm_m.group(1)
    additions = []
    for flag, default in NEW_FLAGS:
        if not re.search(rf"^{flag}:\s*\S+", body, re.MULTILINE):
            additions.append(f"{flag}: {default}")

    if not additions:
        return None

    # Insert after the `applied:` line
    insert_block = "\n" + "\n".join(additions)

    def _replace(m):
        return m.group(1) + insert_block

    new_text = FLAG_LINE_RE.sub(_replace, text, count=1)
    if apply:
        path.write_text(new_text, encoding="utf-8")
    return ", ".join(a.split(":")[0] for a in additions)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    if not MATCH_DIR.exists():
        print(f"no such directory: {MATCH_DIR}")
        return 1

    files = md_files(MATCH_DIR)
    backfilled, already, skipped = 0, 0, 0

    for f in files:
        result = backfill_one(f, args.apply)
        if result is None:
            # check if it already had all flags
            text = f.read_text(encoding="utf-8")
            fm_m = re.match(r"\A---\n(.*?)\n---", text, re.DOTALL)
            if fm_m and all(re.search(rf"^{flag}:", fm_m.group(1), re.MULTILINE) for flag, _ in NEW_FLAGS):
                already += 1
            else:
                skipped += 1
        else:
            print(f"  {f.name}: + {result}" + ("" if args.apply else " (dry run)"))
            backfilled += 1

    print(f"\nbackfilled={backfilled} already_present={already} skipped={skipped} apply={args.apply}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
