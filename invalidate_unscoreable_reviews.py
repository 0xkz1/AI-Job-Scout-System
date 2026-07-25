"""Blank out submission scores that were derived from a failed scrape.

When a posting's description is empty or is page machinery, the reviewer has no
requirements to check against — but instead of abstaining it invents 3-5 plausible
ones from the job title, finds a generic CV satisfies all of them, and writes a
high score. HYPERCREATE LTD's "Web Designer" reached submission_score 100 with
submission_ready true off a rubric of "familiar with Figma", "understands
responsive design", "basic HTML and CSS" — none of which came from the posting,
because the posting was tracker JavaScript.

A wrong "提出可" is the most costly output this system can produce, so those scores
are set to null (未算出, a state the reviewer already models) rather than left to
look like verdicts. The findings text is kept: it was written against the real CV
and stays useful reading. reviewed_sha is untouched — the document did not change,
only our trust in the score.

    python3 invalidate_unscoreable_reviews.py --dry-run
    python3 invalidate_unscoreable_reviews.py
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from matcher import make_safe_name  # noqa: E402
from reviewer import PRISTINE_DIR, REVIEWS_DIR, _score_line  # noqa: E402
from selection import _dedupe, is_unscoreable  # noqa: E402

ANALYZED = ROOT / "10_output" / "_analyzed.json"
NOTE = ("**採点不能:** この求人の説明文はスクレイプに失敗しており(空またはページの"
        "JavaScript)、レビュアーは求人の実際の要件を読めていません。ルーブリックは"
        "職種名から推測されたものなので、提出スコアは無効です。求人票を再取得してから"
        "再レビューしてください。")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    jobs = json.loads(ANALYZED.read_text(encoding="utf-8"))
    bad_bases = {
        make_safe_name(j.get("company", ""), j.get("title", ""))
        for j in _dedupe(jobs) if j.get("match") and is_unscoreable(j)
    }
    print(f"unscoreable jobs: {len(bad_bases)}")

    hits, already = [], 0
    for path in sorted(REVIEWS_DIR.glob("*_review.md")):
        stem = path.stem[: -len("_review")]
        base = stem[:-3] if stem.endswith(("_CV", "_CL")) else stem
        if base not in bad_bases:
            continue
        text = path.read_text(encoding="utf-8")
        m = re.search(r"^submission_score:\s*(\S+)", text, flags=re.MULTILINE)
        if m and m.group(1) == "null":
            already += 1
            continue
        hits.append((path, text, m.group(1) if m else "?"))

    print(f"reviews to invalidate: {len(hits)}   already null: {already}")
    for path, _t, old in hits:
        print(f"  {old:>4} -> null   {path.stem}")

    if args.dry_run:
        print("\nDRY RUN — nothing written")
        return 0

    for path, text, _old in hits:
        out = re.sub(r"^submission_score:.*$", "submission_score: null",
                     text, count=1, flags=re.MULTILINE)
        out = re.sub(r"^submission_ready:.*$", "submission_ready: false",
                     out, count=1, flags=re.MULTILINE)
        out = re.sub(r"^unscoreable:.*$\n?", "", out, flags=re.MULTILINE)
        out = re.sub(r"^(submission_score:.*)$", r"\1\nunscoreable: true",
                     out, count=1, flags=re.MULTILINE)
        # Swap the in-body badge for the reason, so the number is not left
        # contradicting the frontmatter where Properties are hidden.
        nits = re.search(r"^style_nits:\s*(\d+)", out, flags=re.MULTILINE)
        line = _score_line(None, False, int(nits.group(1)) if nits else 0)
        out = re.sub(r"^\*\*提出スコア:\*\*.*\n?", "", out, flags=re.MULTILINE)
        if re.search(r"###\s*総評", out):
            out = re.sub(r"(###\s*総評)", f"{line}\n\n{NOTE}\n\n\\1", out, count=1)
        else:
            out = out.rstrip() + f"\n\n{line}\n\n{NOTE}\n"
        path.write_text(out, encoding="utf-8")
        pristine = PRISTINE_DIR / path.name
        if pristine.exists():  # keep the annotation baseline in step
            pristine.write_text(out, encoding="utf-8")

    print(f"\ninvalidated: {len(hits)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
