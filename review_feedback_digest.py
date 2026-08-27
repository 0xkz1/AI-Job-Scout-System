"""What the reviewers keep saying about the SAME sentence, and where it is written.

The reviews are the one place a thousand independent readings of these documents
exist, and nobody can read a thousand of them. This gathers the style section of
every CV/CL review, groups the complaints by the sentence they quote, and points
at the authored file that sentence came from.

It edits nothing, and that is the design, not a limitation. Measured over 1065
CV reviews on 2026-08-27: the reviewers agree readily on WHICH sentence is a
problem — one is flagged 68 times — and almost never on what to write instead.
Those 68 flags proposed 54 distinct rewrites, the most popular appearing 3
times. A rule of the "8 of 10 agree, apply it" shape fires on the complaint and
picks noise on the fix.

Two other things the numbers say, both visible in the output below:

  - a large share of complaints are per-job TAILORING demands wearing the shape
    of a template defect. "Independent Creative Technologist" is flagged 41
    times, and reading the reason shows it is Product Designer postings asking
    for a Product Designer title. Applying that to the source would tilt the CV
    toward whichever role happens to dominate the scrape. So every group here
    carries the role distribution of the jobs that raised it.
  - the reviewer's fixes trend toward flattening. It called "no frameworks, no
    build tools" redundant; that clause is the point of the sentence. Judging
    that needs the author, not a majority vote.

So: read the digest, edit the source by hand. The expensive half — finding which
of the 209 flagged sentences is worth your time — is what this does.

Usage:
    python3 review_feedback_digest.py                  # CV reviews, 5+ flags
    python3 review_feedback_digest.py --kind both
    python3 review_feedback_digest.py --min-flags 20 --out /tmp/digest.md
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from matcher import make_safe_name  # noqa: E402

REVIEWS = ROOT / "10_output" / "15_reviews"
DB = ROOT / "10_output" / "_analyzed.json"
DEFAULT_OUT = ROOT / "10_output" / "_review_feedback_digest.md"

# Where the sentences are actually written. A flagged sentence that cannot be
# found in any of these came from an LLM-written span (the cover letter's
# tailored bridge, a generated summary) and cannot be fixed by editing a file —
# saying so is more useful than leaving the reader to search.
SOURCE_DIRS = [
    Path("/media/kz003/atelier/00_Kazuki/career/cv"),
    Path("/media/kz003/atelier/00_Kazuki/career/letter"),
    Path("/media/kz003/atelier/00_Kazuki/01-portfolio/projects"),
]

_STYLE_SECTION = re.compile(r"### ✍️ 文体(.*?)(?=\n### |\Z)", re.S)
_ITEM = re.compile(r'\d+\.\s+\*\*"(.+?)"\*\*(.*?)(?=\n\d+\.\s+\*\*|\Z)', re.S)
_REASON = re.compile(r"問題:\s*(.+)")
_FIX = re.compile(r"修正案:\s*[`\"]?(.+?)[`\"]?\s*$", re.M)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _index_sources() -> list[tuple[Path, int, str]]:
    """(path, line number, text) for every line of every authored file."""
    out = []
    for d in SOURCE_DIRS:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.md")):
            try:
                for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                    if line.strip():
                        out.append((p, n, _norm(line)))
            except OSError:
                continue
    return out


def _locate(sentence: str, index) -> str | None:
    """The authored line this sentence was taken from, if it is authored at all.

    Matched on a distinctive middle slice rather than the whole sentence: the
    generator wraps, joins and re-punctuates what it assembles, so an exact
    match finds nothing while the wording is plainly the same.
    """
    s = _norm(sentence)
    probe = s[:80] if len(s) < 120 else s[20:100]
    if len(probe) < 25:
        return None
    for path, n, line in index:
        if probe in line:
            try:
                rel = path.relative_to(Path("/media/kz003/atelier/00_Kazuki"))
            except ValueError:
                rel = path
            return f"{rel}:{n}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", choices=["CV", "CL", "both"], default="CV")
    ap.add_argument("--min-flags", type=int, default=5,
                    help="only report sentences flagged at least this often")
    ap.add_argument("--top", type=int, default=40, help="most-flagged N groups")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    kinds = ["CV", "CL"] if args.kind == "both" else [args.kind]
    jobs = json.loads(DB.read_text(encoding="utf-8"))
    by_base = {make_safe_name(j.get("company", ""), j.get("title", "")): j for j in jobs}

    flags = Counter()
    reasons = defaultdict(Counter)
    fixes = defaultdict(Counter)
    roles = defaultdict(Counter)
    scanned = 0

    for kind in kinds:
        for p in sorted(REVIEWS.glob(f"*_{kind}_review.md")):
            text = p.read_text(encoding="utf-8", errors="ignore")
            scanned += 1
            section = _STYLE_SECTION.search(text)
            if not section:
                continue
            base = p.name[: -len(f"_{kind}_review.md")]
            job = by_base.get(base)
            role = ((job or {}).get("match") or {}).get("detected_role") or "unknown"
            for item in _ITEM.finditer(section.group(1)):
                q = _norm(item.group(1))
                body = item.group(2)
                flags[q] += 1
                roles[q][role] += 1
                r = _REASON.search(body)
                if r:
                    reasons[q][_norm(r.group(1))[:90]] += 1
                f = _FIX.search(body)
                if f:
                    fixes[q][_norm(f.group(1))[:160]] += 1

    index = _index_sources()
    groups = [(n, q) for q, n in flags.items() if n >= args.min_flags]
    groups.sort(reverse=True)

    lines = [
        "# Review feedback digest",
        "",
        f"- reviews read: **{scanned}** ({', '.join(kinds)})",
        f"- distinct sentences flagged: **{len(flags)}**",
        f"- shown here: flagged {args.min_flags}+ times, top {args.top}",
        "",
        "Nothing below has been applied. Agreement on WHICH sentence is a problem",
        "is high; agreement on the replacement is not — read `修正案の一致` on each",
        "group before treating a rewrite as a verdict. A group whose roles are",
        "dominated by one discipline is usually asking for tailoring to that",
        "discipline, not reporting a defect in the source.",
        "",
        "---",
        "",
    ]

    for n, q in groups[: args.top]:
        where = _locate(q, index)
        top_fix = fixes[q].most_common(1)
        agree = (top_fix[0][1] / n) if top_fix else 0.0
        lines += [
            f"## {n}× — {where or '_(not in any authored file — LLM-written span)_'}",
            "",
            f"> {q[:400]}",
            "",
            f"- **修正案の一致**: {len(fixes[q])} distinct rewrites proposed; "
            f"the most common appears {top_fix[0][1] if top_fix else 0}× ({agree:.0%})",
            f"- **flagged by roles**: "
            + ", ".join(f"{r} {c}" for r, c in roles[q].most_common(4)),
            "",
            "**理由:**",
        ]
        for reason, c in reasons[q].most_common(4):
            lines.append(f"- ({c}×) {reason}")
        if fixes[q]:
            lines += ["", "**提案された修正案 (採用されていない):**"]
            for fix, c in fixes[q].most_common(3):
                lines.append(f"- ({c}×) {fix}")
        lines += ["", "---", ""]

    out = Path(args.out)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"📄 {len(groups)} sentence groups (>= {args.min_flags} flags) "
          f"from {scanned} reviews -> {out}")
    unlocated = sum(1 for n, q in groups if not _locate(q, index))
    print(f"   {unlocated} of the top groups are not in any authored file "
          f"(LLM-written spans — nothing to edit)")
    print("   Nothing was modified. Edit the authored files by hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
