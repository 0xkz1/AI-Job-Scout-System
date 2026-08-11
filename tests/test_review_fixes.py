"""parse_review_fixes / apply_review_fixes — deterministic apply of review
suggestions: verbatim quote replacement only, no LLM, backup before write."""
from pathlib import Path

from reviewer import (parse_review_fixes, apply_review_fixes, REVIEWS_DIR,
                      _mark_unusable_bridge_suggestions)

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


def test_a_fix_the_bridge_gate_would_reject_is_not_applicable(tmp_path):
    """Told plainly not to, the reviewer still offers "aligns with" for "feels
    relevant to" on about half of runs. That word is in _BRIDGE_NEVER_ECHO, so
    applying the fix writes a sentence the next regeneration throws out."""
    body = ('### ✍️ 文体\n'
            '- **"feels relevant to the way I built TAIFUNOME"**\n'
            '  → 修正案: "PressW\'s focus aligns with how I built TAIFUNOME."\n'
            '- **"abstracted assumptions"**\n'
            '  → 修正案: "unverified assumptions."\n')

    rp = tmp_path / "X_CL_review.md"
    rp.write_text(_mark_unusable_bridge_suggestions(body))

    assert parse_review_fixes(rp) == [("abstracted assumptions",
                                       "unverified assumptions.")]


def test_the_defused_suggestion_stays_readable(tmp_path):
    """Dropping the finding would hide the reviewer's reasoning; only the
    quoting that makes it applicable is removed."""
    body = '- **"x"**\n  → 修正案: "y that mirrors the platform."\n'

    out = _mark_unusable_bridge_suggestions(body)

    assert "y that mirrors the platform." in out
    assert '"y that mirrors the platform."' not in out


def test_the_bridge_translation_is_never_mined_for_fixes(tmp_path):
    """The translation heading has moved twice as the letter's variable part
    moved (全文和訳 → 冒頭段落の和訳 → Bridge の和訳). Reviews on disk are not
    regenerated, so every past name has to keep excluding its own block."""
    for heading in ("全文和訳", "冒頭段落の和訳", "Bridge の和訳"):
        rp = tmp_path / f"X_CL_review.md"
        rp.write_text('- **"real quote"**\n  → 修正案: "real fix"\n\n'
                      f'## {heading}\n- **"和訳の引用"**\n  → 修正案: "訳文"\n')

        assert parse_review_fixes(rp) == [("real quote", "real fix")], heading


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
    # pre-apply backup preserved, under .backups/ as apply_review_fixes documents
    assert (tmp_path / "15_reviews" / ".backups" / "X_CV.pre_apply.md"
            ).read_text() == DOC_MD
