"""Re-render 00_matches/*.md from the DB, preserving every non-score field.

run.py writes each match report at scrape time, BEFORE skill_coverage_backfill
has a verdict for that job — so the file on disk carries dictionary-only scores.
recompute_skill_scores.py then fixes _analyzed.json but never touches the .md,
which is what Obsidian/Dataview actually read. Without this step the nightly
silently shows pre-coverage numbers.

A report whose job is ticked applied or expired is skipped outright: those
locks exist so a submitted application's record stops moving, and this script
rewrites the very file the lock flag is read from.

For the rest, cv/cover_letter/route/saved_at/expired/applied and the carried
cv_pdf/cl_pdf/cv_review/cl_review lines are read back off the existing file and
fed to the renderer, so only score-derived frontmatter and the body change.
Files whose content would be byte-identical are left alone (no vault churn).

DRY-RUN by default; pass --apply to write.
"""
import sys
import re
import json
import difflib
from pathlib import Path

JIS = Path(__file__).resolve().parent
sys.path.insert(0, str(JIS))

import gen_version  # noqa: E402
from matcher import (  # noqa: E402
    generate_match_report, read_expired_flag, read_applied_flag,
    read_carried_properties,
)
from scraper_url_list import normalize_url  # noqa: E402

MATCH_DIR = JIS / "10_output" / "00_matches"
DB_PATH = JIS / "10_output" / "_analyzed.json"

APPLY = "--apply" in sys.argv


def parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"')
    return fm


def wikilink_to_filename(val: str) -> str | None:
    # cv: "[[Name]]"  ->  Name.md
    m = re.search(r"\[\[(.+?)\]\]", val or "")
    return (m.group(1) + ".md") if m else None


def main():
    db = json.loads(DB_PATH.read_text())
    by_url, by_title = {}, {}
    for job in db:
        if not job.get("match"):
            continue
        u = job.get("url")
        if u:
            by_url[normalize_url(u)] = job
        key = (job.get("title", ""), job.get("company", ""))
        by_title[key] = job

    files = sorted(p for p in MATCH_DIR.glob("*.md") if p.is_file())
    matched, unmatched, changed, unchanged, locked = 0, [], 0, 0, 0
    sample_shown = False

    for path in files:
        text = path.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)

        # A job ticked applied or expired is frozen — see gen_version's lock
        # rationale: once applied to, "the files on disk ARE the record of what
        # was actually submitted. They must stop moving." Those locks were
        # written to guard the CV/CL, and nothing guarded the match report that
        # the lock flag is itself read from. Re-rendering it moves the record of
        # a submitted application (and, before the flags were passed through
        # below, silently cleared the tick as well).
        if gen_version.job_lock_reason(path.stem, MATCH_DIR):
            locked += 1
            continue
        url = fm.get("url", "")
        job = by_url.get(normalize_url(url)) if url else None
        if job is None:
            job = by_title.get((fm.get("title", ""), fm.get("company", "")))
        if job is None:
            unmatched.append(path.name)
            continue
        matched += 1

        # Preserve non-score frontmatter by feeding the render exactly what the
        # existing file recorded (score fields come from the DB match dict).
        job = dict(job)  # shallow copy — don't mutate the DB in memory
        if fm.get("saved_at"):
            job["scraped_at"] = fm["saved_at"]  # generate_match_report slices [:10]
        if fm.get("route"):
            job["route"] = fm["route"]
        if fm.get("source"):
            job["source"] = fm["source"]
        if fm.get("type"):
            job["type"] = fm["type"]

        cv = wikilink_to_filename(fm.get("cv", ""))
        cl = wikilink_to_filename(fm.get("cover_letter", ""))

        match = dict(job["match"])
        # Preserve the description-missing banner if the old file had it.
        if "> **⚠️ 求人説明文が取得できませんでした" in text:
            match["description_missing"] = True

        # generate_match_report's own docstring warns that every caller must
        # pass expired/applied through, or a rewrite silently resets both to
        # false — save_match_report does this correctly by reading the flags
        # off the file it is about to overwrite. This function did not, and on
        # 2026-08-06 that reset applied/expired on every report whose content
        # had changed, wiping hand-ticked checkboxes for jobs already applied
        # to. `carried` (cv_pdf/cl_pdf/cv_review/cl_review) was missing the
        # same way and lost the same night.
        new_text = generate_match_report(
            job, match, cv, cl,
            expired=read_expired_flag(path),
            applied=read_applied_flag(path),
            carried=read_carried_properties(path),
        )
        # Preserve the original file's trailing-newline convention so a pure
        # newline delta never counts as a change (avoids churning 589 files
        # in the vault for a 1-byte difference).
        if text.endswith("\n") and not new_text.endswith("\n"):
            new_text += "\n"
        elif not text.endswith("\n"):
            new_text = new_text.rstrip("\n")

        if new_text == text:
            unchanged += 1
            continue
        changed += 1

        if not sample_shown and "Waffle" in path.name:
            sample_shown = True
            diff = difflib.unified_diff(
                text.splitlines(), new_text.splitlines(),
                fromfile=path.name + " (old)", tofile=path.name + " (new)",
                lineterm="", n=1,
            )
            print("=== SAMPLE DIFF:", path.name, "===")
            print("\n".join(diff))
            print("=== end sample ===\n")

        if APPLY:
            path.write_text(new_text, encoding="utf-8")

    print(f"files={len(files)} matched={matched} unmatched={len(unmatched)} "
          f"changed={changed} unchanged={unchanged} locked={locked} apply={APPLY}")
    if unmatched:
        print(f"UNMATCHED ({len(unmatched)}) — left untouched:")
        for n in unmatched[:40]:
            print("  ", n)
        if len(unmatched) > 40:
            print(f"   ... and {len(unmatched)-40} more")


if __name__ == "__main__":
    main()
