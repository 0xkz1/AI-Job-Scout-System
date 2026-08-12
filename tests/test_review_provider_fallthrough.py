"""A provider that answers 200 with nothing must not end the fallback chain.

run_review advanced to the next provider on exceptions only, so a model that
replied successfully with an empty or off-format body was accepted. On
2026-08-12 that wrote 28 CL and 3 CV reviews containing frontmatter and the
words 未算出, nothing else — and nothing in the frontmatter distinguishes one
of those from a review that genuinely found no faults.
"""
import pytest

import reviewer

GOOD_CL = """### ❗ 事実
問題なし

### 🎯 求人適合
- **"Example's focus on X feels relevant to the way I built TAIFUNOME."**
  求人票の主要な要求のうち、3Dビューアの実装経験とバックエンド接続の経験が
  検証済み事実に存在しない。接続点が候補者の方法論のみに依存している。
  → 補強不可（検証済み事実に該当経験なし。この求人は適合度が低い）

### ✍️ 文体
- **"designing the feedback loops that keep users oriented"**
  分詞構文の使い方が不自然で、冗長。
  → 修正案: "with feedback loops that keep users oriented"

### 総評
bridge の接続は方法論に寄りすぎており、求人票の技術的中核要件との適合が示せていない。
"""

GOOD_CV = "```yaml\nrubric:\n  - requirement: \"X\"\n    evidence: \"Weak\"\n```\n\n" + GOOD_CL


def test_an_empty_body_is_unusable():
    assert reviewer._review_is_unusable("", "CL")
    assert reviewer._review_is_unusable("**提出スコア:** ⚪ 未算出", "CL")


def test_a_body_without_finding_sections_is_unusable():
    prose = "この文書は良く書けています。" * 40

    assert reviewer._review_is_unusable(prose, "CL") == "no finding sections"


def test_a_cv_review_without_a_rubric_is_unusable():
    """The rubric IS the submission score, so a CV review missing it scores
    null — which reads the same as a review that could not be produced."""
    assert reviewer._review_is_unusable(GOOD_CL, "CV") == "no rubric block"
    assert reviewer._review_is_unusable(GOOD_CV, "CV") is None


def test_a_well_formed_cl_review_passes():
    assert reviewer._review_is_unusable(GOOD_CL, "CL") is None


def test_the_chain_skips_a_provider_that_returns_an_unusable_body(monkeypatch, tmp_path):
    """The local fallback is the only entry that accepts a 62k-character
    prompt, so once the cloud providers rate-limit, every review lands there."""
    monkeypatch.setattr(reviewer, "_review_chain",
                        lambda: [("weak", "m1"), ("good", "m2")])
    monkeypatch.setattr(reviewer, "_load_review_facts", lambda: "facts")
    monkeypatch.setattr(reviewer, "_load_skills_md", lambda: "skills")
    monkeypatch.setattr(reviewer, "_load_decisions", lambda: "decisions")
    monkeypatch.setattr(reviewer, "REVIEWS_DIR", tmp_path)
    called = []

    def fake_llm(*_a, provider=None, **_k):
        called.append(provider)
        return "**提出スコア:** ⚪ 未算出" if provider == "weak" else GOOD_CL

    monkeypatch.setattr(reviewer, "call_llm", fake_llm)
    doc = tmp_path / "X_CL.md"
    doc.write_text("---\ntype: cl\n---\n\nDear Hiring Team,\n\nbody\n")

    out = reviewer.run_review("CL", doc, {"company": "X", "title": "Y", "description": "d"})

    assert called == ["weak", "good"]
    assert "問題なし" in out.read_text(encoding="utf-8")


def test_every_provider_failing_raises_rather_than_storing_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(reviewer, "_review_chain", lambda: [("weak", "m1")])
    monkeypatch.setattr(reviewer, "_load_review_facts", lambda: "facts")
    monkeypatch.setattr(reviewer, "_load_skills_md", lambda: "skills")
    monkeypatch.setattr(reviewer, "_load_decisions", lambda: "decisions")
    monkeypatch.setattr(reviewer, "REVIEWS_DIR", tmp_path)
    monkeypatch.setattr(reviewer, "call_llm", lambda *a, **k: "")
    doc = tmp_path / "X_CL.md"
    doc.write_text("---\ntype: cl\n---\n\nDear Hiring Team,\n\nbody\n")

    with pytest.raises(RuntimeError, match="All review providers failed"):
        reviewer.run_review("CL", doc, {"company": "X", "title": "Y", "description": "d"})
