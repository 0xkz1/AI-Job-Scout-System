"""parse_review_fixes / apply_review_fixes — deterministic apply of review
suggestions: verbatim quote replacement only, no LLM, backup before write."""
from pathlib import Path

from reviewer import parse_review_fixes, apply_review_fixes, REVIEWS_DIR

REVIEW_MD = '''---
type: "review"
---

### ❗ 事実
- **"I built the entire platform alone."**
  → 誇張の可能性。
  → 修正案: **"I built the core pipeline of the platform."**

- **"Expert in Kubernetes."**
  → 検証済み事実にない。
  → 修正案: **"Working knowledge of Docker-based deployment."**

### ✍️ 文体
- **"This phrase is not in the document."**
  → テスト用の不一致ケース。
  → 修正案: **"replacement that must not be applied"**
'''

DOC_MD = """# CV
I built the entire platform alone. Expert in Kubernetes. Done.
"""


def test_parse_extracts_quote_fix_pairs(tmp_path):
    rp = tmp_path / "X_CV_review.md"
    rp.write_text(REVIEW_MD)
    pairs = parse_review_fixes(rp)
    assert ("I built the entire platform alone.",
            "I built the core pipeline of the platform.") in pairs
    assert len(pairs) == 3


def test_apply_replaces_only_verbatim_matches(tmp_path, monkeypatch):
    import reviewer
    monkeypatch.setattr(reviewer, "REVIEWS_DIR", tmp_path / "15_reviews")
    rp = tmp_path / "X_CV_review.md"
    rp.write_text(REVIEW_MD)
    doc = tmp_path / "X_CV.md"
    doc.write_text(DOC_MD)

    applied, unmatched = apply_review_fixes(doc, rp)
    text = doc.read_text()
    assert applied == 2
    assert "I built the core pipeline of the platform." in text
    assert "Working knowledge of Docker-based deployment." in text
    assert "must not be applied" not in text
    assert unmatched == ["This phrase is not in the document."]
    # pre-apply backup preserved
    assert (tmp_path / "15_reviews" / "X_CV.pre_apply.md").read_text() == DOC_MD
