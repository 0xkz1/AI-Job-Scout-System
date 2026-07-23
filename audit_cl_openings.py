"""Audit generated cover-letter openings against the current gates.

The gates in cover_letter_generator only run at generation time, so a letter
written before a gate was tightened keeps whatever slipped through. This
re-runs the *current* checks over letters already on disk and reports which
ones would be rejected now — without calling the writer model, so it is cheap
to run after every gate change.

Only the opening paragraph is checked: the rest of the letter is static
template text, which the gates never governed.

Usage:
  .venv/bin/python3 audit_cl_openings.py --limit 56
  .venv/bin/python3 audit_cl_openings.py --limit 56 --list   # print paths only
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from filter import passes_filter  # noqa: E402
from matcher import make_safe_name, _load_persona_summary  # noqa: E402
from cover_letter_generator import (  # noqa: E402
    _claims_unsupported_sector, _has_inverted_person, _verify_opening_claims,
)

ANALYZED = ROOT / "10_output" / "_analyzed.json"
CL_DIR = ROOT / "10_output" / "10_cover-letters"


def opening_of(path: Path) -> str:
    """First body paragraph after the greeting — the only LLM-written part."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"Dear Hiring Team[^\n]*\n+(.+?)(?:\n\n|\Z)", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=56)
    ap.add_argument("--list", action="store_true", help="print only the failing stems")
    args = ap.parse_args()

    jobs = json.loads(ANALYZED.read_text())
    config = yaml.safe_load((ROOT / "config.yaml").read_text()) or {}
    passed = [j for j in jobs if j.get("match") and passes_filter(j, config)[0]]
    passed.sort(key=lambda j: j["match"]["composite_score"], reverse=True)
    persona = _load_persona_summary() or ""

    checked = failing = template = 0
    rows = []
    for job in passed[:args.limit]:
        base = make_safe_name(job.get("company", ""), job.get("title", ""))
        p = CL_DIR / f"{base}_CL.md"
        if not p.exists():
            continue
        # A template opening was never model-written — nothing to audit.
        if 'opening_source: "template"' in p.read_text(encoding="utf-8"):
            template += 1
            continue
        text = opening_of(p)
        if not text:
            continue
        checked += 1

        reason = None
        if not re.search(r"(?:^|\s)(?:I|I['’](?:m|ve|d|ll)|[Mm]y)\b", text):
            reason = "not first person"
        if reason is None:
            inverted = _has_inverted_person(text)
            if inverted:
                reason = f"inverted person: {inverted}"
        if reason is None:
            sector = _claims_unsupported_sector(text, persona)
            if sector:
                reason = f"unsupported sector: {sector}"
        if reason is None:
            unsupported = _verify_opening_claims(text)
            if unsupported:
                reason = f"unsupported claim: {unsupported}"

        if reason:
            failing += 1
            rows.append((base, reason))

    if args.list:
        for base, _ in rows:
            print(base)
        return 0

    print(f"LLM冒頭文を持つCL: {checked}件 (テンプレート冒頭: {template}件)")
    print(f"現行ゲートで不合格: {failing}件")
    for base, reason in rows:
        print(f"  {base[:52]:52s} {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
