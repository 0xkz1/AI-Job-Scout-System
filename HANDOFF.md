# Cover-letter narrative generation — handoff

Updated: 2026-08-08 (Asia/Tokyo)

## Goal

Replace the legacy cover-letter template assembly with a strategy-led narrative:

1. select verified source records for the specific job;
2. draft a 260–335-word UK-English letter body from those records only;
3. fact/style-check it and revise once; and
4. save it with `generation_mode: "strategy-narrative"`.

The legacy opening/template flow remains only as the safe fallback when the narrative path fails.

## Current implementation

`cover_letter_generator.py` now contains the narrative path:

- `_load_evidence_bank()` builds records from `../cv/projects/` and `../cv/experience/`.
- `_create_letter_strategy()` asks the LLM to choose primary/secondary evidence before drafting.
- `_resolve_evidence_id()` safely normalizes a unique source title to its short `E##` ID. This was needed because Medium returned a project title instead of the requested ID.
- An invalid optional secondary ID is discarded while a valid primary ID is retained. A bad optional ID must not discard a grounded strategy.
- `_draft_narrative_body()` → `_critique_narrative_body()` → `_revise_narrative_body()` produces the body.
- `_vet_narrative_body()` enforces 3–5 paragraphs, 260–335 words, first person, no unsupported sector claims/metrics/exit plan, and LLM fact checking.
- `_require_narrative_length_revision()` forces a revision if the critic accepts a draft below 260 words. The minimum is deliberately **260**; do not lower it to make a terse model pass.

`save_cover_letter()` writes `generation_mode: "strategy-narrative"` only when this path succeeds; otherwise it writes `legacy-template`.

## What the Bending Spoons pilot showed

Pilot target:

- posting: `10_output/00_matches/Bending_Spoons_UXUI_designer/job-description.md`
- output: `10_output/_pilot_cover-letters-medium/Bending_Spoons_UXUI_designer_CL.md`
- role: UX/UI designer, Bending Spoons

Input material is not too short:

- posting: 1,197 words;
- persona summary: 2,025 words;
- TAIFUNOME evidence record: 162 words;
- Portfolio Website record: 88 words;
- AI Job Scout record: 90 words.

Results:

- Mistral Tiny produced prohibited phrasing (`friction between intent and execution`, `deployment-agnostic`), so the safety gate correctly used the fallback.
- Medium initially returned a valid primary `E02` but an invented optional `E03`; that exposed the optional-secondary handling bug, now fixed.
- With the normal fallback chain working, Medium produced narrative candidates of 213, then 155/162, then 227/189 words even after the length-revision instruction. They are too short for the accepted 260–335-word standard, so the pilot remains `legacy-template`.

Do **not** treat the legacy pilot file as a successful narrative output.

## Main remaining problem

The strategy prompt is now given the role-specific evidence guidance in `_ROLE_PROJECT_HINTS`, and substantive postings are told to prefer two complementary records. For a UX/UI role this steers it toward a strong pair such as:

1. `TAIFUNOME — Research & Creative Technology Platform`; and
2. `Portfolio Website Design & Development`.

That narrow one-record input makes a grounded 260–335-word argument unnecessarily hard and encourages either short output or filler.

### Recommended next validation

The role-guidance prompt change has mocked coverage. Retry **one** Bending Spoons pilot with Mistral Medium using the normal fallback chain when API budget permits. Do not bulk-regenerate until it produces `generation_mode: "strategy-narrative"` and the prose is manually reviewed.

## Mistral fallback and quarantine

Configured in `.env` (do not print key values):

- 10 Mistral key slots: `mistral` through `mistral-denary`;
- fallback order continues through `nvidia`, `opencode-go`, `opencode`, and `ollama`;
- state file: `10_output/.key_quarantine.json`.

Important fixes made this session:

- `llm_client.call_llm()` now invokes `_maybe_quarantine()` even when the failing provider is the final provider in the chain. Previously a single-provider pilot never quarantined its failing key.
- HTTP `402 Payment Required` is now treated as transient for fallback and as a quota/auth condition for quarantine. It had previously stopped the chain without fallback.
- 429 gets a 15-minute cooldown; 401/402/403 and quota/auth failures get a 5-day cooldown.

Before a normal-chain pilot, use an environment that does **not** override `FALLBACK_PROVIDERS` or `FALLBACK_PROVIDER`:

```bash
env -u FALLBACK_PROVIDERS -u FALLBACK_PROVIDER \
  ANALYSIS_PROVIDER=mistral MISTRAL_MODEL=mistral-medium-latest \
  PYTHONUNBUFFERED=1 .venv/bin/python -c '...'
```

The earlier experiments used `FALLBACK_PROVIDERS=` deliberately for a one-key comparison; that disables the normal chain and is not a fallback test.

## Regeneration status

- `gen_version.py` is bumped to `2026-08-08.1` for the narrative-generation specification.
- `python regen_top_docs.py --dry-run --stale-only --percent 30` identifies **360** unlocked stale CV/CL pairs (23 locked pairs skipped).
- Existing documents must not be bulk-regenerated yet. `regen_top_docs.py` overwrites CVs and archives old CLs; run it only after the one-document pilot is accepted.

## Tests run

Use the project virtualenv, not the system Python:

```bash
cd career/Job-Intelligence-System
.venv/bin/python -m pytest -q \
  tests/test_cover_letter_narrative.py \
  tests/test_llm_fallback.py \
  tests/test_key_quarantine_cooldown.py
```

Last result: **24 passed**.

Also run:

```bash
.venv/bin/python -m py_compile cover_letter_generator.py llm_client.py key_quarantine.py
git diff --check
```

## Working-tree caution

This nested repository already had many unrelated, uncommitted changes before this work. Do not reset, checkout, or broadly clean it. The relevant files for this handoff are:

- `cover_letter_generator.py`
- `gen_version.py`
- `llm_client.py`
- `key_quarantine.py`
- `tests/test_cover_letter_narrative.py`
- `tests/test_llm_fallback.py`
- `tests/test_key_quarantine_cooldown.py`
- `HANDOFF.md`

No commit has been made.
