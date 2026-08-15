#!/usr/bin/env python3
"""Stamp `*_at: YYYY-MM-DD` onto match reports when a flag is ticked.

Generalisation of stamp_applied_at.py — works for ALL hand-maintained boolean
flags on match reports:

  applied            → applied_at
  screening_passed   → screening_passed_at
  interview_passed   → interview_passed_at

And their failure counterparts (if you track them):
  screening_failed   → screening_failed_at
  interview_failed   → interview_failed_at

Obsidian's property editor toggles the boolean to true; this script finds
reports that are ticked but carry no `*_at` yet and records the date they
were ticked.

Date source: the report file's modification time (mtime). Because
`regen_match_report` skips applied/expired reports via gen_version's lock
(once applied, "the files on disk ARE the record of what was submitted"), a
ticked report's mtime stays fixed at the moment it was marked, so mtime is
the most trustworthy available proxy for the check date. Reports whose mtime
predates this feature are backfilled from that same mtime.

Idempotent: a report with `*_at` already set is never rewritten, so a
`false → true → false → true` cycle cannot rewrite the original date.

Usage:
    python3 stamp_flags_at.py             # dry run (all flags)
    python3 stamp_flags_at.py --apply     # write *_at for all flags
    python3 stamp_flags_at.py --apply --flag screening_passed  # one flag only
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MATCH_DIR = ROOT / "10_output" / "00_matches"

# flag_name → date_property
FLAG_DATE_MAP = {
    "applied": "applied_at",
    "screening_passed": "screening_passed_at",
    "interview_passed": "interview_passed_at",
    "screening_failed": "screening_failed_at",
    "interview_failed": "interview_failed_at",
}


def parse_frontmatter(text: str) -> dict:
    m = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


def is_flag_set(path: Path, flag: str) -> bool:
    """True when the report's flag checkbox is ticked (true)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    fm = parse_frontmatter(text)
    return str(fm.get(flag, "")).lower() == "true"


def _date_from_mtime(path: Path) -> str:
    import datetime
    ts = path.stat().st_mtime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def stamp_flag_at(path: Path, flag: str, date_prop: str, apply: bool) -> str | None:
    """Add date_prop to frontmatter. Returns the date if changed, None otherwise."""
    text = path.read_text(encoding="utf-8")
    fm_m = re.match(r"\A(---\n)(.*?)(\n---\n)", text, flags=re.DOTALL)
    if not fm_m:
        return None
    head, body, tail = fm_m.group(1), fm_m.group(2), fm_m.group(3)
    if re.search(rf"^{date_prop}:.*$", body, flags=re.MULTILINE):
        return None  # already stamped
    date = _date_from_mtime(path)
    new_body = body.rstrip("\n") + f"\n{date_prop}: {date}\n"
    if apply:
        path.write_text(head + new_body + tail, encoding="utf-8")
    return date


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--flag", default=None, choices=list(FLAG_DATE_MAP.keys()),
                    help="stamp only this flag (default: all flags)")
    args = ap.parse_args()

    if not MATCH_DIR.exists():
        print(f"no such directory: {MATCH_DIR}")
        return 1

    flags_to_process = {args.flag: FLAG_DATE_MAP[args.flag]} if args.flag else FLAG_DATE_MAP
    files = sorted(MATCH_DIR.glob("*.md"))

    summary = {}
    for flag, date_prop in flags_to_process.items():
        stamped, already, skipped = 0, 0, 0
        for f in files:
            if not is_flag_set(f, flag):
                skipped += 1
                continue
            text = f.read_text(encoding="utf-8")
            if re.search(rf"^{date_prop}:.*$", text, re.MULTILINE):
                already += 1
                continue
            date = stamp_flag_at(f, flag, date_prop, args.apply)
            if date:
                print(f"  {f.name}: {date_prop} = {date}" + ("" if args.apply else " (dry run)"))
                stamped += 1
        summary[flag] = (stamped, already, skipped)

    print()
    for flag, (stamped, already, skipped) in summary.items():
        print(f"{flag}: stamped={stamped} already={already} not_set={skipped} apply={args.apply}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
