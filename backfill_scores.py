"""Backfill submission_score / submission_ready into existing review files.

Does NOT import llm_client or call anything network-dependent.
Parses the YAML rubric block + section structure directly.
"""
import re
import yaml
from pathlib import Path

REVIEWS_DIR = Path(__file__).resolve().parent / "10_output" / "15_reviews"


def _extract_score(text: str) -> tuple[int, bool]:
    score = 100
    ready = True

    # 1. YAML rubric
    rubric_match = re.search(r'```yaml\n(.*?)\n```', text, re.DOTALL)
    if rubric_match:
        try:
            rubric_data = yaml.safe_load(rubric_match.group(1))
            rubric = rubric_data.get('rubric', [])
            total_reqs = len(rubric)
            if total_reqs > 0:
                req_score = 0
                for item in rubric:
                    ev = str(item.get('evidence', '')).lower()
                    if ev == 'strong':
                        req_score += 1.0
                    elif ev == 'weak':
                        req_score += 0.5
                coverage = req_score / total_reqs
                score = int(30 + (70 * coverage))
        except Exception as e:
            print(f"  YAML parse error: {e}")

    # 2. Fact section (hard block)
    fact_match = re.search(r'### ❗ 事実(.*?)(?=###|$)', text, re.DOTALL)
    if fact_match:
        fact_section = fact_match.group(1).strip()
        if re.search(r'(?:^\d+\.|^\*|\n\d+\.|\n\*)', fact_section):
            ready = False

    # 3. Style penalty
    style_match = re.search(r'### ✍️ 文体(.*?)(?=###|$)', text, re.DOTALL)
    if style_match:
        style_section = style_match.group(1).strip()
        style_items = len(re.findall(r'(?:^\d+\.|^\*|\n\d+\.|\n\*)', style_section))
        penalty = min(style_items * 3, 30)
        score -= penalty

    score = max(0, min(100, score))
    if score < 85:
        ready = False

    return score, ready


count = 0
skipped = 0
for f in sorted(REVIEWS_DIR.glob("*_review.md")):
    content = f.read_text(encoding="utf-8")

    # Skip if already has scores
    if "submission_score:" in content:
        skipped += 1
        continue

    # Split frontmatter
    parts = content.split("---", 2)
    if len(parts) < 3:
        print(f"  SKIP (no frontmatter): {f.name}")
        continue

    fm = parts[1]
    body = parts[2]

    score, ready = _extract_score(body)
    ready_str = "true" if ready else "false"

    new_fm = fm.rstrip() + f"\nsubmission_score: {score}\nsubmission_ready: {ready_str}\n"
    f.write_text(f"---{new_fm}---{body}", encoding="utf-8")
    print(f"  {f.name}: score={score} ready={ready_str}")
    count += 1

print(f"\nDone. Updated {count}, skipped {skipped}.")
