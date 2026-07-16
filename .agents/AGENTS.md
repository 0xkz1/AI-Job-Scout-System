# AGENTS.md — AI Job Scout System

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

This applies to ALL keyword classification, not just skills. On 2026-07-16 substring
matching in `analyzer.py` was found to have misclassified 124/305 jobs' experience level
("lead" matched "**Lead**ing video game company" → senior) and 192/305 employment types
("intern" matched "inter**n**ationally" → internship), silently filtering good jobs out.
Use `_kw_search()` in `analyzer.py`.

### 2b. Experience level classification is TITLE-ONLY (user instruction)

`classify_experience_level()` in `analyzer.py` must classify from the job **title only** —
never scan the description. Description text is full of trap phrases ("work with senior
stakeholders", "5 years of company history") that misclassify. Titles without a level word
return `"unknown"`, which (a) triggers the LLM fallback in `analyze_job()` — the LLM reads
the description WITH context, and (b) passes the level filter (benefit of the doubt).
This was instructed by Kazuki before 2026-07-16 but a previous agent never landed it; do
not "improve" it back to description scanning.

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

---

## 2026-07-14 追加ルール

### 9. 説明文なしのジョブはマッチ分析しない

説明文 (`description`) が空のジョブに対して LLM 分析を実行すると、
スコアが過剰に高い/低い値になり、ミスリードを引き起こす。

`run.py` では以下のガードが実装済み:
- 説明文が空 → LLM 分析・サマリー生成・CV/CL 生成を全てスキップ
- パイプライン終了時に WARNING 一覧を出力

説明文が取れていないジョブを再分析したい場合は `re_scrape_morgan.py` を参考に
対象ジョブ専用の強制再スクレイプスクリプトを作成すること。

### 10. Reed の説明文取得は requests + JSON-LD が正解

Reed のジョブページでは `<script type="application/ld+json">` に
完全な `JobPosting` スキーマが含まれている。

Playwright を使う必要はない。`requests` で同期取得し BeautifulSoup でパースする:

```python
resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 ..."})
soup = BeautifulSoup(resp.text, "html.parser")
for tag in soup.find_all("script", type="application/ld+json"):
    data = json.loads(tag.string or "{}")
    if data.get("@type") == "JobPosting":
        description = data.get("description", "")
        break
```

### 11. プロファイル MD が CV の Single Source of Truth

`cv_generator.py` に PROFILE / CORE STRENGTHS / TECHNICAL TOOLKIT を直書きしない。
これらは `00_Kazuki/career/cv/profile/{role_type}.md` の各セクションから動的ロードする:

```
## Profile        → get_profile(role_type)
## Core Strengths → get_strengths(role_type)
## Technical Toolkit → get_toolkit(role_type)   ← 2026-07-14 追加
```

`## Technical Toolkit` セクションがない場合は `DEFAULT_TECHNICAL_TOOLKIT` にフォールバック。
新しいロールタイプを追加する場合は `.md` ファイルを追加するだけでよい。

### 12. LLM の挙動はソースデータで制御する（プロンプトハックより優先）

LLM の分析結果がおかしい場合、まずプロンプトに `Note: ...` を追加したくなるが、
**ソースデータ（ethos.md / profile/*.md）を正しく記述することを優先すること。**

例: コンテキスト分析が「ローカルファーストとエンタープライズは相容れない」と判断した場合
→ `ethos.md` に `Professional Pragmatism` セクションを追加して事実を明示する
→ プロンプトのガイドライン注記は補助として残してよい

### 13. python3 コマンドがターミナルで詰まる場合の回避策

バックグラウンドタスクで `python3 -c "..."` が「Last progress: never」で詰まる場合:
- `grep_search` を使い JSON を直接検索（python3 なしで確認）
- `view_file` で JSON の先頭数十行を直接読む
- `RunPersistent: true` のターミナルを使い回す（一度確立した Terminal ID は安定している）
- `WaitMsBeforeAsync` は 8000ms 以上に設定する
