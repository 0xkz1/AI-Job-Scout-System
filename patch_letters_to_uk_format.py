"""One-off: bring already-generated cover letters onto the current template.

The letter template changed in four ways that are pure text — a UK reader's
expectations about a letter's head, plus one paragraph reworded from a noun
pile into sentences. Regenerating would apply them too, but regeneration
re-rolls the LLM opening and closing, so it would also discard the specific,
already-reviewed prose in 471 letters to fix their punctuation. These are
string edits; do them as string edits.

  * The salutation named the company ("Dear Hiring Team at Lloyds Banking
    Group,"), which repeats the line directly above it. UK letters open
    "Dear Hiring Team,".
  * Dates were zero-padded ("02 August 2026"). UK style is "2 August 2026" —
    and the date line now goes in at PDF-render time, so it is dropped here
    entirely rather than corrected.
  * The recipient block carried the scraper's county ("Edinburgh,
    Midlothian"), which reads as a half-typed postal address.
  * The TAIFUNOME sentence listed four noun phrases in a row.

Run with --apply to write. Without it, prints what would change.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CL_DIR = Path(__file__).resolve().parent / "10_output" / "10_cover-letters"

OLD_TAIFUNOME = (
    "Most recently I designed TAIFUNOME from the ground up as an independent "
    "research platform: brand architecture and naming, information architecture "
    "separating findings from tools from finished work, a hand-built design "
    "system, and the CMS schemas behind it."
)
NEW_TAIFUNOME = (
    "Most recently, I designed and built TAIFUNOME, an independent research "
    "platform, defining its brand identity, structuring its information "
    "architecture to separate findings from tools from finished work, and "
    "building both the design system and the CMS schemas behind it."
)

# "12 August 2026" on a line of its own, zero-padded or not.
DATE_LINE = re.compile(r"^\d{1,2} [A-Z][a-z]+ \d{4}\n", re.MULTILINE)


def has_no_company(text: str) -> bool:
    """True for letters generated with an empty company name.

    Their salutation reads "Dear Hiring Team at ," and the recipient block has
    a blank line where the employer should be — some are old enough to still
    carry a "# Cover Letter" heading no current template emits. Tidying the
    punctuation would leave a letter that is addressed to nobody while looking
    finished, which is worse than one that obviously is not. They are reported
    and skipped; the fix is to recover the company on the job and regenerate.
    """
    if "Dear Hiring Team at ," in text:
        return True
    m = re.search(r'^company: "(.*)"$', text, re.MULTILINE)
    return bool(m and not m.group(1).strip())


def patch(text: str) -> tuple[str, list[str]]:
    """Return the corrected letter and the list of fixes applied."""
    fixes = []

    body_at = text.find("\n---\n")  # never touch frontmatter
    head, body = (text[: body_at + 5], text[body_at + 5:]) if body_at != -1 else ("", text)

    # An older generator opened the letter with an H1 naming the job. The
    # renderer promotes the first line to the page heading, so those letters
    # print the JOB TITLE where the sender's name belongs and demote the name
    # to body text. The job is already the frontmatter `title:`.
    new = re.sub(r"\A\s*#[^\n]*\n+", "\n", body, count=1)
    if new != body:
        body, _ = new, fixes.append("stray H1 removed (was printing as the letterhead)")

    # "(Local Resident)" was dropped from the master contact line; leaving it on
    # older letters makes two versions of the same sender block.
    new = body.replace("Edinburgh, Scotland, UK (Local Resident)", "Edinburgh, Scotland, UK")
    if new != body:
        body, _ = new, fixes.append("contact line matches master")

    new = DATE_LINE.sub("", body, count=1)
    if new != body:
        body, _ = new, fixes.append("date line removed (now stamped at render)")

    new = re.sub(r"^Dear Hiring Team at .+,$", "Dear Hiring Team,", body, count=1, flags=re.MULTILINE)
    if new != body:
        body, _ = new, fixes.append("salutation")

    # Recipient block: the line after "Hiring Team\n{company}". Only that one —
    # the sender's own "Edinburgh, Scotland, UK" line above it stays as is.
    m = re.search(r"^(Hiring Team\n.+\n)(.+)$", body, re.MULTILINE)
    if m and "," in m.group(2):
        city = m.group(2).split(",")[0].strip()
        if city:
            body = body[: m.start(2)] + city + body[m.end(2):]
            fixes.append(f"recipient location → {city}")

    if OLD_TAIFUNOME in body:
        body = body.replace(OLD_TAIFUNOME, NEW_TAIFUNOME)
        fixes.append("TAIFUNOME paragraph")

    return head + body, fixes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    if not CL_DIR.exists():
        print(f"no such directory: {CL_DIR}")
        return 1

    files = sorted(CL_DIR.glob("*_CL.md"))
    counts: dict[str, int] = {}
    changed = 0
    skipped: list[str] = []
    for f in files:
        original = f.read_text(encoding="utf-8")
        if has_no_company(original):
            skipped.append(f.name)
            continue
        patched, fixes = patch(original)
        if not fixes:
            continue
        changed += 1
        for fix in fixes:
            key = fix.split(" →")[0]
            counts[key] = counts.get(key, 0) + 1
        if args.apply:
            f.write_text(patched, encoding="utf-8")

    verb = "patched" if args.apply else "would patch"
    print(f"{verb} {changed}/{len(files)} letters")
    for key, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {key}")
    if skipped:
        print(f"\nskipped {len(skipped)} letters addressed to nobody "
              f"(empty company — regenerate once the job has one):")
        for name in skipped:
            print(f"  {name}")
    if not args.apply:
        print("\ndry run — nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
