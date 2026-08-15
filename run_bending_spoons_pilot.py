"""Run one letter through the assembler with every stage printed.

The point is to see WHICH block a bad letter came from. Each block is printed
with its word count, so a letter that reads badly can be traced to the file that
needs editing (canonical_narrative_v1.md, letter_facts_v1.md) rather than to a
prompt — which is the whole reason the identity left the generation loop.
"""

import sys
from pathlib import Path

import cover_letter_generator as cl
from matcher import _load_persona_summary

jd_path = Path("10_output/00_matches/Bending_Spoons_UXUI_designer/job-description.md")
desc = jd_path.read_text(encoding="utf-8")
company = "Bending Spoons"
job_title = "UX/UI designer"


def show(label: str, text: str) -> None:
    print(f"\n--- {label} ({len(text.split())} words) ---", flush=True)
    print(text, flush=True)


print("--- Step 1: Authored assets ---", flush=True)
canonical = cl._load_canonical_narrative()
if not canonical:
    print("FAILED: canonical narrative did not load", flush=True)
    sys.exit(1)
facts = cl._load_letter_facts()
bank = cl._load_evidence_bank()
print(f"canonical paragraphs: {len(canonical.split(chr(10) * 2))}", flush=True)
print(f"letter facts: {len(facts)} | live CV entries: {len(bank)}", flush=True)

print("\n--- Step 2: Evidence selection (deterministic, no model) ---", flush=True)
role_type = cl.detect_role_type(job_title, desc)
evidence = cl._select_evidence(job_title, desc, role_type)
print(f"role_type: {role_type}", flush=True)
print(f"ranked:    {[item['source_id'] for item in evidence]}", flush=True)
if not evidence:
    print("FAILED: no evidence eligible for this role", flush=True)
    sys.exit(1)
evidence = cl._fit_evidence_to_budget(job_title, company, canonical, evidence)
print(f"kept:      {[item['source_id'] for item in evidence]} "
      f"(canonical is {len(canonical.split())} words)", flush=True)

print("\n--- Step 3: Context bridge (the only model-written block) ---", flush=True)
persona = _load_persona_summary() or ""
bridge, bridge_source = cl._build_context_bridge(job_title, company, desc,
                                                 canonical, evidence)
print(f"bridge source: {bridge_source}", flush=True)

print("\n--- Step 4: Assembly ---", flush=True)
show("opening", cl._OPENING_TEMPLATE.format(job_title=job_title, company=company))
show("canonical", canonical)
for item in evidence:
    show(f"evidence: {item['source_id']}", item["fact"])
show("bridge (the last two sentences of the letter)", bridge)

body = cl._assemble_letter_body(job_title, company, canonical, evidence, bridge)
ok, reason = cl._vet_letter_body(body)
print(f"\n--- Step 5: Assembled letter: {len(body.split())} words, "
      f"ok={ok}, reason={reason!r} ---", flush=True)

out_file = cl.save_cover_letter(
    job_title, company, "London", desc,
    "10_output/_pilot_cover-letters-medium",
    "_pilot_match", "_pilot_cv",
    override_body=body,
)
print(f"\nSaved: {out_file}", flush=True)
