"""CV/CL review — an LLM as proofreader, never as rewriter.

Runs AFTER the user's manual edits, BEFORE PDF export: checks the current
document against the job posting and the candidate's real profile, and returns
a findings list (factual issues, job-fit gaps, style). The human edit is
always the final word — this module never modifies the document itself.

Reviews are saved to 10_output/15_reviews/ as Obsidian notes (numbered
between 10_cvs/10_cover-letters and 20_pdfs to mirror the workflow order:
generate → hand-edit → review → export) and linked from the match report
frontmatter (cv_review / cl_review).
"""

import hashlib
import os
from datetime import date
from pathlib import Path

from llm_client import call_llm
from matcher import USER_PROFILE_DIR, _load_persona_summary

ROOT = Path(__file__).resolve().parent
REVIEWS_DIR = ROOT / "10_output" / "15_reviews"

# Review deserves a stronger model than bulk analysis: it runs only on
# shortlisted applications and its output gates what actually gets sent.
REVIEW_MODEL = os.environ.get("REVIEW_MODEL", "mistral-medium-latest")


def _load_skills_md() -> str:
    p = USER_PROFILE_DIR / "skills.md"
    try:
        return p.read_text(encoding="utf-8")[:3000]
    except Exception:
        return ""


REVIEW_PROMPT = """You are a rigorous UK hiring reviewer. Review ONE application document ({doc_kind}) against the job posting and the candidate's verified profile.

## JOB POSTING
Company: {company}
Title: {job_title}
Description (excerpt):
{job_description}

## CANDIDATE — VERIFIED FACTS (authoritative; anything not supported here is unverified)
{persona}

### Verified skills table (source of truth for skill claims)
{skills}

## DOCUMENT UNDER REVIEW ({doc_kind})
{document}

## YOUR TASK
Produce a findings list in markdown. Do NOT rewrite the document.

LANGUAGE RULES (important):
- Write ALL explanations, problem descriptions, and the verdict in JAPANESE.
- Quote the document's original ENGLISH sentences verbatim when referencing a passage.
- Suggested replacement sentences must be in ENGLISH (they will be pasted into the English document as-is).

Categories:

### ❗ 事実
検証済み事実で裏付けられない主張（捏造・誇張リスク）。該当箇所を英語原文のまま引用すること。

### 🎯 求人適合
求人票の主要な要求のうちドキュメントが触れていないもの、および今回の求人に無関係な記述。

### ✍️ 文体
UK英語の問題、クリシェ、冗長表現、日付の不整合、不自然な言い回し。各指摘に英語原文の引用を付けること。

各指摘の形式: 英語原文の引用 → 何が問題か（日本語）→ 具体的な修正案（英語の置き換え文。候補者がそのまま採用/却下できるもの）。
指摘がないカテゴリには「問題なし」と書くこと。
最後に2〜3文の **総評**（日本語）: 修正案を反映すればこのドキュメントは提出可能か。
具体的かつ正直に — 社交辞令だけの空のレビューは誰の役にも立たない。"""


def run_review(doc_kind: str, md_path: Path, job: dict) -> Path:
    """Review a CV or CL markdown against its job. Returns the review file path.

    doc_kind: "CV" or "CL". job: dict with company/title/description.
    Raises on LLM failure — the caller surfaces the error; no silent fallback,
    a review that silently degrades to a weak model would be worse than none.
    """
    document = md_path.read_text(encoding="utf-8")
    doc_sha = hashlib.sha1(document.encode()).hexdigest()

    prompt = REVIEW_PROMPT.format(
        doc_kind=doc_kind,
        company=job.get("company", ""),
        job_title=job.get("title", ""),
        job_description=(job.get("description") or job.get("snippet") or "")[:3500],
        persona=(_load_persona_summary() or "")[:2500],
        skills=_load_skills_md(),
        document=document[:7000],
    )
    review_body = call_llm(
        messages=[{"role": "user", "content": prompt}],
        system_prompt=(
            "You are a rigorous, honest application-document reviewer. "
            "Output only the requested markdown findings — never a rewritten document."
        ),
        temperature=0.2,
        max_tokens=2000,
        model=REVIEW_MODEL,
    )

    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    stem = md_path.stem  # e.g. Wordsmith_AI_Product_Designer_CV
    review_path = REVIEWS_DIR / f"{stem}_review.md"
    base = stem[:-3] if stem.endswith(("_CV", "_CL")) else stem
    frontmatter = f"""---
type: "review"
doc: "[[{stem}]]"
match_report: "[[{base}]]"
reviewed_sha: "{doc_sha}"
review_model: "{REVIEW_MODEL}"
reviewed_at: {date.today().isoformat()}
---

"""
    review_path.write_text(frontmatter + review_body.strip() + "\n", encoding="utf-8")
    return review_path


def parse_review_fixes(review_path: Path) -> list[tuple[str, str]]:
    """Extract (original_quote, replacement) pairs from a review's findings.

    The review format quotes the document verbatim (**"..."**) and offers a
    replacement after 修正案:/Fix:. Only pairs with BOTH parts present are
    returned — applying them is then a deterministic string replacement, no
    second LLM call, no chance of the model rewriting anything else.
    """
    import re
    text = review_path.read_text(encoding="utf-8")
    pairs = []
    # Findings look like:  - **"<quote>"** ... 修正案: **"<fix>"**  (fix may
    # use *...* or **...**, with or without quotes)
    blocks = re.split(r"\n- ", text)
    for block in blocks:
        mq = re.match(r'\*\*"(.+?)"\*\*', block.strip(), flags=re.DOTALL)
        if not mq:
            continue
        mf = re.search(
            r'(?:修正案|Fix)\s*[::]\s*\*{1,2}"?(.+?)"?\*{1,2}(?:\s|$)',
            block, flags=re.DOTALL,
        )
        if not mf:
            continue
        original = mq.group(1).strip()
        replacement = mf.group(1).strip()
        if original and replacement and original != replacement:
            pairs.append((original, replacement))
    return pairs


def apply_review_fixes(md_path: Path, review_path: Path) -> tuple[int, list[str]]:
    """Apply the review's suggested replacements to the document.

    Deterministic: each quoted original is replaced only where it matches the
    document verbatim. Returns (applied_count, unmatched_originals) — the
    unmatched ones need manual editing (the model paraphrased its quote, or
    the doc changed since the review). A pre-apply backup is written next to
    the review as <stem>.pre_apply.md.
    """
    doc = md_path.read_text(encoding="utf-8")
    backup = REVIEWS_DIR / f"{md_path.stem}.pre_apply.md"
    applied, unmatched = 0, []
    for original, replacement in parse_review_fixes(review_path):
        if original in doc:
            doc = doc.replace(original, replacement, 1)
            applied += 1
        else:
            unmatched.append(original)
    if applied:
        REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
        backup.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
        md_path.write_text(doc, encoding="utf-8")
    return applied, unmatched


def review_is_current(md_path: Path) -> tuple[bool, Path | None]:
    """(is_current, review_path): whether a review exists for md_path's CURRENT
    content. False+path = review exists but the doc was edited afterwards."""
    review_path = REVIEWS_DIR / f"{md_path.stem}_review.md"
    if not review_path.exists() or not md_path.exists():
        return False, review_path if review_path.exists() else None
    doc_sha = hashlib.sha1(md_path.read_bytes()).hexdigest()
    head = review_path.read_text(encoding="utf-8")[:400]
    return (f'reviewed_sha: "{doc_sha}"' in head), review_path
