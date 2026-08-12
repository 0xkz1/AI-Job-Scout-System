#!/usr/bin/env python3
"""Record what actually happened to an application.

Every question this system tries to answer — is the match score right, is a
posting a stretch, does a role type fit — is currently unanswerable, because
nothing records the outcome. 10 applications had been submitted and 0 results
stored, so the only ground truth available was the CV review, which grades the
document rather than what the employer did with it.

The frontmatter already anticipated this: `screening_failed_at` and
`interview_failed_at` sit in run.py's PRESERVED_FRONTMATTER_PREFIXES, and
stamp_flags_at.py knows how to date them. What was missing is anything that
sets them, and any path from a ticked report into _analyzed.json where analysis
can read it. This writes both.

Outcomes, and how they land:

  pending     applied, no answer yet. The default; nothing is stamped.
  rejected    turned down before a screen. screening_failed
  screening   reached a screen or first call. screening_passed
  interview   reached an interview. screening_passed + interview_passed
  offer       offer made. both, plus offer
  withdrawn   the candidate pulled out. withdrawn — NOT a rejection, and it
              must never be counted as one when measuring the scorer.

`--date` is the date the thing happened. Omitted, it uses today and records
`outcome_recorded_at` alongside, so a batch entered from memory is never
mistaken later for same-day precision.

  python record_outcome.py --list
  python record_outcome.py --url <url> --outcome rejected --date 2026-08-11
  python record_outcome.py --slug Wordsmith_AI_Product_Designer --outcome rejected
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MATCHES = ROOT / "10_output" / "00_matches"
ANALYZED = ROOT / "10_output" / "_analyzed.json"

# What each outcome asserts about the two gates the reports already track.
OUTCOMES = {
    "pending":   {},
    "rejected":  {"screening_failed": True},
    "screening": {"screening_passed": True},
    "interview": {"screening_passed": True, "interview_passed": True},
    "offer":     {"screening_passed": True, "interview_passed": True, "offer": True},
    "withdrawn": {"withdrawn": True},
}


def _front(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    return m.group(1) if m else ""


def _get(text: str, key: str) -> str | None:
    m = re.search(rf"^{re.escape(key)}:\s*\"?([^\"\n]*)\"?\s*$", _front(text), re.M)
    return m.group(1).strip() if m else None


def _set(text: str, key: str, value: str) -> str:
    """Set a frontmatter key, in place if present, appended if not.

    Appending rather than prepending, and only inside the block: run.py's own
    comment records what a duplicated key costs — every reader takes the FIRST
    match, so a second `applied:` line silently unlocked a submitted
    application.
    """
    front = _front(text)
    line = f"{key}: {value}"
    if re.search(rf"^{re.escape(key)}:", front, re.M):
        new_front = re.sub(rf"^{re.escape(key)}:.*$", line, front, count=1, flags=re.M)
    else:
        new_front = front + "\n" + line
    return text.replace(front, new_front, 1)


def _reports() -> list[tuple[Path, str]]:
    out = []
    for p in sorted(MATCHES.glob("*.md")):
        if ".sync-conflict-" in p.name:
            continue
        text = p.read_text(encoding="utf-8")
        if re.search(r"^applied:\s*true\s*$", _front(text), re.M | re.I):
            out.append((p, text))
    return out


def list_applications() -> None:
    print(f"{'slug':46s} {'outcome':10s} {'score':>6s}  company / title")
    for p, text in _reports():
        outcome = _get(text, "outcome") or "pending"
        print(f"{p.stem[:46]:46s} {outcome:10s} {_get(text,'match_score') or '':>6s}  "
              f"{_get(text,'company')} — {_get(text,'title')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--url")
    ap.add_argument("--slug")
    ap.add_argument("--outcome", choices=sorted(OUTCOMES))
    ap.add_argument("--date", help="when it happened (YYYY-MM-DD); default today")
    ap.add_argument("--apply", action="store_true", help="write; otherwise dry run")
    args = ap.parse_args()

    if args.list or not args.outcome:
        list_applications()
        return 0
    if not (args.url or args.slug):
        print("need --url or --slug", file=sys.stderr)
        return 2

    when = args.date or date.today().isoformat()
    approximate = args.date is None

    hits = [(p, t) for p, t in _reports()
            if (args.slug and p.stem == args.slug) or (args.url and _get(t, "url") == args.url)]
    if not hits:
        print("no applied report matches", file=sys.stderr)
        return 1

    for p, text in hits:
        new = _set(text, "outcome", args.outcome)
        new = _set(new, "outcome_at", when)
        if approximate:
            new = _set(new, "outcome_recorded_at", date.today().isoformat())
        for flag, value in OUTCOMES[args.outcome].items():
            new = _set(new, flag, "true" if value else "false")
            new = _set(new, f"{flag}_at", when)
        print(f"{'WRITE' if args.apply else 'would write'}  {p.name}: outcome={args.outcome} at {when}"
              + ("  (date approximate)" if approximate else ""))
        if args.apply:
            p.write_text(new, encoding="utf-8")
            _mirror(_get(text, "url"), args.outcome, when, approximate)
    return 0


def _mirror(url: str | None, outcome: str, when: str, approximate: bool) -> None:
    """Copy the outcome into _analyzed.json, keyed on url.

    On url, never on (company, title): that pair is not unique here and has
    faked a scraper bug more than once. Analysis reads this file, not the
    markdown, so an outcome that lives only in frontmatter is an outcome no
    measurement can use.
    """
    if not url:
        return
    raw = json.loads(ANALYZED.read_text(encoding="utf-8"))
    jobs = list(raw.values()) if isinstance(raw, dict) else raw
    for job in jobs:
        if job.get("url") != url:
            continue
        match = job.setdefault("match", {})
        match["outcome"] = outcome
        match["outcome_at"] = when
        match["outcome_date_approximate"] = approximate
        ANALYZED.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return


if __name__ == "__main__":
    sys.exit(main())
