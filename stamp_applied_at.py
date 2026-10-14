#!/usr/bin/env python3
"""Stamp `applied_at: YYYY-MM-DD` onto match reports when Applied is ticked.

Obsidian's property editor toggles `applied` to true; this script finds
reports that are applied (applied: true) but carry no `applied_at` yet and
records the date they were ticked.

Date source: the report file's modification time (mtime). Because
`regen_match_report` skips applied/expired reports via gen_version's lock
(once applied, "the files on disk ARE the record of what was submitted"),
a ticked report's mtime stays fixed at the moment it was marked applied, so
mtime is the most trustworthy available proxy for the check date. Applied
reports whose mtime predates this feature are backfilled from that same mtime.

Idempotent: a report with `applied_at` already set is never rewritten, so a
`false -> true -> false -> true` cycle cannot rewrite the original date.

Usage:
    python3 stamp_applied_at.py          # dry run
    python3 stamp_applied_at.py --apply  # write applied_at
"""
import argparse
import re
import sys
from pathlib import Path
from doc_paths import md_files

ROOT = Path(__file__).resolve().parent
MATCH_DIR = ROOT / "10_output" / "00_matches"


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


def is_applied(path: Path) -> bool:
    """True when the report's applied checkbox is ticked (true, not 'true')."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    fm = parse_frontmatter(text)
    return str(fm.get("applied", "")).lower() == "true"


def stamp_applied_at(path: Path, apply: bool) -> bool:
    """Add/replace applied_at in frontmatter. Returns True if text changed."""
    text = path.read_text(encoding="utf-8")
    fm_m = re.match(r"\A(---\n)(.*?)(\n---\n)", text, flags=re.DOTALL)
    if not fm_m:
        return False
    head, body, tail = fm_m.group(1), fm_m.group(2), fm_m.group(3)
    if re.search(r"^applied_at:.*$", body, flags=re.MULTILINE):
        return False  # already stamped
    # date from mtime (the applied-check date, frozen by the regen lock)
    date = _date_from_mtime(path)
    new_body = body.rstrip("\n") + f"\napplied_at: {date}\n"
    if not apply:
        return True
    path.write_text(head + new_body + tail, encoding="utf-8")
    return True


def _date_from_mtime(path: Path) -> str:
    import datetime
    ts = path.stat().st_mtime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    if not MATCH_DIR.exists():
        print(f"no such directory: {MATCH_DIR}")
        return 1

    files = md_files(MATCH_DIR)
    stamped, already, skipped = 0, 0, 0
    for f in files:
        if not is_applied(f):
            skipped += 1
            continue
        if re.search(r"^applied_at:.*$", f.read_text(encoding="utf-8"), flags=re.MULTILINE):
            already += 1
            continue
        if stamp_applied_at(f, args.apply):
            date = _date_from_mtime(f)
            print(f"  {f.name}: applied_at = {date}" + ("" if args.apply else " (dry run)"))
            stamped += 1

    print(f"applied={len(files)} stamped={stamped} already={already} not_applied={skipped} apply={args.apply}")
    return 0


def parse_applied_at(text: str) -> str | None:
    m = re.search(r"^applied_at:\s*(\S+)", text, flags=re.MULTILINE)
    return m.group(1) if m else None


if __name__ == "__main__":
    sys.exit(main())