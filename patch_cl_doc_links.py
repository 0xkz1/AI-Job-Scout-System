"""Fill in the empty match_report / cv wikilinks on assembled cover letters.

save_cover_letter takes the two link targets as arguments; run.py passes them,
but the batch that generated the top 200 letters did not, so every one of them
carries `match_report: "[[]]"` and `cv: "[[]]"`. The link targets are derived
from the filename, not from the letter's content, so they can be repaired in
place — regenerating would spend a model call per letter to rewrite a bridge
that is already correct.

Only empty links are touched, and only on the letters this can name a target
for. Run with --write to apply; the default is a dry run.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LETTERS = ROOT / "10_output" / "10_cover-letters"
MATCHES = ROOT / "10_output" / "00_matches"
CVS = ROOT / "10_output" / "10_cvs"

EMPTY = re.compile(r'^(match_report|cv): "\[\[\]\]"$', re.MULTILINE)


def main() -> None:
    write = "--write" in sys.argv
    patched = skipped = missing = 0

    for path in sorted(LETTERS.glob("*_CL.md")):
        text = path.read_text(encoding="utf-8")
        if not EMPTY.search(text):
            skipped += 1
            continue

        base = path.name[: -len("_CL.md")]
        # A letter whose report is absent gets no link rather than a broken one:
        # an empty wikilink renders as nothing, a wrong one renders as a
        # dead link the reader has to check.
        if not (MATCHES / f"{base}.md").exists():
            print(f"  no match report for {base}")
            missing += 1
            continue

        updated = text.replace('match_report: "[[]]"', f'match_report: "[[{base}]]"')
        if (CVS / f"{base}_CV.md").exists():
            updated = updated.replace('cv: "[[]]"', f'cv: "[[{base}_CV]]"')

        if write:
            path.write_text(updated, encoding="utf-8")
        patched += 1

    verb = "patched" if write else "would patch"
    print(f"\n{verb} {patched}; {skipped} already linked; {missing} without a match report")
    if not write:
        print("dry run — pass --write to apply")


if __name__ == "__main__":
    main()
