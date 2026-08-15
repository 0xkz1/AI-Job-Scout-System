"""One-off: re-link match reports to the CV/CL that already exist on disk.

run.py derived a report's `cv:` / `cover_letter:` links from whether THAT PASS
generated the documents, not from whether they exist. So a job that fell out of
the generation set — its score drifting under the threshold, or the top-N%
boundary moving past it — had its links dropped on the next run while its CV and
CL sat on disk, reviewed and scored. Measured before this ran: 368 of 534
existing CVs and 386 CLs were orphaned in their own reports.

run.py now derives the links from file existence, so this cannot recur. This
repairs the reports already written that way. It is a pure addition:

  * only inserts a link whose target file actually exists;
  * never touches a report that already has the key, so a hand-corrected link
    cannot be overwritten;
  * inserts after `url:`, which is where generate_match_report puts them, so a
    later regeneration produces an identical file rather than a diff.

Run with --apply to write. Without it, prints what would change.
"""
from __future__ import annotations

import argparse
import re
import sys
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "10_output"
MATCH_DIR = OUT / "00_matches"
CV_DIR = OUT / "10_cvs"
CL_DIR = OUT / "10_cover-letters"

FM_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)


def patch(stem: str, text: str) -> tuple[str | None, list[str]]:
    """(new_text, keys added). new_text is None when nothing needs doing."""
    m = FM_RE.match(text)
    if not m:
        return None, []
    fm = m.group(1)
    if not re.search(r"^url:", fm, re.MULTILINE):
        return None, []  # no anchor to insert after

    # Later keys must stay after the links, so build the insert as one block and
    # place it directly after url: — the generator's own position.
    additions, added = [], []
    for key, directory, suffix in (("cv", CV_DIR, "_CV"),
                                   ("cover_letter", CL_DIR, "_CL")):
        if re.search(rf"^{key}:", fm, re.MULTILINE):
            continue
        if not (directory / f"{stem}{suffix}.md").exists():
            continue
        additions.append(f'{key}: "[[{stem}{suffix}]]"')
        added.append(key)
    if not additions:
        return None, []

    new_fm = re.sub(r"^(url:.*)$", lambda mm: mm.group(1) + "\n" + "\n".join(additions),
                    fm, count=1, flags=re.MULTILINE)
    return f"---\n{new_fm}---\n" + text[m.end():], added


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    if not MATCH_DIR.exists():
        print(f"no such directory: {MATCH_DIR}")
        return 1

    files = sorted(MATCH_DIR.glob("*.md"))
    todo, counts = [], {"cv": 0, "cover_letter": 0}
    for f in files:
        out, added = patch(f.stem, f.read_text(encoding="utf-8"))
        if out is None:
            continue
        todo.append((f, out))
        for k in added:
            counts[k] += 1

    print(f"reports: {len(files)}  |  would re-link: {len(todo)}  "
          f"(cv: {counts['cv']}, cover_letter: {counts['cover_letter']})")

    if not args.apply:
        for f, _ in todo[:5]:
            print(f"  e.g. {f.name}")
        print("dry run — nothing written. Re-run with --apply.")
        return 0

    # 10_output is gitignored, so there is no VCS to undo this. Snapshot first.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = OUT / f".matches_backup_pre_relink_{stamp}.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(MATCH_DIR, arcname=MATCH_DIR.name)
    print(f"backup: {archive.name}")

    for f, out in todo:
        f.write_text(out, encoding="utf-8")
    print(f"re-linked {len(todo)} reports")
    return 0


if __name__ == "__main__":
    sys.exit(main())
