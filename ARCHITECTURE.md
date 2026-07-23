# AI Job Scout System — Architecture Spec

This document describes the system architecture, data flow, staging layer, and dynamic LLM components of the AI Job Scout System.

---

## 1. High-Level Architecture

The system is a multi-stage pipeline: **Scrape → Stage (00_saved/) → Analyze → Filter → Match → Generate CV/CL → Review (dialogue + apply)**.
It runs as a local service with a **Streamlit UI** on port `8501`, plus an unattended **nightly run** (Hermes cron → Telegram notification). All cognitive operations go through `llm_client.py`'s provider chain — **Mistral (cloud) → StepFun `step-3.5-flash` (cloud) → local Ollama (`gemma-4-26b`)** — falling through on rate limits, 5xx, timeouts, or missing API keys.

Generation reads from **reusable masters** (`career/cv/profile/*.md`, `projects/*.md`, `skill-toolkit/master.md`): each profile's frontmatter carries a per-role `role_title` / `role_tagline` that becomes the CV header, and the review subsystem can apply agreed fixes either to one generated document or back to these masters.

![System architecture](docs/architecture.svg)

```mermaid
flowchart TD
    %% ==== Core components ====
    subgraph UI["Streamlit WebUI (app.py) — 🔍Scraper / 🎯Weights / 👁Saved / 🧐Review / 📄PDF"]
        A1["Search Config / Filters<br/>(config.yaml)"]
        A2["Recent Results & Insights<br/>(re-analyze, metrics)"]
    end

    subgraph Nightly["Nightly Automation (02:00)"]
        N1["Hermes cron — archivist profile<br/>job_scout_nightly.sh"]
        N2["nightly_scout.py<br/>(diff vs last run → auto-review ≥80% → summary)"]
        N3["Telegram DM<br/>(Archivist bot, stdout = message)"]
    end

    subgraph Scrapers["Scrapers & Gathering"]
        S1["run.py (Main Runner)"]
        S2["scraper_indeed.py (Indeed)"]
        S3["scraper_linkedin.py (LinkedIn — interactive only)"]
        S5["scraper_reed / guardian / adzuna"]
        S4["scraper_saved.py (Bookmarks)"]
    end

    subgraph Staging["00_saved/ — Raw Staging"]
        ST1["_raw_indeed_*.json"]
        ST2["_raw_linkedin_*.json"]
        ST3["_saved_index.json"]
    end

    subgraph Analysis["Analysis & Alignment"]
        AN1["analyzer.py<br/>(Salary/Level Classification)"]
        AN2["matcher.py<br/>(Scoring & Philosophy Weighting)"]
        OL1["llm_client.py<br/>(Mistral → StepFun → Ollama)"]
    end

    subgraph Masters["career/cv/ — Reusable Masters"]
        M1["profile/*.md<br/>(role_title / role_tagline + Profile)"]
        M2["projects/*.md"]
        M3["skill-toolkit/master.md"]
    end

    subgraph DynamicGen["Dynamic Resume & Cover Letter Generator"]
        CVG["cv_generator.py (Dynamic CV)"]
        CLG["cover_letter_generator.py (Tailored CL)"]
        OL2["llm_client.py<br/>(Dynamic Experience Sorter)"]
    end

    subgraph Review["Review & Dialogue (reviewer.py)"]
        RV1["batch review<br/>(skips unchanged docs via reviewed_sha)"]
        RV2["annotation dialogue<br/>(user notes in Obsidian → LLM replies,<br/>sees masters + decisions ledger)"]
        RV3["per-fix apply<br/>(この文書のみ / 元ファイル+この文書 / 適用しない)"]
        RV4["review-decisions.md<br/>(settled-matters ledger — injected into every review)"]
    end

    subgraph Output["10_output/ — Analysis Results"]
        O1["_analyzed.json (All Jobs DB)"]
        O2["00_matches/*_match.md (Match Reports)"]
        O3["10_cvs/*_CV.md (Dynamic Resume)"]
        O4["10_cover-letters/*_CL.md (Cover Letter)"]
        O7["15_reviews/*_review.md<br/>(+ .pristine/ baselines, source_backups/)"]
        O5["20_pdfs/ (PDF exports)"]
        O6["_debug/ (Playwright screenshots)"]
    end

    %% ==== Data Flow Connections ====
    A1 -->|Read/Write| S1
    N1 -->|"unattended run (indeed/reed/guardian/adzuna)"| S1
    N1 --> N2
    N2 -->|new high matches only| N3
    S1 -->|Orchestrate| S2
    S1 -->|Orchestrate| S3
    S1 -->|Orchestrate| S5
    S4 -->|Manual saved| ST3

    S2 -->|Raw dump| ST1
    S3 -->|Raw dump| ST2

    ST1 -->|load_all_from_saved()| AN1
    ST2 -->|load_all_from_saved()| AN1
    ST3 -->|load_saved_from_index()| AN1

    AN1 <-->|Skill/salary extraction| OL1
    AN1 -->|Enriched Data| AN2
    AN2 -->|Save Match Details| O2

    %% ==== Generation Pipeline ====
    O2 -->|Job Details + Role Type| CVG
    O2 -->|Job Details + Role Type| CLG
    M1 -->|"header (get_header) + profile"| CVG
    M2 -->|project registry| CVG
    M3 -->|toolkit (role-ordered)| CVG

    CVG <-->|Rank 7 projects based on job description| OL2
    CVG -->|Generate CV| O3
    CLG -->|Generate Cover Letter| O4

    %% ==== Review Loop ====
    O3 --> RV1
    O4 --> RV1
    RV1 -->|findings + 修正案| O7
    O7 <-->|user annotates in Obsidian| RV2
    RV2 -->|"## 新規決定事項"| RV4
    RV4 -->|既決事項 injected| RV1
    RV3 -->|doc-level fix| O3
    RV3 -->|source-level fix<br/>(frontmatter excluded)| Masters

    classDef ui fill:#e3f2fd,stroke:#1565c0,stroke-width:2px;
    classDef scr fill:#fff3e0,stroke:#e65100,stroke-width:2px;
    classDef stg fill:#fce4ec,stroke:#c62828,stroke-width:2px;
    classDef ana fill:#efebe9,stroke:#4e342e,stroke-width:2px;
    classDef gen fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    classDef out fill:#f3e5f5,stroke:#4a148c,stroke-width:2px;
    classDef rev fill:#fffde7,stroke:#f9a825,stroke-width:2px;
    classDef ngt fill:#eceff1,stroke:#37474f,stroke-width:2px;
    classDef mst fill:#e0f2f1,stroke:#00695c,stroke-width:2px;

    class UI,A1,A2 ui;
    class Scrapers,S1,S2,S3,S4,S5 scr;
    class Staging,ST1,ST2,ST3 stg;
    class Analysis,AN1,AN2,OL1 ana;
    class DynamicGen,CVG,CLG,OL2 gen;
    class Output,O1,O2,O3,O4,O5,O6,O7 out;
    class Review,RV1,RV2,RV3,RV4 rev;
    class Nightly,N1,N2,N3 ngt;
    class Masters,M1,M2,M3 mst;
```

---

## 2. Three Pipeline Modes

The system has three entry points, all orchestrated by `run.py`:

| Mode | Command | Flow | Use Case |
|------|---------|------|----------|
| **Full scrape** | `run.py --site all` | scrape → `00_saved/` → analyze → `10_output/` | Nightly cron |
| **Staging reanalyze** | `run.py --from-saved` | `00_saved/` → analyze → `10_output/` | Rerun after matcher/config changes |
| **Manual saved** | `run.py --saved` | `scraper_saved.py` → `00_saved/` → merge → analyze → `10_output/` | Process LinkedIn bookmarks |

### Staging Layer (`00_saved/`)

All raw scraped data lands in `00_saved/` before analysis. This decouples gathering from processing:

- `_raw_indeed_{date}.json` — Indeed raw listings (from `scraper_indeed.py`)
- `_raw_linkedin_{date}.json` — LinkedIn search results (from `scraper_linkedin.py`)
- `_saved_index.json` — Manual bookmarks (from `scraper_saved.py`)

Functions in `run.py`:
- `save_raw_to_saved(jobs, source)` — writer (called by scrapers)
- `load_saved_from_index()` — reads `_saved_index.json` only
- `load_all_from_saved()` — reads all three sources, merges into one list

### Output Layer (`10_output/`)

Numeric prefixes enforce semantic ordering:

| Directory | Contents |
|-----------|----------|
| `00_matches/` | Match reports as `.md` with YAML frontmatter |
| `10_cvs/` | Tailored CVs (one per match ≥ threshold) |
| `10_cover-letters/` | Tailored cover letters |
| `15_reviews/` | LLM reviews (`*_review.md`), `.pristine/` dialogue baselines, `source_backups/`, `*.pre_apply.md` |
| `20_pdfs/` | PDF exports (per-company subdirectories) |
| `_debug/` | Playwright debug screenshots |
| `_analyzed.json` | Full analyzed job data |
| `_analyzed_full.json` | Full data with LLM context scores |
| `_nightly_state.json` | Seen-URL state for the nightly diff (what counts as "new") |

### Frontmatter Schema

Every match report carries these fields (Dataview-queryable in Obsidian):

| Field | Example | Purpose |
|-------|---------|---------|
| `source` | `indeed` / `linkedin` / `manual` | Origin platform |
| `type` | `auto` / `manual` | Capture method |
| `saved_at` | `2026-07-11` | Date added to system |
| `match_score_pct` | 0–100 | Overall match score |
| `tier` | `Strong` / `Good` / `Partial` / `Weak` | Tier label |
| `skills_score` | 0–100 | Skill embedding similarity |
| `experience_score` | 0–100 | Seniority level |
| `location_score` | 0–100 | City + remote match |
| `salary_score` | 0–100 | Salary vs minimum |
| `context_score` | 0–100 | Brand/ethos alignment (LLM) |
| `company` | `"Example Corp"` | Company name |
| `title` | `"Creative Technologist"` | Job title |
| `location` | `"Edinburgh"` | Job location |
| `url` | `"https://..."` | Original listing URL |

---

## 3. Dynamic Experience Generator (Ollama Pipeline)

This section highlights how CVs are dynamically tailored for each specific job posting via the `llm_client.py` provider chain (Mistral → StepFun → local `gemma-4-26b`).

```mermaid
sequenceDiagram
    autonumber
    participant Pipeline as Generation Pipeline (run.py)
    participant CVG as cv_generator.py (generate_cv)
    participant OLL as llm_client (Mistral→StepFun→Ollama)

    Pipeline->>CVG: Call generate_cv(role_type, job_title, job_description)
    alt Job description available (len > 50 chars)
        CVG->>CVG: Retrieve all 7 projects from Project Registry (PROJECTS)
        CVG->>OLL: Send Job Details + 7 Projects Registry
        Note over OLL: Prompt: Select 3-5 most relevant projects,<br/>order by relevance, write verbatim

        alt Ollama responds successfully
            OLL-->>CVG: Ordered & structured EXPERIENCE section
        else Ollama connection fails / timeout
            CVG->>CVG: Fallback: Load static experience list from STATIC_EXPERIENCE[role_type]
        end
    else No job description (CLI direct run)
        CVG->>CVG: Load static experience list from STATIC_EXPERIENCE[role_type]
    end
    CVG->>CVG: Merge selected Experience section + Profile + Core Strengths
    CVG-->>Pipeline: Complete Tailored Resume (CV)
```

---

## 4. Project Registry & Role Mappings

Projects are declared as modular data fragments in `cv_generator.py` under the `PROJECTS` registry.

| Project ID | Project Title | Key Focus | Primary Target Roles |
|------------|---------------|-----------|----------------------|
| `portfolio_website` | Portfolio Website Design & Development | HTML/CSS/JS, Sanity CMS, AI-assisted dev | `web_developer`, `creative_technologist` |
| `independent_development` | Independent Dev & Workflow Support | Python, PostgreSQL, Selenium, Web Scraping | `development_support`, `data_analysis`, `web_developer` |
| `linux_systems` | Linux Systems & Process Management | Linux, Ubuntu, tmux, process monitoring | `development_support`, `web_developer` |
| `terra_drone` | Sales & Cross-functional Support | Communication, technical brochures, sales | `general`, `development_support` |
| `feral` | Creative Workflow — "Feral" | Obsidian Canvas, ComfyUI, Stable Diffusion, local LLMs | `creative_technologist`, `technical_artist` |
| `arch_viz` | Architectural Visualization | Blender, ComfyUI, Obsidian | `creative_technologist`, `technical_artist` |
| `hive_floral_pod` | Design Competition — "Hive Floral Pod" | Procreate, Blender, 3D visual proposal | `creative_technologist`, `technical_artist` |

### Static Mapping Fallbacks (Ollama Offline)

| Role | Project Order |
|------|---------------|
| `web_developer` | Portfolio Website → Independent Dev → Linux Systems |
| `development_support` | Independent Dev → Linux Systems → Terra Drone |
| `data_analysis` | Independent Dev → Terra Drone |
| `creative_technologist` | Feral → Arch Viz → Hive Floral Pod → Portfolio Website |
| `technical_artist` | Feral → Arch Viz → Hive Floral Pod |
| `general` | All projects in standard chronological order |

---

## 5. Key Design Decisions

### Why a Staging Layer?

1. **Decouple scrape from analyze** — If the matcher changes, `--from-saved` reprocesses cached raw data without re-scraping (avoids rate limits)
2. **Raw data preservation** — `_raw_indeed_*.json` lets you debug parser changes or re-run with different analyzer versions
3. **Merge manual + auto** — Bookmarks from `scraper_saved.py` join the same pipeline as scraped listings, deduplicated by URL

### Why Numeric Prefixes?

`00_` = raw/staging, `10_` = analysis, `20_` = final artifacts. Alphabetical sort becomes semantic sort — no need to remember directory names.

### Why Frontmatter + Dataview?

Structured YAML in `.md` files means:
- No separate database — Obsidian's FTS + Dataview is the query layer
- Human-readable without tooling
- Cross-linkable with other vault notes

---

## 6. Review & Dialogue Subsystem (`reviewer.py`)

Generated CVs/CLs are reviewed by LLM against the job posting and the candidate's verified facts. Reviews are a **dialogue**, not one-shot output:

1. **Batch review** — Streamlit's 🧐 Review tab runs `run_review()` per document; a `reviewed_sha` frontmatter hash skips unchanged docs on later batches. Output: `15_reviews/<doc>_review.md` with findings in three categories (❗事実 / 🎯求人適合 / ✍️文体), each with a verbatim quote and a 修正案.
2. **Annotation dialogue** — The user annotates the review in Obsidian (questions, objections, agreements). `detect_annotations()` finds the added lines by diffing against a pristine baseline (`15_reviews/.pristine/`). 「💬 追記に回答」 sends the dialogue to the LLM, which replies inline (`> 💬 回答: …`), revises 修正案 where the user is right, and holds its ground where not. The prompt includes the **reusable master files** traced to the findings, so 「参照元から編集」 requests are grounded in the actual source text.
3. **Decisions ledger** — Matters settled in dialogue are appended to `career/cv/review-decisions.md` (`## 新規決定事項` → ledger). The ledger is injected into **every future review**, so a settled point is never re-flagged.
4. **Per-fix apply with destination choice** — Each parsed 修正案 offers: **この文書のみ** (default) / **元ファイル+この文書** (only offered when the quote matches a master's body verbatim) / **適用しない**. Applies are deterministic exact-match replacements; backups go to `*.pre_apply.md` (doc) and `15_reviews/source_backups/` (masters).

Guard rails:
- **Masters must not drift per job posting** — source-level apply is an explicit per-fix opt-in; job-specific tailoring stays in the generated doc.
- **Frontmatter is never auto-replaced** — a quote matching only a master's frontmatter (e.g. the settled `role_tagline` brand line) is excluded from source apply.
- Dialogue buttons do **not** require the doc to be unedited (`is_cur`) — applying fixes edits the doc, and the dialogue must survive that.

Note for maintainers: Streamlit auto-reloads `app.py` but **not** imported modules — after editing `reviewer.py` (etc.), restart the server.

---

## 7. Nightly Automation & Telegram Notification

An unattended nightly run (02:00 JST) is scheduled in the **Hermes archivist profile's cron** (`~/.hermes/profiles/archivist/cron/jobs.json`, script `job_scout_nightly.sh`, `no_agent: true`):

1. `scraper_saved.py` + `run.py --site indeed/reed/guardian/adzuna` (LinkedIn is excluded — it needs an interactive login; its saved jobs still enter via staging). The full pipeline runs: scrape → analyze → match → generate CV/CL.
2. `nightly_scout.py` post-processing: diffs `_analyzed.json` against `_nightly_state.json` (seen URLs) → picks **new** matches ≥ `SCOUT_NOTIFY_MIN` (0.70) → auto-reviews the CV/CL of those ≥ `SCOUT_REVIEW_MIN` (0.80) → prints a summary to stdout.
3. Delivery: the job's stdout **is** the Telegram message, sent via the archivist profile's own gateway/bot to the configured DM (`deliver: telegram:<chat_id>`). Empty stdout = silent night. All scraper logs go to `10_output/_nightly_scout.log` only.

Script timeout is raised to 7200 s (`cron.script_timeout_seconds` in the archivist profile's `config.yaml`) — four sites × 5 pages exceeds the 3600 s default.
