"""One-off: restamp reviewed_sha after review_source_sha replaced raw-bytes hashing.

review_is_current used to hash the document's whole file. Every generated CV
carries the same contact lines and the same EDUCATION & LANGUAGES block, so
correcting two words in the university's name marked 450 documents for
re-review without changing a single claim any reviewer had judged. The hash now
skips those template-constant lines.

Changing the function invalidates every review already on disk, which is the
opposite of the point — so this restamps them. A review is restamped ONLY when
it was genuinely current beforehand, established one of two ways:

  * it matches the live document under the OLD hash (nothing changed since), or
  * it matches a PRE-RENAME copy of that document from a backup archive, and
    the live document differs from that copy only in the lines the new hash
    ignores.

Anything else keeps its old sha and stays stale, which is correct: those
documents really were rewritten. Restamping them would be the failure this
project keeps guarding against — a stale review reporting itself current.

Run with --apply to write. Without it, prints what would change.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tarfile
from pathlib import Path

from reviewer import REVIEWS_DIR, review_source_sha, _REVIEW_IGNORED_LINE

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "10_output"
DOC_DIRS = {"_CV": OUT / "10_cvs", "_CL": OUT / "10_cover-letters"}


def old_sha(data: bytes) -> str:
    """The hash review_is_current used before: the file's raw bytes."""
    return hashlib.sha1(data).hexdigest()


def ignored_lines_only(a: str, b: str) -> bool:
    """True when two documents differ only in lines the new hash skips."""
    strip = lambda t: [l for l in re.sub(r"\A---\n.*?\n---\n", "", t, flags=re.DOTALL).split("\n")
                       if not _REVIEW_IGNORED_LINE.match(l.strip())]
    return strip(a) == strip(b)


def load_backup_docs() -> dict[str, bytes]:
    """Documents as they stood in the most recent pre-rename archive."""
    archives = sorted(OUT.glob(".docs_backup_pre_*.tgz"), key=lambda p: p.stat().st_mtime)
    if not archives:
        return {}
    docs: dict[str, bytes] = {}
    with tarfile.open(archives[-1]) as t:
        for m in t.getmembers():
            if m.name.endswith(".md") and ("10_cvs/" in m.name or "10_cover-letters/" in m.name):
                f = t.extractfile(m)
                if f:
                    docs[Path(m.name).name] = f.read()
    print(f"  参照バックアップ: {archives[-1].name} ({len(docs)}件)")
    return docs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    backup = load_backup_docs()
    restamped = already = left_stale = 0

    for review in sorted(REVIEWS_DIR.glob("*_review.md")):
        stem = review.name[: -len("_review.md")]
        suffix = "_CV" if stem.endswith("_CV") else "_CL" if stem.endswith("_CL") else None
        if suffix is None:
            continue
        doc = DOC_DIRS[suffix] / f"{stem}.md"
        if not doc.exists():
            continue

        text = review.read_text(encoding="utf-8")
        # Quotes optional — Obsidian strips them when it rewrites frontmatter.
        m = re.search(r'^reviewed_sha:\s*"?([0-9a-f]+)"?', text, re.MULTILINE)
        if not m:
            continue
        stamped = m.group(1)
        live = doc.read_bytes()
        new = review_source_sha(doc)

        if stamped == new:
            already += 1
            continue

        was_current = stamped == old_sha(live)
        if not was_current:
            old_doc = backup.get(doc.name)
            was_current = bool(
                old_doc
                and stamped == old_sha(old_doc)
                and ignored_lines_only(old_doc.decode("utf-8"), live.decode("utf-8"))
            )
        if not was_current:
            left_stale += 1
            continue

        restamped += 1
        if args.apply:
            review.write_text(
                re.sub(r'^reviewed_sha:.*$', f'reviewed_sha: "{new}"', text,
                       count=1, flags=re.MULTILINE),
                encoding="utf-8",
            )

    verb = "restamped" if args.apply else "would restamp"
    print(f"{verb}: {restamped}")
    print(f"  既に新方式: {already}")
    print(f"  陳腐のまま据え置き: {left_stale}")
    if not args.apply:
        print("dry run — nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
