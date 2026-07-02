# Career Intelligence System

**An end-to-end, local-first job search pipeline** — scrape hundreds of listings, score them against your profile with a local LLM, and auto-generate tailored CVs and cover letters for every match. All running on your own hardware, zero API costs.

```python
# One command runs the full pipeline
python run.py --reanalyze

# → Scrape  → Analyze  → Match  → Generate CV  → Generate Cover Letter
#    507 jobs   507 jobs   481 reports   297 CVs       297 cover letters
```

---

## Why This Exists

Job hunting is a numbers game, but manual tailoring doesn't scale. This pipeline:

1. **Scrapes** Indeed UK and LinkedIn at scale (500+ listings per run)
2. **Analyzes** each job with a local LLM (Ollama Gemma-4-26b) — salary parsing, skill extraction, seniority classification
3. **Matches** each job against your profile using weighted scoring (skills/embedding similarity, experience, location, salary)
4. **Generates** a tailored CV and cover letter for every job scoring ≥ 50%
5. **Outputs** Obsidian-ready Markdown with YAML frontmatter — queryable via Dataview

**No API keys. No cloud costs. No rate limits.** Everything runs locally on an RTX 5080.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     config.yaml                             │
│        (keywords, locations, filters, weights)              │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
              ┌────────────────┐
              │     run.py     │          ← Orchestration layer
              │   (347 lines)  │
              └──┬──────────┬──┘
         ┌────────┘        └────────┐
         ▼                          ▼
  ┌──────────────┐          ┌──────────────┐
  │ scraper_     │          │ scraper_     │
  │ indeed.py    │          │ linkedin.py  │   ← Playwright stealth scraping
  │ (305 lines)  │          │ (382 lines)  │
  └──────┬───────┘          └──────┬───────┘
         │                         │
         └──────────┬──────────────┘
                    ▼
         ┌──────────────────┐
         │   analyzer.py    │          ← Ollama LLM extracts:
         │   (644 lines)    │            skills, salary, seniority, work style
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │    filter.py     │          ← Config-based filtering
         │   (95 lines)     │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
         │   matcher.py     │          ← Weighted scoring engine
         │   (794 lines)    │            (embeddings, TF-IDF, 4-axis match)
         └────────┬─────────┘
                  │
         ┌────────┴────────┐
         ▼                 ▼
  ┌──────────────┐  ┌──────────────────┐
  │ cv_generator │  │ cover_letter_    │  ← Ollama generates tailored
  │    .py       │  │ generator.py     │    Markdown CVs / cover letters
  │ (133 lines)  │  │ (141 lines)      │
  └──────────────┘  └──────────────────┘
         │                 │
         └────────┬────────┘
                  ▼
         ┌──────────────────┐
         │     output/      │          ← Obsidian-ready Markdown
         │   (Dataview)     │            YAML frontmatter + cross-links
         └──────────────────┘

                    ┌──────────────────┐
                    │     app.py       │          ← Streamlit UI
                    │   (483 lines)    │            2 tabs: Scraper + Weights
                    └──────────────────┘
```

---

## Match Scoring

Each job is scored on four weighted axes:

| Axis         | Default Weight | Method                                           |
| ------------ | --------------- | ------------------------------------------------ |
| **Skills**   | 40%             | Skill name embedding similarity (all-MiniLM) + TF-IDF overlap |
| **Experience** | 25%           | Seniority level matching (entry/mid/senior/director) |
| **Location** | 20%             | City match + remote-friendliness bonus            |
| **Salary**   | 15%             | Salary range vs. minimum expectation              |

Weights are **adjustable in real-time** via the Streamlit UI — no code changes needed.

### Tier System

| Tier | Score Range | Icon | CV/CL Generated? |
| ---- | ----------- | ---- | ---------------- |
| Strong | 80%+ | 🟢 | ✅ Yes |
| Good | 60–79% | 🟡 | ✅ Yes |
| Partial | 40–59% | 🟠 | ✅ If ≥ 50% threshold |
| Weak | < 40% | 🔴 | ❌ No |

### Sample Match Report

```markdown
---
match_score: 0.72
match_score_pct: 72
tier: 🟡Good
company: "Example Corp"
title: "Creative Technologist"
location: "Edinburgh"
skills_score: 0.81
experience_score: 0.75
location_score: 1.00
salary_score: 0.45
url: "https://indeed.com/..."
---

# Match Report: Creative Technologist — Example Corp

**Score: 72%  🟡 Good**

## 📊 Breakdown
| Category | Score | Weight |
|----------|-------|--------|
| Skills   | 81%   | 40%    |
| ...

## 📎 Related Documents
- **CV:** [ExampleCorp_Creative_Technologist_CV](../00_cvs/ExampleCorp_Creative_Technologist_CV.md)
- **Cover Letter:** [ExampleCorp_Creative_Technologist_CL](../00_cover-letters/ExampleCorp_Creative_Technologist_CL.md)
```

---

## Streamlit UI

Two tabs in a single app (`app.py`, 483 lines):

| Tab | Function |
| --- | -------- |
| **🔍 Scraper** | Edit keywords/locations/salary/sites, run scraper, view results table |
| **🎯 Weights** | Drag sliders to adjust scoring weights, regenerate all match reports live |

```bash
# Launch
cd career/scraper
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
```

---

## Tech Stack

| Layer | Technology | Why |
| ----- | ---------- | --- |
| Scraping | Playwright + stealth | Anti-bot evasion, headless browsing |
| LLM Analysis | Ollama (Gemma-4-26b) | Local, free, private — runs on RTX 5080 |
| Skill Matching | Sentence Transformers (all-MiniLM-L6-v2) | Embedding similarity beats keyword matching |
| Scoring | Custom weighted engine | 4-axis, adjustable via UI |
| CV/CL Generation | Ollama (Gemma-4-26b) | Tailored per job, no templates |
| UI | Streamlit | Lightweight, 1-file, no build step |
| Output | Obsidian Markdown + Dataview | Queryable knowledge base |
| Scheduling | Cron | Nightly scrape + reanalyze |

---

## Quick Start

```bash
# 1. Install Python dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Install Ollama + model
ollama pull gemma3:26b

# 3. Configure search
#    Edit config.yaml — keywords, locations, salary, sites

# 4. Run full pipeline
python run.py                    # Scrape + analyze + match + generate
python run.py --reanalyze        # Re-score only (no scraping)

# 5. Launch UI (optional)
streamlit run app.py --server.port 8501
```

### Configuration (`config.yaml`)

```yaml
keywords:
  - Creative Technologist
  - Technical Artist
  - Web Developer

locations:
  - Edinburgh
  - Glasgow
  - Remote

min_salary_gbp: 26000
match_score_threshold: 0.50    # Generate CV/CL only for ≥ 50% match

sites:
  - indeed
  - linkedin
```

---

## File Overview

| File | Lines | Role |
| ---- | ----- | ---- |
| `matcher.py` | 794 | Scoring engine — skill embeddings, 4-axis match, report generation |
| `analyzer.py` | 644 | Ollama-powered job analysis — skills, salary, seniority, work style |
| `app.py` | 483 | Streamlit UI — scraper tab + weights tab |
| `run.py` | 347 | Orchestration — scrape → analyze → filter → match → CV → CL |
| `scraper_saved.py` | 576 | Scrape favorited/saved jobs from Indeed + LinkedIn |
| `scraper_linkedin.py` | 382 | LinkedIn scraper with cookie persistence |
| `scraper_indeed.py` | 305 | Indeed UK scraper with Playwright stealth |
| `weight_adjuster.py` | 243 | Standalone weight tuning utility (integrated into app.py) |
| `cover_letter_generator.py` | 141 | Ollama-powered cover letter generation |
| `cv_generator.py` | 133 | Ollama-powered CV generation |
| `filter.py` | 95 | Config-based job filtering |
| `check_integrity.py` | 176 | Validate output consistency |
| **Total** | **~4,420** | |

---

## Output Structure

```
output/
├── 00_matches/          # Match reports (.md, YAML frontmatter, Dataview-ready)
├── 00_cvs/              # Tailored CVs (one per match ≥ threshold)
├── 00_cover-letters/    # Tailored cover letters (one per match ≥ threshold)
├── 00_saved/            # Saved/favorited jobs
├── _analyzed.json       # Full analyzed job data
└── _index.json          # Index of all scraped jobs
```

### Obsidian Dataview Integration

All outputs are Markdown with YAML frontmatter — queryable live in Obsidian:

```dataview
TABLE match_score_pct, tier, company, location
FROM "02-career/matches"
WHERE match_score_pct >= 70
SORT match_score_pct DESC
```

```dataview
TABLE tier, count() as count
FROM "02-career/matches"
GROUP BY tier
```

---

## Real Results

| Metric | Value |
| ------ | ----- |
| Jobs scraped per run | ~507 |
| Match reports generated | 481 |
| Tailored CVs generated | 297 |
| Tailored cover letters generated | 297 |
| Cost per run | £0 (all local LLM) |
| Hardware | RTX 5080, Ubuntu, Ollama |
| Scoring latency | ~0.5s per job (Ollama inference) |

---

## Cron Scheduling

Nightly automated runs:

```bash
# Every night at 02:00 — scrape new jobs + reanalyze
0 2 * * * cd /path/to/scraper && python3 scraper_saved.py && python3 run.py --site indeed --pages 5
```

---

## Philosophy

- **Local-first** — no API keys, no cloud costs, no rate limits
- **Privacy** — your CV, profile, and job data never leave your machine
- **Composable** — each stage is a standalone module; swap any part
- **Observable** — every output is human-readable Markdown with structured metadata

---

## Future Enhancements

- [ ] Multi-language support (JP/EN job markets)
- [ ] Company research enrichment (Glassdoor, companies house)
- [ ] Application status tracking via Obsidian Dataview
- [ ] PDF export for CVs and cover letters
- [ ] Streaming LLM generation (view CV as it's written)

---

*Built by [Kazuki Yunome](https://github.com/0xkz1) — Artist + System Engineer. Runs on a custom Ubuntu PC with an RTX 5080.*