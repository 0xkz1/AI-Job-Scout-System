"""Cluster review findings that trace back to a shared source file.

When N different CVs get flagged for the same weak sentence, it is because
that sentence lives in ONE reusable master (career/cv/profile/, projects/,
skill-toolkit/, cover-letter/) and got copied into every generation. Fixing
it per-document N times is wasted motion — fixing the source once fixes all
future generations (and, via apply_fixes_to_sources, the current ones too).

This script does NOT touch anything. It reads every review under
10_output/15_reviews/*_review.md, uses reviewer.fix_targets() to find which
suggested fixes trace to a source file, groups them by (source file,
original quote), and prints a report ranked by how many reviews raised it —
so the user can eyeball which fixes are worth applying at the source before
anyone touches career/cv/*.

Usage: .venv/bin/python3 aggregate_source_findings.py [--min-hits 2]
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reviewer import REVIEWS_DIR, fix_targets  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-hits", type=int, default=2,
                     help="only show findings raised in at least this many reviews (default 2)")
    args = ap.parse_args()

    reviews = sorted(REVIEWS_DIR.glob("*_review.md"))
    if not reviews:
        print("レビューが見つかりません (10_output/15_reviews/*_review.md)")
        return

    # (source_label, original) -> {replacements: [...], reviews: [...]}
    # replacements is a list (not a set) of (replacement, review_stem) so a
    # split verdict — same weak sentence, different job-specific rewrites —
    # is visible instead of silently overwritten by whichever review ran last.
    groups: dict[tuple[str, str], dict] = defaultdict(lambda: {"replacements": [], "reviews": []})
    skipped_errors = []

    for rp in reviews:
        try:
            targets = fix_targets(rp)
        except Exception as e:
            skipped_errors.append(f"{rp.name}: {e}")
            continue
        for original, replacement, source, _why in targets:
            if source is None:
                continue  # doc-only / frontmatter / already-applied — not a source cluster
            key = (source, original)
            stem = rp.stem.replace("_review", "")
            groups[key]["replacements"].append((replacement, stem))
            groups[key]["reviews"].append(stem)

    if not groups:
        print("ソースに遡れる指摘は見つかりませんでした "
              "(全指摘がdoc-only、または全レビューが最新のsource済み)")
        if skipped_errors:
            print(f"\n⚠ {len(skipped_errors)}件のレビューでエラー:")
            for e in skipped_errors[:5]:
                print(f"  {e}")
        return

    # Rank by hit count desc, then by source file for readability
    ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]["reviews"]), kv[0][0]))
    shown = [kv for kv in ranked if len(kv[1]["reviews"]) >= args.min_hits]

    # A finding is only a safe one-shot source fix when every review that
    # raised it agrees on the SAME rewrite. If the rewrites differ, the weak
    # spot is real but the "correct" fix is job-specific — rewriting the
    # master to any one of them would misfit the other jobs that share it.
    agreeing = [kv for kv in shown if len({r for r, _ in kv[1]["replacements"]}) == 1]
    split = [kv for kv in shown if len({r for r, _ in kv[1]["replacements"]}) > 1]

    print(f"{'='*70}")
    print(f"ソース由来の共通指摘 — {len(reviews)}件のレビュー中、{len(groups)}件のクラスタ")
    print(f"({args.min_hits}件以上のレビューで指摘されたもののみ表示: {len(shown)}件"
          f" — 一致{len(agreeing)}件 / 意見割れ{len(split)}件)")
    print(f"{'='*70}\n")

    if agreeing:
        print(f"── ✅ 修正案が一致 (安全にソース側へ一括適用可能) ──────────────\n")
        for (source, original), data in agreeing:
            n = len(data["reviews"])
            replacement = data["replacements"][0][0]
            print(f"【{n}件で指摘】 {source}")
            print(f"  原文: \"{original[:100]}{'...' if len(original) > 100 else ''}\"")
            print(f"  修正案: \"{replacement[:100]}{'...' if len(replacement) > 100 else ''}\"")
            print(f"  該当求人: {', '.join(data['reviews'][:5])}"
                  + (f" 他{n-5}件" if n > 5 else ""))
            print()

    if split:
        print(f"\n── ⚠️ 同じ箇所だが修正案が割れている (求人ごとに正解が違う可能性 — マスター一括書き換え注意) ──\n")
        for (source, original), data in split:
            n = len(data["reviews"])
            print(f"【{n}件で指摘、修正案{len({r for r, _ in data['replacements']})}種】 {source}")
            print(f"  原文: \"{original[:100]}{'...' if len(original) > 100 else ''}\"")
            for repl, stem in data["replacements"]:
                print(f"    - ({stem}) → \"{repl[:90]}{'...' if len(repl) > 90 else ''}\"")
            print()

    if len(shown) < len(ranked):
        print(f"({len(ranked) - len(shown)}件は{args.min_hits}件未満のため非表示 — --min-hits 1 で全表示)")

    if skipped_errors:
        print(f"\n⚠ {len(skipped_errors)}件のレビューでエラー (フォーマット不整合など):")
        for e in skipped_errors[:5]:
            print(f"  {e}")


if __name__ == "__main__":
    main()
