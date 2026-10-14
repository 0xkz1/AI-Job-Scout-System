"""Bring one project's write-up in existing CVs back onto its source file.

cv_generator copies project descriptions out of career/cv/projects/*.md
verbatim — the experience prompt asks the model to select and order projects
and forbids modifying their text — so when a project file is edited, every CV
already on disk keeps the old wording until it is regenerated. Regeneration
re-rolls the LLM ordering and rewrites the other three write-ups, which is a
lot of churn to change one paragraph. This is a string edit; do it as one.

Written for the TAIFUNOME rewrite on 2026-08-31, which was a disclosure
decision rather than a wording one: the old bullets named the rendering
approach, the particle system, the camera timeline and the audio engine —
detail a hiring reader does not need and a competing studio does. What a CV
should carry is what was built and what it does, not how exactly. Anything
still on disk claiming the old text is the old decision, still being sent out.

Only the bullet lines move. The heading, its URL, and every other section stay
byte-for-byte as they are, and a locked CV is not touched at all: `applied`
means the file IS the record of what was submitted.

    python3 patch_project_bullets.py --project taifunome-research-platform
    python3 patch_project_bullets.py --project taifunome-research-platform --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import cv_generator as cg  # noqa: E402
import gen_version  # noqa: E402

CV_DIR = ROOT / "10_output" / "10_cvs"
MATCH_DIR = ROOT / "10_output" / "00_matches"


def source_bullets(project: dict) -> list[str]:
    return [l.strip() for l in (project.get("description") or "").split("\n")
            if l.strip().startswith("•")]


def patch(text: str, project: dict, bullets: list[str]) -> tuple[str, bool]:
    """The CV with this project's bullets replaced by the source's."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    changed = False
    while i < len(lines):
        line = lines[i]
        heading = line.strip().replace("**", "")
        # An entry heading: "Title | Role | Period", possibly with a trailing
        # " · [url]". Matched through the same near-match rule the repair uses,
        # because the model rewrites headings as it orders them.
        is_heading = heading.count(" | ") >= 2 and not heading.startswith(("•", "-", "#"))
        if not is_heading:
            out.append(line)
            i += 1
            continue

        title = heading.split(" | ", 1)[0].split(" · ", 1)[0]
        title = title.replace("[", "").replace("]", "").strip()
        out.append(line)
        i += 1
        if cg._project_for_title(title) is not project:
            continue

        block = []
        while i < len(lines) and lines[i].strip():
            block.append(lines[i].strip())
            i += 1
        if not block:
            continue

        # Older CVs render a write-up as one prose paragraph rather than as
        # bullets. Rewriting those into bullets would leave one entry in a new
        # format and the three around it in the old one, so the replacement
        # takes the shape it is replacing — the same sentences, run together.
        if block[0].startswith("•"):
            replacement = bullets
        else:
            replacement = [" ".join(b.lstrip("• ").strip() for b in bullets)]
        if block != replacement:
            out.extend(replacement)
            changed = True
        else:
            out.extend(block)
    return "\n".join(out), changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", required=True, help="project id from career/cv/projects")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    project = next((p for p in cg.PROJECTS if p["id"] == args.project), None)
    if project is None:
        print(f"no project with id {args.project!r}")
        return 1
    bullets = source_bullets(project)
    if not bullets:
        print(f"{args.project} has no bullets to copy")
        return 1

    files = sorted(CV_DIR.glob("*_CV.md"))
    changed = locked = 0
    deltas = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        if gen_version.is_locked(f.stem[:-3], text, MATCH_DIR):
            locked += 1
            continue
        patched, did = patch(text, project, bullets)
        if not did:
            continue
        changed += 1
        deltas.append(len(patched.split()) - len(text.split()))
        if args.apply:
            f.write_text(patched, encoding="utf-8")

    verb = "patched" if args.apply else "would patch"
    print(f"{verb} {changed}/{len(files)} CVs" + (f", {locked} locked (skipped)" if locked else ""))
    if deltas:
        print(f"word delta: min {min(deltas)}  max {max(deltas)}  "
              f"mean {sum(deltas) / len(deltas):.1f}")
    if not args.apply:
        print("dry run — nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
