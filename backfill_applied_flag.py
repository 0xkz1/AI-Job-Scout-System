"""One-off: give every existing match report the `applied` checkbox.

generate_match_report now emits `applied: true|false` beside `expired:`, so a
report written from now on renders a checkbox in Obsidian's property editor.
The 1492 reports already on disk predate that: only the 9 a human had added the
property to by hand carry it, and the rest show no checkbox at all until the
next rescrape happens to rewrite them.

This inserts the missing line and nothing else. It is a pure addition:

  * a report that already has `applied:` is left byte-for-byte alone, so the 7
    ticked ones cannot be reset by running this;
  * the line goes directly after `expired:`, matching where the generator puts
    it, so a later regeneration produces an identical file rather than a diff;
  * a report without frontmatter, or without `expired:`, is skipped and
    counted rather than guessed at.

Run with --apply to write. Without it, prints what would change.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MATCH_DIR = ROOT / "10_output" / "00_matches"
BACKUP_DIR = ROOT / "10_output"

FM_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)


def patch(text: str) -> str | None:
    """The report with `applied: false` inserted after `expired:`, or None when
    there is nothing to do (already present, or no frontmatter to put it in)."""
    m = FM_RE.match(text)
    if not m:
        return None
    fm = m.group(1)
    if re.search(r"^applied:", fm, re.MULTILINE):
        return None  # already has it — never touch a tick that is already set
    if not re.search(r"^expired:", fm, re.MULTILINE):
        return None  # no anchor; the generator will add both on next write
    new_fm = re.sub(r"^(expired:.*)$", r"\1\napplied: false", fm, count=1, flags=re.MULTILINE)
    return f"---\n{new_fm}---\n" + text[m.end():]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    if not MATCH_DIR.exists():
        print(f"no such directory: {MATCH_DIR}")
        return 1

    files = sorted(MATCH_DIR.glob("*.md"))
    todo = []
    already = no_anchor = 0
    for f in files:
        text = f.read_text(encoding="utf-8")
        out = patch(text)
        if out is None:
            m = FM_RE.match(text)
            if m and re.search(r"^applied:", m.group(1), re.MULTILINE):
                already += 1
            else:
                no_anchor += 1
            continue
        todo.append((f, out))

    print(f"reports: {len(files)}  |  would add: {len(todo)}  |  "
          f"already had applied: {already}  |  skipped (no frontmatter/expired): {no_anchor}")

    if not args.apply:
        for f, _ in todo[:5]:
            print(f"  e.g. {f.name}")
        print("dry run — nothing written. Re-run with --apply.")
        return 0

    # 10_output is gitignored, so there is no VCS to undo this. Snapshot first.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = BACKUP_DIR / f".matches_backup_pre_applied_{stamp}.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(MATCH_DIR, arcname=MATCH_DIR.name)
    print(f"backup: {archive.name}")

    for f, out in todo:
        f.write_text(out, encoding="utf-8")
    print(f"patched {len(todo)} reports")
    return 0


if __name__ == "__main__":
    sys.exit(main())
