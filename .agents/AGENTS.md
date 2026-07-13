# AGENTS.md — Job Intelligence System

Project-scoped rules for AI agents working in this directory.
These complement the global `AGENTS.md` at `/home/kz003/atelier/AGENTS.md`.

---

## Project Overview

This is a **local-first job search pipeline** for Kazuki Yunome.
It scrapes, scores, and generates tailored CVs and cover letters using a local LLM (Ollama).
See `README.md` for full architecture.

---

## Key Files

| File | Role |
|------|------|
| `run.py` | Orchestration. Entry point for the full pipeline. |
| `analyzer.py` | LLM-based skill/salary/seniority extraction per job. |
| `matcher.py` | Weighted scoring engine. Skill maps and synonym tables live here. |
| `cv_generator.py` | Generates tailored CV markdown. Contains contact info template. |
| `cover_letter_generator.py` | Generates tailored CL markdown. Contains contact info template. |
| `profile/skills.md` | Kazuki's canonical skill list with proficiency levels. Source of truth for scoring. |
| `profile/contact.md` | Correct contact details. Always use `kazukiyunome@gmail.com`. |
| `config.yaml` | Keywords, locations, filters, scoring weights. |

---

## Critical Rules

### 1. Email address

The correct email is **`kazukiyunome@gmail.com`**.
`junoyuno55@gmail.com` is obsolete. Never use it. Check both generators if in doubt.

### 2. Skill keyword matching — use word boundaries

When searching for skill keywords in free text (job descriptions, profile text), always use
word-boundary regex, not bare substring `in`:

```python
import re
if re.search(r'\b' + re.escape(keyword) + r'\b', text, re.IGNORECASE):
    ...
```

Never use `keyword in text` — short keywords (`c`, `go`, `hr`, `lab`) will match inside
unrelated longer words (`collaborative`, `laboratory`, `labor`), causing false positives.

### 3. Skill synonym mapping is in `matcher.py`

`SKILL_SYNONYMS` dict maps aliases → canonical skill name.
`SKILL_LEVELS` dict maps canonical name → proficiency float (0–1).

When adding a new skill or synonym, update **both** dicts AND `profile/skills.md`.
The three must stay in sync.

### 4. Prototyping ≠ Agile

These are separate skills with different levels:
- `Prototyping` → Advanced (0.9) — core creative/technical practice
- `Agile` → Intermediate (0.6) — process methodology, not a specialty

Do not merge them into one.

### 5. Obsidian wikilink format for cross-links

Generated markdown uses **bare filename wikilinks** (no extension, no path):
```yaml
match_report: "[[Wordsmith AI - Product Designer]]"
cv: "[[CV - Wordsmith AI - Product Designer]]"
cover_letter: "[[CL - Wordsmith AI - Product Designer]]"
```

Do not use relative markdown links (`[text](../path/file.md)`) in frontmatter.
Obsidian resolves bare `[[Name]]` across the vault automatically.

### 6. Import shadowing in `run.py`

All imports must stay at the **top of the file** (module level).
Never add `from X import Y` inside `main()` or any other function —
Python will treat the name as local for the entire function scope, causing
`UnboundLocalError` in code paths that don't reach the import statement.

### 7. Output directory structure

```
10_output/
├── 00_matches/   ← Match report .md files
├── 10_cvs/       ← CV .md files
├── 10_cover-letters/  ← Cover letter .md files
└── 20_pdfs/      ← PDF exports
```

Do not move or rename these directories — Obsidian Dataview queries depend on them.

### 8. Profile is source of truth, not generators

The generators (`cv_generator.py`, `cover_letter_generator.py`) pull from files under
`profile/`. If personal info (name, email, phone, address, skills) needs updating,
update the profile files first, then verify the generators still reference them correctly.

---

## Known Gotchas

- **`--from-saved` skips scraping** — use this to reanalyze without re-running Playwright.
- **`--reanalyze` regenerates all outputs** — safe to run, but slow (~0.5s/job × 500 jobs).
- **`00_saved/` is a staging area** — raw scraped JSON lives here before analysis.
- **Ollama must be running** (`ollama serve`) before any analyzer or generator call.
- **The `app.py` Streamlit UI** is a separate entry point for manual browsing/filtering.

---

## Git

This repo was not pushed regularly during the July 2026 session.
When pushing, remember to check `git status` — `00_saved/` and `10_output/` are untracked
(not in `.gitignore` by default — confirm before committing large output directories).
