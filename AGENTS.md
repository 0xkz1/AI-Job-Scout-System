# AGENTS.md — Opencode Minimal Loop

These rules are loaded by opencode before loop work.

## Loop Mode

- Start in L1 report-only mode.
- Read `STATE.md` before any triage.
- Update `STATE.md` after every loop run.
- Do not edit source code until the human explicitly enables L2.

## Safety

- Never push or merge without human approval.
- Never edit `.env`, `.env.*`, `auth/`, `payments/`, `secrets/`, or `credentials/`.
- Use a git worktree for every code-changing attempt.
- Max 3 fix attempts per item; escalate after that.

## Architecture & Multi-Agent Boundary (Decision: 2026-09-20)

### 3-Layer Execution Model

1. **Layer 1: Deterministic Core & High-Throughput Batch (L1 Nightly Scout)**
   - **`no_agent: true` / Sub-agent spawns: 0**.
   - Pure Python code (`run.py`, `filter.py`, `matcher.py`). Regex and deterministic maths only.
   - Handles scraping, deduplication, deterministic salary/date math, and keyword classification in sub-second passes.
   - Do NOT run autonomous agents inside this high-volume data loop.
   - Scheduled under the Hermes **`archivist`** profile, not crontab: `job-scout-early`
     (02:00) and `job-scout-late` (04:30) are two runs with separate deadlines, and
     `hermes cron list` only shows them with `HERMES_HOME` set to that profile.
   - **Jev is NOT in this layer.** `jis_jev_judge.py` is imported in exactly one
     place, `jis_hermes_bridge.py` (L3). Its `check_sponsorship_jev` and
     `classify_role_jev` have no callers at all.
   - See [docs/JIS_AND_JEV.md](docs/JIS_AND_JEV.md).

2. **Layer 2: Autonomous Scraper Repair (L2 Loop)**
   - Assigned to Hermes **`builder`** profile.
   - Triggers when a scraper runs clean with zero results (e.g. site DOM changes).
   - Must execute in an isolated `git worktree` branch (`loop/<site>-<date>`).
   - Uses `dispatch_worker.py` (Codex / Claude / OpenCode / LiteLLM Gateway fallback).
   - Verified with tests before human review; never merges automatically to main.

3. **Layer 3: Autonomous High-Match Document Review (L3 Kanban Workflow)**
   - High-match jobs (score ≥ 0.70) are pushed to Hermes Kanban (`jis` board) via `jis_hermes_bridge.py`.
   - **L1 → L3 Direct**: `jis_hermes_bridge.py` calls `cv_generator.generate_cv()` and `cover_letter_generator.save_cover_letter()` **directly** (pure Python, zero LLM tokens, sub-second). No `writer` profile needed — the generators are deterministic template assemblers.
   - **`review-editor`**: Performs strict factual audit against `letter_facts_v1.md`, flags hallucinations or ungrounded claims, and requests changes or approves.
   - **`fast_pre_audit_documents` is not a hallucination gate.** Measured 2026-09-23:
     appending fabricated claims (a Coca-Cola rebrand, an MIT PhD, a Cannes Lions
     Grand Prix) to a real CV and cover letter moved `has_hallucinations_prob` from
     0.09 to 0.09, and it scored a degraded `assembled-static` letter the same as two
     tailored ones. It only fires when a document is replaced *entirely* by the
     fabrication, which is not how hallucinations arrive. Treat its number as
     unvalidated and leave `review-editor` as the real check.
   - Jev runs only when `JIS_JEV_MODE` is set to `shadow` or `on`. The default is
     `off`, so an installed SDK and a present API key do not by themselves change
     what the pipeline does (ADR-015 P0).
   - Human role: Final review and application submission (Apply button). Eliminates manual button-clicking in Streamlit.
   - **Design Decision (2026-09-20)**: The `writer` profile was removed from the JIS pipeline. It consumed ~28k LLM tokens per job just to "think about calling Python functions" and repeatedly hit API rate limits. The generators contain zero LLM calls.
   - **System 1 (Reflex) vs System 2 (Deep Thought)**:
     - **Jev (System 1)**: Sub-second reflex engine. Provides typed probabilistic judgments (`Choice`, `Noul`, `Score`) for L1 invariants and pre-filters with near-zero tokens. Jev cannot serve as Hermes's chat model (it generates no text/tool calls).
     - **Hermes Profile (System 2)**: Deep thought engine. Only activated at L3 for high-value creative and contextual review, completely freed from mechanical verification tasks.
