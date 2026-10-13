"""A provider that answers 200 with nothing must not end the fallback chain.

run_review advanced to the next provider on exceptions only, so a model that
replied successfully with an empty or off-format body was accepted. On
2026-08-12 that wrote 28 CL and 3 CV reviews containing frontmatter and the
words 未算出, nothing else — and nothing in the frontmatter distinguishes one
of those from a review that genuinely found no faults.
"""
import itertools
from concurrent.futures import ThreadPoolExecutor

import pytest

import key_quarantine
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


@pytest.mark.parametrize(
    "survivors",
    [
        reviewer.MISTRAL_KEYS,
        reviewer.MISTRAL_KEYS[-3:],
    ],
)
def test_parallel_reviews_rotate_the_surviving_mistral_keys(monkeypatch, survivors):
    """Filtering first is load-bearing when most direct keys are quarantined.

    Rotating the complete list before filtering made all three workers converge
    on the first surviving key when the first twelve keys were sidelined.
    """
    survivor_set = set(survivors)
    monkeypatch.setattr(reviewer, "_MISTRAL_ROTATION_COUNTER", itertools.count())
    monkeypatch.setattr(
        key_quarantine,
        "is_quarantined",
        lambda provider: provider in reviewer.MISTRAL_KEYS and provider not in survivor_set,
    )

    def direct_mistral_head(_index):
        return next(
            provider for provider, _model in reviewer._prepare_review_chain(
                [(provider, reviewer.REVIEW_MODEL) for provider in reviewer.MISTRAL_KEYS]
            )
            if provider in reviewer.MISTRAL_KEYS
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        heads = list(pool.map(direct_mistral_head, range(3)))

    assert set(heads) == set(survivors[:3])
    assert len(heads) == len(set(heads))


def test_review_fallback_env_preserves_operator_priority(monkeypatch):
    monkeypatch.setenv(
        "REVIEW_FALLBACKS",
        "mistral-tertiary:model-c,mistral:model-a,mistral-backup:model-b",
    )
    monkeypatch.setattr(key_quarantine, "is_quarantined", lambda _provider: False)
    monkeypatch.setattr(reviewer, "_MISTRAL_ROTATION_COUNTER", itertools.count())

    expected = [
        ("mistral-tertiary", "model-c"),
        ("mistral", "model-a"),
        ("mistral-backup", "model-b"),
    ]
    assert reviewer._review_chain() == expected
    assert reviewer._review_chain() == expected


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


# --- ❗事実 findings that cannot be a false statement in the document -----------

CV_DOC = """# Kazuki Yunome
## PROFILE
Technical professional working across automation, data processing, and design.
Built a bespoke design system around typography, design tokens and editorial rules.
**Languages:** Japanese (native) · English (professional working)
"""


def _body(*bullets):
    return "### ❗ 事実\n" + "\n".join(bullets) + "\n\n### 🎯 求人適合\n- x\n"


def _blocks(body, doc=CV_DOC):
    fixed, notes = reviewer.verify_fact_findings(body, doc)
    return reviewer._extract_score(fixed)[1], fixed, notes


def test_a_quote_of_the_job_posting_is_not_a_fabrication_in_the_cv():
    """Wooden Books: the posting's requirement, quoted as if the CV had claimed it."""
    blocked, fixed, notes = _blocks(_body(
        '- **事実に反する記述**: CVに「ネイティブスピーカーの英語」と明記されていない。\n'
        '  > "A native English speaker with good editorial senses"'))
    assert not blocked
    assert "※未検証（引用が本文に無い）" in fixed and notes


def test_a_quote_that_is_in_the_document_still_blocks():
    blocked, _, notes = _blocks(_body(
        '- **事実に反する記述**: 検証済み事実にこの成果は無い。\n'
        '  > "Built a bespoke design system around typography, design tokens and editorial rules."'))
    assert blocked and not notes


def test_curly_apostrophes_and_hyphen_variants_do_not_hide_a_real_quote():
    doc = "I built the site’s front‑end by hand."
    blocked, _, _ = _blocks(_body('- 事実に反する: "I built the site\'s front-end by hand."'), doc)
    assert blocked


@pytest.mark.parametrize("bullet", [
    "- 記載なし",
    "- **職歴の虚偽な記載なし**：個人プロジェクトとして記載されている。",
    "- No factual inaccuracies found.",
    "- 「Built a bespoke design system around typography」は検証済みです。",
])
def test_the_reviewers_all_clear_written_as_a_bullet_does_not_block(bullet):
    assert not _blocks(_body(bullet))[0]


def test_something_missing_is_a_fit_question_not_a_fabrication():
    blocked, _, _ = _blocks(_body(
        "- 求人票で要求される「UKセキュリティクリアランス」が、候補者の経歴には見当たらない。"))
    assert not blocked


def test_an_unquoted_claim_of_falsehood_still_blocks():
    """Err toward blocking: a real fabrication let through is the worse error."""
    assert _blocks(_body("- CVの年数表記は事実に反する。実際は4年である。"))[0]


def test_a_finding_that_says_the_fact_is_false_is_not_demoted_for_being_phrased_as_absence():
    assert _blocks(_body("- 検証済み事実に存在しない受賞歴が記載されている（記載なしではない）。"))[0]
