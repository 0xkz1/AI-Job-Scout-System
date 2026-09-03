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
import re
import yaml
from datetime import date
from pathlib import Path

from llm_client import call_llm
from matcher import USER_PROFILE_DIR, _load_persona_summary

ROOT = Path(__file__).resolve().parent
REVIEWS_DIR = ROOT / "10_output" / "15_reviews"
PRISTINE_DIR = REVIEWS_DIR / ".pristine"   # as-generated copies → annotation detection
ARCHIVE_DIR = REVIEWS_DIR / ".archive"      # old versions saved on re-review / dialogue

# Review deserves a stronger model than bulk analysis: it runs only on
# shortlisted applications and its output gates what actually gets sent.
REVIEW_MODEL = os.environ.get("REVIEW_MODEL", "mistral-medium-latest")

# Single source of truth for which Mistral keys exist, in priority order. Read from
# llm_client rather than restated here: the two lists drifted before, and a chain
# entry with no dispatch branch fails every call to that provider.
from llm_client import MISTRAL_PROVIDERS as _MISTRAL_PROVIDERS  # noqa: E402
from doc_paths import md_files  # noqa: E402

MISTRAL_KEYS = tuple(_MISTRAL_PROVIDERS)


def _review_chain() -> list[tuple[str, str]]:
    """Ordered (provider, model) candidates for a review call, tried in turn.

    Unlike the global FALLBACK_PROVIDERS chain, each entry carries its OWN model
    name — a model id is provider-specific (mistral-medium does not exist on
    stepfun), so the single-`model` override could never fall back across
    providers. Override via env REVIEW_FALLBACKS="prov:model,prov:model,...".

    Default chain, best → last-resort. Reliable non-reasoning cloud models come
    FIRST; the free reasoning model (deepseek-v4-flash) sits low because it can
    silently return empty content on long docs (burns max_tokens on hidden
    reasoning) — llm_client now raises on empty so the chain falls through, but
    it's still a poor primary. Every MISTRAL_API_KEY* in the environment becomes an
    entry (each key has its own allowance); nvidia is a fully independent provider,
    so it survives a mistral.ai outage that would take out all of them at once:

    The Z.AI entries (z-ai/glm-5.2) add another 11-key pool from Hermes's
    credential pool — 2 are exhausted but quarantine handles them. Same
    independent-rate-limit advantages as the others.

      1..N.    mistral / mistral-backup / ...            (see MISTRAL_KEYS)
      N+1..7   nvidia..nvidia-septenary / nemotron-super-49b-v1.5 — NIM 7 keys
      N+8..18  zai..zai-undenary / glm-5.2                — Z.AI pool (11 keys)
      N+19.    opencode / deepseek-v4-flash-free          — FREE reasoning (Zen)
      N+20.    opencode / big-pickle                      — independent Zen model
      N+21.    nvidia   / nemotron-nano-9b-v2             — cheap, looser on format
      N+22.    ollama   / local                           — offline last resort

    The prompt is ~64k characters, and that decides membership more than model
    quality does. Measured 2026-08-12 against the real thing: mistral and the
    NIM nemotrons take it, groq returns 413 Payload Too Large on every model
    tried (a request-size limit on the account, not a context window), and the
    local model is the only entry that accepts it while ignoring the output
    format — which is why _review_is_unusable exists.

    Key depth is not redundancy for its own sake: a single day of work (182 reviews
    plus analysis) exhausted the first three keys AND nvidia AND stepfun, leaving
    one live cloud provider. Free-tier Mistral allowances are monthly, so depth buys
    throughput for exactly that kind of bulk day. Entries whose key is unset raise
    on call and are skipped, so listing a key that does not exist is harmless —
    which is why the list is fixed here rather than probed from os.environ. Dead
    accounts (zai 429) are left out; add back via REVIEW_FALLBACKS once recharged.
    """
    env = os.environ.get("REVIEW_FALLBACKS", "").strip()
    if env:
        chain = [
            (p.split(":", 1)[0].strip(), p.split(":", 1)[1].strip())
            for p in env.split(",") if ":" in p
        ]
        if chain:
            return _drop_quarantined(chain)
    return _drop_quarantined([
        # The gateway leads, ahead of the keys this project holds itself, because
        # it holds a SUPERSET of them — the same fifteen plus nine more, 24
        # mistral-medium deployments as of 2026-08-18 — behind its own cooldown
        # table and its own model-level fallback (nvidia-nim, groq-fast, zai-glm,
        # ollama). Walking MISTRAL_KEYS first would spend the chain re-testing
        # keys the gateway already knows are spent: five of the fifteen were
        # sitting on multi-day 402s that day, and every review paid for them.
        # Its model id is the gateway's own `mistral-medium`, not REVIEW_MODEL —
        # the gateway maps that to mistral-medium-latest internally.
        # Verified 2026-08-18: a 98,000-char prompt (review-sized) answered in
        # 45.9s. If the gateway is down the entry simply fails and the chain
        # falls through to the direct keys below, which is the safe direction.
        ("litellm-gateway", "mistral-medium"),
        *((provider, REVIEW_MODEL) for provider in MISTRAL_KEYS),
        # mistralai/mistral-medium-3.5-128b does not exist on NIM and never
        # did: all seven keys answered 410 Gone, which reads as a dead account
        # rather than a wrong model id. GET /v1/models lists what is actually
        # served; nemotron-super-49b takes the 64k prompt and follows the
        # format, including the CL instruction not to comment on the letter's
        # fixed blocks. nano-9b also takes the prompt and is far cheaper, but
        # it flagged the canonical narrative the scope section rules out — so
        # it sits behind, as a still-useful last cloud option.
        ("nvidia", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
        ("nvidia-back", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
        ("nvidia-tertiary", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
        ("nvidia-quaternary", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
        ("nvidia-quinary", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
        ("nvidia-senary", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
        ("nvidia-septenary", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
        # groq is absent by measurement, not by model choice. Bisected against
        # the live API 2026-08-17: it accepts 21,812 prompt chars and refuses
        # 22,281, identically on gpt-oss-120b, gpt-oss-20b, qwen3.6-27b and
        # compound-mini — an account request-BODY cap, not a context window
        # (every one of those advertises 131k tokens). A review prompt measures
        # ~98,577 chars, so nothing groq serves can take it and no model swap
        # will change that. llm_client now enforces this generally
        # (_PROVIDER_MAX_PROMPT_CHARS), so groq leads the general chain and is
        # skipped here on size; do not "fix" its absence by adding it back.
        # What WOULD make groq usable here is a smaller prompt, not a different
        # model — the persona alone is ~55k chars.
        # Z.AI 11-key pool — chain names zai..zai-undenary (see ZAI_PROVIDERS in llm_client)
        ("zai", "glm-5.2"),
        ("zai-back", "glm-5.2"),
        ("zai-tertiary", "glm-5.2"),
        ("zai-quaternary", "glm-5.2"),
        ("zai-quinary", "glm-5.2"),
        ("zai-senary", "glm-5.2"),
        ("zai-septenary", "glm-5.2"),
        ("zai-octonary", "glm-5.2"),
        ("zai-nonary", "glm-5.2"),
        ("zai-denary", "glm-5.2"),
        ("zai-undenary", "glm-5.2"),
        ("opencode", "deepseek-v4-flash-free"),
        ("opencode", "big-pickle"),
        ("nvidia", "nvidia/nvidia-nemotron-nano-9b-v2"),
        ("ollama", os.environ.get("OLLAMA_MODEL", "gemma-4-26b-a4b-it-gguf")),
    ])


def _drop_quarantined(chain: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Skip providers whose key is sidelined by key_quarantine, so a review call
    doesn't burn its full retry budget on a dead key (two exhausted Mistral keys
    otherwise cost ~12s per review before reaching the live one). Never returns
    empty — if every provider is sidelined, fall back to the full chain.

    A missing provider here is EXPECTED, not a fault to repair. Quarantine
    entries expire on their own (key_quarantine.DEFAULT_COOLDOWN_DAYS = 5); do
    not `key_quarantine.py --release` them to "restore" the chain. Nor does a
    small probe call prove a key recovered — a max_tokens=5 request can succeed
    on a key whose allowance is spent, because a real review sends a long prompt
    to mistral-medium. Releasing early puts a dead key back ahead of working
    ones and slows every subsequent review.
    """
    try:
        from key_quarantine import is_quarantined
        active = [(p, m) for p, m in chain if not is_quarantined(p)]
        return active or chain
    except Exception:
        return chain


def _load_skills_md() -> str:
    """Skill source of truth for the reviewer: the full skills.md plus the CV's
    own skill toolkit.

    Both halves fix a real misfire. skills.md is ~10.5k chars and was being
    truncated to 3000 — which cut off Figma, so a CL line about "producing
    final assets in Figma" was flagged as an unsupported claim even though
    skills.md documents it. career/cv/skill-toolkit/master.md ("Figma
    (component libraries, auto-layout, interactive prototypes), Affinity
    Suite, Procreate, …") is what the generated CV's toolkit section is built
    from, yet it was never shown to the reviewer at all — same class of bug as
    the projects omission in _load_review_facts().
    """
    parts = []
    try:
        parts.append((USER_PROFILE_DIR / "skills.md").read_text(encoding="utf-8"))
    except Exception:
        pass
    toolkit_dir = ROOT.parent / "cv" / "skill-toolkit"
    try:
        for f in md_files(toolkit_dir):
            parts.append(f"--- skill-toolkit/{f.name} ---\n"
                         + f.read_text(encoding="utf-8"))
    except Exception:
        pass
    return "\n\n".join(p.strip() for p in parts if p.strip())


# ── Decision ledger ─────────────────────────────────────────────────────
# Settled review matters live in career/cv/review-decisions.md and are fed
# into every review prompt, so a point the user already ruled on (e.g. "the
# tagline stays") is never re-flagged. The annotation dialogue appends newly
# settled matters automatically.
DECISIONS_FILE = ROOT.parent / "cv" / "review-decisions.md"

# Source files that reviews commonly quote — used to trace a finding back to
# the reusable block it came from ("fix it there once, it fixes every CV").
_SOURCE_GLOBS = [
    ("profile", ROOT.parent / "cv" / "profile", "*.md"),
    ("project", ROOT.parent / "cv" / "projects", "*.md"),
    ("employment", ROOT.parent / "cv" / "experience", "*.md"),
    ("toolkit", ROOT.parent / "cv" / "skill-toolkit", "*.md"),
    ("CL template", ROOT.parent / "cover-letter", "*.md"),
]


def _load_decisions() -> str:
    """The whole ledger, untruncated.

    It was capped at 2000 chars while the file had already grown to ~4.4k, so
    the oldest rulings silently fell off the end and the reviewer re-raised
    points the candidate had settled weeks earlier — the same truncation bug
    that had been starving _load_review_facts and _load_skills_md. The ledger
    is one line per decision and grows slowly; there is no reason to cap it.
    """
    try:
        text = DECISIONS_FILE.read_text(encoding="utf-8")
        import re
        text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)
        return text.strip() or "(none yet)"
    except Exception:
        return "(none yet)"


def _load_review_facts() -> str:
    """Full evidence base for a review: persona docs PLUS the project entries.

    _load_persona_summary() (shared with the matcher) reads only ethos.md /
    about.md / profile.md / interests.md — it never sees career/cv/projects/,
    which is where the candidate's actual built work is documented. Reviews
    were additionally truncating that already-partial persona to 2500 chars,
    so the reviewer was fact-checking CVs against roughly a third of the
    profile and none of the projects.

    That starved base produced false fabrication findings: "Product designer
    with a systems-level approach to UX and UI" was flagged as unverified even
    though portfolio_website.md ("Portfolio Website Design & Development" —
    HTML/CSS/JS/GSAP/Front-End Engineering) and taifunome-research-platform
    .md (Web Design, Frontend Engineering, React) evidence exactly that. The
    CV is GENERATED from these project files, so they must be part of what it
    is checked against — otherwise the reviewer calls the CV's own sources
    fabrication.
    """
    persona = _load_persona_summary() or ""
    try:
        from cv_generator import _ALL_ENTRIES
        blocks = []
        for p in _ALL_ENTRIES:
            head = " | ".join(x for x in (p.get("title", ""), p.get("role", ""),
                                          p.get("period", "")) if x)
            skills = ", ".join(str(s) for s in (p.get("skills") or []))
            body = (p.get("description", "") or "").strip()
            blocks.append(
                f"### {head}\n"
                + (f"Skills: {skills}\n" if skills else "")
                + body
            )
        projects = "\n\n".join(blocks)
    except Exception as e:
        print(f"  ⚠ project facts unavailable for review ({e})")
        projects = ""

    if not projects:
        return persona
    return (
        f"{persona}\n\n"
        "--- DOCUMENTED PROJECTS & EMPLOYMENT (authoritative; these are the "
        "source files the CV is generated from) ---\n"
        f"{projects}"
    )


def _norm(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", s.replace("**", "").replace("*", "")).strip().lower()


def verify_rubric_evidence(body: str, document: str) -> tuple[str, list[str]]:
    """Downgrade a Strong rubric row whose quote is not in the document.

    The score is the rubric, and the rubric was the reviewer's unshown opinion:
    a Meltwater AI Engineer posting naming NLP, Transformers, fine-tuning and
    transfer learning throughout scored `Strong` on exactly that requirement
    against a CV that contains none of those words in any form. That is 14
    points on a 100-point scale, and it reached apply_priority through
    cv_review_score at 0.6 weight.

    So `Strong` now has to carry a line from the document, and the line has to
    be there. Matching is normalised the way finding quotes are (_norm), since
    the document is markdown and a model reliably drops the bold markers.

    Deliberately partial: a quote that IS in the CV but does not actually
    support the requirement still passes. What this buys against that case is
    that the reviewer has to commit to a specific piece of evidence, where the
    reader can see it is thin — which was impossible when the verdict was a
    bare "Strong". The demotion is to `Weak`, not `None`, so a wrongly rejected
    quote costs half a rubric row rather than a whole one.

    Returns (body, [notes]) — body unchanged when there is nothing to correct.
    """
    import re
    match = re.search(r'```yaml\s*\n(.*?)\n```', body, re.DOTALL)
    if not match:
        return body, []
    try:
        block = yaml.safe_load(match.group(1)) or {}
        rubric = block.get("rubric") or []
    except Exception as e:
        print(f"  ⚠ rubric parse error during evidence check: {e}")
        return body, []

    haystack = _norm(document)
    notes: list[str] = []
    for item in rubric:
        if not isinstance(item, dict) or str(item.get("evidence", "")).lower() != "strong":
            continue
        quote = str(item.get("evidence_quote") or "").strip()
        if quote and _norm(quote) in haystack:
            continue
        item["evidence"] = "Weak"
        item["downgraded_from"] = "Strong"
        item["downgrade_reason"] = ("引用なし" if not quote
                                    else "引用が本文に見つからない")
        notes.append(str(item.get("requirement", "?"))[:60])

    if not notes:
        return body, []
    rewritten = yaml.safe_dump({"rubric": rubric}, allow_unicode=True,
                               sort_keys=False, default_flow_style=False)
    return body.replace(match.group(0), f"```yaml\n{rewritten.strip()}\n```", 1), notes


def trace_finding_sources(review_path: Path) -> list[tuple[str, str | None]]:
    """For each finding quote, locate the reusable source file it came from.
    Deterministic substring matching, no LLM. Returns [(quote, source or None)]
    where source like 'project: portfolio_website.md' means: fix it THERE and
    it fixes every generated document — answering it per-review just repeats."""
    import re
    text = review_path.read_text(encoding="utf-8")
    text = re.split(r"\n#+\s*(?:全文和訳|冒頭段落の和訳)", text, maxsplit=1)[0]
    quotes = [q.strip() for q in re.findall(r'\*\*"(.+?)"\*\*', text, flags=re.DOTALL)]

    corpus = []
    for kind, d, pat in _SOURCE_GLOBS:
        if d.exists():
            for f in sorted(d.glob(pat)):
                if f.name.startswith("archive"):
                    continue
                corpus.append((f"{kind}: {f.name}", _norm(f.read_text(encoding="utf-8"))))

    out = []
    for q in quotes:
        nq = _norm(q)
        hit = next((label for label, body in corpus if len(nq) >= 25 and nq in body), None)
        out.append((q, hit))
    return out


CV_RUBRIC_INSTRUCTION = """FIRST, you MUST output a YAML block evaluating the job's key requirements against the document.
List 3-5 major requirements from the job posting. For each, determine the evidence level in the document: 'Strong', 'Weak', or 'None'.

`Strong` additionally requires `evidence_quote`: ONE sentence or bullet copied VERBATIM from the document under review, which a reader would accept as evidence for that requirement on its own. Copy it exactly — it is checked against the document, and a quote that is not found there is downgraded to `Weak` automatically. If nothing in the document can be quoted for a requirement, the evidence level is not `Strong`; say `Weak` or `None` and leave `evidence_quote` out.

Format exactly as follows at the very beginning of your response:
```yaml
rubric:
  - requirement: "Requirement description in Japanese"
    evidence: "Strong"  # or "Weak" or "None"
    evidence_quote: "the verbatim sentence from the document"  # Strong only
  - requirement: "..."
    evidence: "None"
```"""


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

## SETTLED MATTERS — 既決事項 (the candidate has already considered these; do NOT flag them again)
{decisions}

## DOCUMENT UNDER REVIEW ({doc_kind})
{document}

## YOUR TASK
Produce a findings list in markdown. Do NOT rewrite the document.

LANGUAGE RULES (important):
- Write ALL explanations, problem descriptions, and the verdict in JAPANESE.
- Quote the document's original ENGLISH sentences verbatim when referencing a passage.
- Suggested replacement sentences must be in ENGLISH (they will be pasted into the English document as-is).

{scope_section}

Then, provide the detailed findings using the following categories:

### ❗ 事実
**書かれている内容が事実に反する場合のみ**。該当箇所を英語原文のまま引用すること。
ここに挙げてよいのは以下だけ:
- 検証済み事実に存在しない職歴・案件・成果物・数値
- 候補者が持っていない資格・在籍歴・業界経験
- 検証済み事実の記述と矛盾する内容

**ここに挙げてはならないもの**（挙げた場合そのレビューは無効）:
- 実績が「個人プロジェクトであって商業案件・クライアントワークではない」こと。
  この候補者はポートフォリオ主導であり、個人プロジェクトは正当な実績。
- 記述が事実だが「求人との関連が薄い」「求人の要求と種類が違う」こと。
  → それは事実の問題ではないので **🎯 求人適合** に書くこと。
- 経験年数や規模が求人の要求に届かないこと → 同じく **🎯 求人適合** へ。

### 🎯 求人適合
求人票の主要な要求のうちドキュメントが触れていないもの、今回の求人に無関係な記述、
および「事実ではあるが求人の求めるものとは種類・規模・文脈が異なる」記述。

**このセクションの修正案は、検証済み事実に無い経歴・スキル・業界経験を新たに書かせてはならない**（これは最優先の絶対規則）。候補者が本当に持っていない要件（例: モバイルアプリUX、React Native、金融業界、ユーザーリサーチ）に対し、「近いことをやったと書け」式の置き換え文を提案することは、事実欄で禁じている捏造そのものである。埋められないギャップには:
- 検証済み事実に**実在する隣接経験**があればそれを挙げる（無理に関連づけない）。
- 実在しないなら、修正案の代わりに `→ 補強不可（検証済み事実に該当経験なし。この求人は適合度が低い）` と正直に書く。捏造してスコアを上げるより、低スコアのまま正直でいることを優先する。
「Terra Droneでコンプライアンス文書を担当した」「ECシステムでユーザーリサーチを実施した」のような、記録に無い業務を作り出す提案は禁止。

### ✍️ 文体
UK英語の問題、クリシェ、冗長表現、日付の不整合、不自然な言い回し。各指摘に英語原文の引用を付けること。

各指摘の形式: 英語原文の引用 → 何が問題か（日本語）→ 具体的な修正案（英語の置き換え文。候補者がそのまま採用/却下できるもの）。
指摘がないカテゴリには「問題なし」と書くこと。
最後に2〜3文の **総評**（日本語）: 修正案を反映すればこのドキュメントは提出可能か。
ただし、求人の中核要件を候補者が本当に満たしておらず、捏造なしでは適合を上げられない場合は、
無理に「修正すれば提出可能」と書いてはならない。「この求人は適合度が低く、寄せて仕上げる価値が
薄い。優先度を下げるか、素の強みで数を打つ対象とすべき」と正直に述べること。低スコアは文書の
欠陥ではなく、求人と候補者のミスマッチを正確に示すシグナルである。
具体的かつ正直に — 社交辞令だけの空のレビューは誰の役にも立たない。

{translation_section}"""

# CL のみ: 求人ごとに新規に書かれるのは最終段落 (context bridge) だけで、どの
# ソース MD にも和訳が存在しない — そこだけ訳す。冒頭の一文は固定テンプレ、
# 中間の身上段落は canonical_narrative_v1.md の逐語コピー、実績段落は
# letter_facts_v1.md の locked block なので、レビューごとに訳す価値はない。
# (旧テンプレ方式では新規生成だったのは冒頭段落で、この指示もそう書いていた。
#  assembler で可変部分が末尾に移ったため、訳す対象も入れ替わっている。)
# CV は再利用ブロックの組み立てなので和訳自体を載せない (ソース側を参照)。
CL_TRANSLATION_INSTRUCTION = """
総評のあとに区切り線 (---) を置き、続けて `## Bridge の和訳` という見出しを付けて、カバーレター本文の最終段落（"Yours sincerely," の直前の段落。この求人のために新規に書かれた唯一の部分）だけを自然な日本語に訳して記載すること。それ以外の段落は固定文の使い回しなので訳さないこと。この和訳は参照用であり指摘ではないので、修正案の引用形式（**"..."**）は絶対に使わないこと。"""


# CL のみ: レビュー対象を bridge に絞る。
#
# rubric (求人要件のカバレッジ) は CV の設問であって CL のものではない。
# assembler 方式のレターは求人要件に応えないことを設計として選んでいる —
# スタックの証明は CV と GitHub の担当で、レターは方法論と接続だけを書く。
# その文書に「Three.js の経験が None」と減点するのは、レターに CV の仕事を
# 採点させることになる。よって CL は rubric を出さず、submission_score は
# null になる (_extract_score は rubric 不在で None を返す)。求人適合の
# 数値は cv_review_score が持っており、Job Matches.base の apply_priority も
# それしか読んでいないので、優先度の算出には影響しない。
#
# 文体指摘も同じ理由で bridge に限る。canonical は全レター同一なので、
# そこへの指摘は 583 通で同じ内容が繰り返されるだけで、直す先は個々の
# レターではなく canonical_narrative_v1.md 一箇所しかない。
CL_SCOPE_INSTRUCTION = """レビュー対象は **本文の最終段落 (context bridge) のみ**。この求人のために新規に書かれたのはそこだけで、それ以外はすべて確定済みの固定文である:
- 冒頭の一文 (`I am writing to apply for ...`) — テンプレート
- 続く身上の段落群 — `canonical_narrative_v1.md` の逐語コピー。全レター共通で、LLM は書き換えない
- その後の実績段落 (1〜2件) — `letter_facts_v1.md` の locked block。CV の記載から起こした検証済みの文

**固定部分への指摘は一切しないこと**（文体・求人適合・冗長さを含む）。それらは全レターで同一なので、指摘しても直す先はこのレターではなくソース1ファイルであり、レビューごとに繰り返しても意味がない。固定部分は bridge を読むための文脈として使うだけでよい。

YAML の rubric ブロックは **出力しないこと**。求人要件をどれだけ満たすかは CV レビューの設問であり、このレターは意図的にそれに応えない設計になっている。

bridge について見るべきことは3点。下の見出しはそのまま使い、それぞれ次の意味で埋めること:
- **❗ 事実** — bridge が検証済み事実に無い経歴・実績・業界経験を主張していないか。相手企業のシステム・組織・技術構成について、求人票に書かれていないことを既知のように述べていないか。
- **🎯 求人適合** — 主眼は **接続の質**。bridge が述べる「この会社と候補者の接点」は求人票に実際に書かれている内容に基づいているか。どの会社に送っても成立する汎用文になっていないか。加えて、この求人と候補者の適合度が低いと判断したならそれも述べてよい（数値ではなく所見として）。ただしその場合も、埋められないギャップに対して経歴の捏造で埋めさせる修正案を出してはならない — `→ 補強不可（検証済み事実に該当経験なし。この求人は適合度が低い）` と正直に書くこと。
- **✍️ 文体** — UK英語、クリシェ、冗長表現、定型的な締め。**bridge の2文に対してのみ**。

**修正案に使ってはならない語**（このセクションに限らず、レビュー全体の修正案に適用）:
`align` を含む一切の語形（"aligns with", "aligned", "alignment"）、`mirrors`、`directly enables`、`directly matches`、`perfectly matches`、`is a natural fit`、`maps directly`、`translates directly`。
生成側の `_vet_bridge` がこれらを語幹で却下するため、提案しても適用できない。特に **"feels relevant to" を "aligns with" に変える提案は禁止** — この接続強度は意図的な選択である。求人広告から言えるのは「関連がありそう」までで、"aligns with" や "mirrors" は構造の同一性を主張しており、広告からは知り得ない。"feels relevant" が弱い・主観的だという指摘自体をしないこと。

総評も bridge についてのみ述べること。スコアには言及しないこと（この文書にスコアは付かない）。"""


def _ensure_review_backlink(md_path: Path) -> str:
    """Make sure the doc's frontmatter links to its review file, and return the
    doc text. Injected BEFORE hashing: the review filename is deterministic
    (<stem>_review), so writing the link first keeps reviewed_sha valid —
    adding it after the review would change the sha and mark the fresh review
    stale forever."""
    document = md_path.read_text(encoding="utf-8")
    if not document.startswith("---\n"):
        return document  # no frontmatter — leave the doc alone
    end = document.find("\n---", 4)
    if end == -1:
        return document
    frontmatter = document[:end]
    if "\nreview:" in frontmatter:
        return document
    updated = f'{frontmatter}\nreview: "[[{md_path.stem}_review]]"{document[end:]}'
    md_path.write_text(updated, encoding="utf-8")
    return updated


# Blocks that are byte-identical on every generated document, because they come
# from the master template rather than from the job: the contact/links lines
# under the name, and the whole EDUCATION & LANGUAGES section. Nothing in them
# can distinguish one review from another, so an edit there — correcting the
# university's name from "Hokkai University" to "Hokkai Gakuen University", say —
# used to invalidate every review on disk at once. 450 documents were marked for
# re-review by a two-word spelling fix.
#
# The trade is deliberate and narrow: a review whose findings were ABOUT one of
# these lines keeps reporting itself current after the line is corrected. That is
# acceptable because these lines state the record rather than argue from it —
# fixing them is what a finding against them would ask for — and because the
# alternative is re-running every review whenever boilerplate is touched.
_REVIEW_IGNORED_LINE = re.compile(
    r"^(?:Edinburgh, Scotland, UK \|"
    r"|Portfolio Website:"
    r"|\*\*Hokkai[^\n]*\|[^\n]*\*\*"
    r"|\*\*Escuela Falcon[^\n]*\*\*"
    r"|\*\*Languages:\*\*)",
)


def review_source_sha(md_path: Path | None = None, document: str | None = None) -> str:
    """The identity of what a review actually judged.

    Both the writer and the freshness check must ask the same question, so they
    ask it here. They used to compute it separately — run_review hashed the
    document string it had just written the backlink into, review_is_current
    hashed the file's raw bytes — which happened to agree only because the two
    were the same bytes; any divergence in preprocessing would have silently
    marked every fresh review stale, the way the PDF badge did.

    Frontmatter is excluded: run_review writes a `review:` link back into the
    document it is reviewing, so hashing it would mean every review invalidated
    itself the moment it was written.
    """
    text = document if document is not None else md_path.read_text(encoding="utf-8")
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)
    kept = [l for l in text.split("\n") if not _REVIEW_IGNORED_LINE.match(l.strip())]
    return hashlib.sha1("\n".join(kept).strip().encode()).hexdigest()


def _mark_unusable_bridge_suggestions(body: str) -> str:
    """Neutralise replacement sentences the bridge generator would reject.

    Told plainly not to, the reviewer still proposes "aligns with" and
    "resonates with" for "feels relevant to" on roughly half of runs — the pull
    toward a stronger connector is hard to instruct away. Those words are in
    _BRIDGE_NEVER_ECHO, so applying such a fix writes a sentence the next
    regeneration throws out; worse, apply_review_fixes can push it into the
    authored sources. Dropping the finding outright would hide the reviewer's
    reasoning, so the quote marker is stripped instead: parse_review_fixes only
    lifts **"..."** quotes, so an un-marked line is visible but not applicable.
    """
    from cover_letter_generator import _BRIDGE_NEVER_ECHO

    banned = tuple(p for p in _BRIDGE_NEVER_ECHO if len(p) > 4) + ("align",)

    def _defuse(match: re.Match) -> str:
        replacement = match.group(2)
        if not any(word in replacement.lower() for word in banned):
            return match.group(0)
        # Drop the quotes, not the text: parse_review_fixes pairs a finding only
        # when it can read a quoted replacement, so an unquoted one stays
        # readable while ceasing to be applicable.
        return (f'{match.group(1)}: ~~{replacement}~~ '
                f'← 適用不可（生成側の bridge ゲートが却下する語を含む）')

    # Same shape parse_review_fixes reads a replacement out of, so anything it
    # would lift is something this has already had the chance to defuse.
    return re.sub(r'((?:修正案|Fix)\*{0,2})\s*[::]\s*\*{0,2}"(.+?)"\*{0,2}',
                  _defuse, body, flags=re.DOTALL)


def _review_is_unusable(body: str, doc_kind: str) -> str | None:
    """Why this reply cannot be stored as a review, or None if it can.

    The provider chain fell through on exceptions only, so a model that
    answered 200 with an empty or off-format body ended the search. Weaker
    models do exactly that under a 62k-character prompt: they reply, briefly,
    with nothing the format asks for. The result is indistinguishable from a
    clean review once written — same `submission_score: null`, same
    `fact_block: false` — so it reads as "reviewed, nothing found" forever.

    Checks the shape the prompt asks for, not the content: at least one of the
    three finding headings, and for a CV the YAML rubric the score comes from.
    """
    text = (body or "").strip()
    if len(text) < 200:
        return f"body is {len(text)} chars"
    if not re.search(r"###?\s*(❗|🎯|✍️)", text):
        return "no finding sections"
    if doc_kind == "CV" and not re.search(r"```yaml\s*\n.*?rubric", text, re.DOTALL):
        return "no rubric block"
    return None


def run_review(doc_kind: str, md_path: Path, job: dict) -> Path:
    """Review a CV or CL markdown against its job. Returns the review file path.

    doc_kind: "CV" or "CL". job: dict with company/title/description.
    Raises on LLM failure — the caller surfaces the error; no silent fallback,
    a review that silently degrades to a weak model would be worse than none.
    """
    document = _ensure_review_backlink(md_path)
    doc_sha = review_source_sha(document=document)

    prompt = REVIEW_PROMPT.format(
        doc_kind=doc_kind,
        company=job.get("company", ""),
        job_title=job.get("title", ""),
        job_description=(job.get("description") or job.get("snippet") or "")[:3500],
        persona=_load_review_facts(),
        skills=_load_skills_md(),
        decisions=_load_decisions(),
        document=document[:7000],
        scope_section=(CL_SCOPE_INSTRUCTION if doc_kind == "CL"
                       else CV_RUBRIC_INSTRUCTION),
        translation_section=CL_TRANSLATION_INSTRUCTION if doc_kind == "CL" else "",
    )
    # Try each (provider, model) in turn; a single model name is provider-
    # specific, so we drive the fallback here (use_fallbacks=False) instead of
    # letting call_llm reuse REVIEW_MODEL against the wrong provider.
    system_prompt = (
        "You are a rigorous, honest application-document reviewer. "
        "Output only the requested markdown findings — never a rewritten document."
    )
    review_body = None
    used_model = REVIEW_MODEL
    errors: list[str] = []
    for prov, model in _review_chain():
        try:
            candidate = call_llm(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=system_prompt,
                temperature=0.2,
                max_tokens=4000,  # findings + full Japanese translation of the doc
                provider=prov,
                model=model,
                use_fallbacks=False,
            )
        except Exception as e:  # missing key, rate limit, bad model id, timeout
            errors.append(f"{prov}:{model}: {e}")
            continue
        unusable = _review_is_unusable(candidate, doc_kind)
        if unusable:
            # Returning 200 with nothing in it is the failure mode a try/except
            # cannot see, and it is not hypothetical: 28 CL and 3 CV reviews
            # were written on 2026-08-12 carrying only frontmatter and "未算出".
            # The local fallback answered every one of them — it is the only
            # entry in the chain that accepts a 62k-character prompt, so once
            # mistral and zai are rate-limited every review lands there, and it
            # does not follow the output format. A review that says nothing is
            # worse than no review: nothing distinguishes it in frontmatter
            # from a clean one, so it reads as "checked, no findings".
            errors.append(f"{prov}:{model}: {unusable}")
            print(f"  ⚠ {prov} returned an unusable review ({unusable}); trying next")
            continue
        review_body = candidate
        used_model = f"{prov}/{model}"
        break
    if review_body is None:
        raise RuntimeError("All review providers failed — " + "; ".join(errors))

    if doc_kind == "CL":
        review_body = _mark_unusable_bridge_suggestions(review_body)
    else:
        # Before _extract_score reads it, so the stored score and the stored
        # rubric agree — invariants recompute from the body on disk and would
        # otherwise report every corrected review as drifted.
        review_body, demoted = verify_rubric_evidence(review_body, document)
        for requirement in demoted:
            print(f"  ⚠ rubric Strong→Weak, evidence not in the CV: {requirement}")

    # Deterministic score from the rubric; ready is derived with the CURRENT
    # config threshold (display recomputes live, this is for nightly filters)
    score, fact_block, style_nits = _extract_score(review_body)
    ready = score is not None and not fact_block and score >= get_score_threshold()

    # Mirror the score into the body too (not just frontmatter) so it stays
    # visible where Properties are collapsed/stripped — inserted right before
    # 総評 since that section is the natural "so what" reader checkpoint.
    score_line = _score_line(score, fact_block, style_nits)
    if re.search(r'###\s*総評', review_body):
        review_body = re.sub(r'(###\s*総評)', f'{score_line}\n\n\\1', review_body, count=1)
    else:
        review_body = review_body.rstrip() + f"\n\n{score_line}\n"

    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    stem = md_path.stem  # e.g. Wordsmith_AI_Product_Designer_CV
    review_path = REVIEWS_DIR / f"{stem}_review.md"
    base = stem[:-3] if stem.endswith(("_CV", "_CL")) else stem
    frontmatter = f"""---
type: "review"
doc: "[[{stem}]]"
match_report: "[[{base}]]"
reviewed_sha: "{doc_sha}"
review_model: "{used_model}"
reviewed_at: {date.today().isoformat()}
submission_score: {score if score is not None else "null"}
style_nits: {style_nits}
fact_block: {"true" if fact_block else "false"}
submission_ready: {"true" if ready else "false"}
---

"""
    # A re-review overwrites the same file — archive the old one first so any
    # user annotations / dialogue history survive.
    if review_path.exists():
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        (ARCHIVE_DIR / f"{stem}_review_{datetime.now():%Y%m%d_%H%M%S}.md").write_text(
            review_path.read_text(encoding="utf-8"), encoding="utf-8")

    content = frontmatter + review_body.strip() + "\n"
    review_path.write_text(content, encoding="utf-8")
    # Pristine copy = annotation-detection baseline: anything the user later
    # adds in Obsidian shows up as a diff against this.
    PRISTINE_DIR.mkdir(parents=True, exist_ok=True)
    (PRISTINE_DIR / review_path.name).write_text(content, encoding="utf-8")
    return review_path


def get_score_threshold() -> int:
    """Submission threshold, adjustable in config.yaml (review_score_threshold)."""
    try:
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text()) or {}
        return int(cfg.get("review_score_threshold", 85))
    except Exception:
        return 85


# Top-level list items in review sections — findings are written as "- **\"…\"**"
# bullets, sometimes "*" or numbered. The original pattern missed "-" entirely,
# which made the fact hard-block dead code and the style penalty always zero.
_ITEM_RE = re.compile(r'^\s*(?:[-*]\s+|\d+\.\s+)', re.MULTILINE)

# "- **問題なし**。…" is how the reviewer reports a clean section — a bullet, but
# the opposite of a finding.
_NO_FINDING_RE = re.compile(r'(問題なし|特に(は)?なし|該当なし|指摘なし|なし。)')


def _has_findings(section: str) -> bool:
    """True when a review section lists actual findings, not a clean result."""
    for line in section.splitlines():
        if not _ITEM_RE.match(line):
            continue
        if _NO_FINDING_RE.search(line):
            continue
        if line.strip(" -*0123456789."):
            return True
    return False


def _extract_score(text: str) -> tuple[int | None, bool]:
    """(submission_score or None, fact_block, style_nits) from a review body.

    score is None when the review has no parseable rubric (pre-rubric reviews,
    or the LLM dropped the YAML block) — an unknown score must never be
    reported as 100.
    fact_block: the ❗事実 section has findings → not submittable regardless
    of score.
    style_nits: count of ✍️ 文体 findings. Reported alongside the score, NOT
    subtracted from it. It used to be a penalty of up to -30 on a 30-100 rubric
    scale, which was wrong three ways: 84% of reviews hit the cap so it acted
    as a constant offset (and made the 85 threshold unreachable — max was
    100-30=70); nit count correlated POSITIVELY with rubric coverage (r=+0.42,
    because a well-matched job earns a longer review), so it punished the best
    fits hardest and produced 287 ranking inversions; and the nits target
    reused CV blocks, so they say nothing about job fit. Style is pre-submission
    editing work — a separate axis from whether the role fits at all.
    """
    score: int | None = None

    # 1. Rubric → coverage (up to 70 pts on a 30-pt base)
    rubric_match = re.search(r'```yaml\s*\n(.*?)\n```', text, re.DOTALL)
    if rubric_match:
        try:
            rubric = (yaml.safe_load(rubric_match.group(1)) or {}).get('rubric', [])
            if rubric:
                req_score = 0.0
                for item in rubric:
                    ev = str(item.get('evidence', '')).lower()
                    req_score += 1.0 if ev == 'strong' else 0.5 if ev == 'weak' else 0.0
                score = int(30 + 70 * req_score / len(rubric))
        except Exception as e:
            print(f"  ⚠ rubric parse error: {e}")

    # 2. ❗事実 findings → hard block
    #    The reviewer states a clean result as a bullet ("- **問題なし**。…"), so
    #    counting bullets alone blocked documents the reviewer had just cleared.
    #    Only bullets that are not such a statement count as findings.
    fact_block = False
    fact_match = re.search(r'###\s*❗\s*事実(.*?)(?=\n###|\Z)', text, re.DOTALL)
    if fact_match and _has_findings(fact_match.group(1)):
        fact_block = True

    # 3. Style nits — counted and reported, never subtracted (see docstring)
    style_nits = 0
    style_match = re.search(r'###\s*✍️\s*文体(.*?)(?=\n###|\n##\s|\Z)', text, re.DOTALL)
    if style_match and _has_findings(style_match.group(1)):
        style_nits = len(_ITEM_RE.findall(style_match.group(1)))
    if score is not None:
        score = max(0, min(100, score))

    return score, fact_block, style_nits


def _score_line(score: int | None, fact_block: bool, style_nits: int = 0) -> str:
    """One-line submission badge for the review BODY (same wording as
    app.py's _score_badge, which reads the frontmatter copy) — keeps the
    number visible even where Properties are hidden (mobile, print, sync
    clients that don't render frontmatter). Style nits ride along as editing
    workload, deliberately outside the score (see _extract_score)."""
    nits_txt = f" / 文体指摘 {style_nits}件" if style_nits else ""
    if fact_block:
        score_txt = f" {score}%" if score is not None else ""
        return f"**提出スコア:**{score_txt} ⛔ 事実要修正{nits_txt}"
    if score is None:
        return f"**提出スコア:** ⚪ 未算出{nits_txt}"
    threshold = get_score_threshold()
    verdict = "🟢 提出可" if score >= threshold else "🔴 要修正"
    return f"**提出スコア:** {score}/100 (基準 {threshold}) {verdict}{nits_txt}"


def detect_annotations(review_path: Path) -> list[str] | None:
    """User-added lines in a review (free-form Obsidian annotations), found by
    diffing against the pristine copy saved at review time. Returns [] when
    the review is untouched, the added lines when it was annotated, and None
    when no pristine baseline exists (pre-feature review — can't tell)."""
    import difflib
    pristine = PRISTINE_DIR / review_path.name
    if not review_path.exists() or not pristine.exists():
        return None
    a = pristine.read_text(encoding="utf-8").splitlines()
    b = review_path.read_text(encoding="utf-8").splitlines()
    added: list[str] = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            added += [l.strip() for l in b[j1:j2] if l.strip()]
    return added


ANNOTATION_PROMPT = """You are the same rigorous UK hiring reviewer who wrote the review below. The candidate has ANNOTATED it in place with their own comments — questions, objections, and agreements, mostly in Japanese (often as indented bullets under a finding).

## JOB POSTING
Company: {company}
Title: {job_title}
Description (excerpt):
{job_description}

## CANDIDATE — VERIFIED FACTS (authoritative)
{persona}

## THE DOCUMENT UNDER REVIEW ({doc_kind})
{document}

## SETTLED MATTERS — 既決事項 (already ruled on; never re-open)
{decisions}

## REUSABLE SOURCE FILES (shared masters — quoted lines in some findings come from these files; an edit here propagates to EVERY generated CV/CL)
{sources}

## THE ANNOTATED REVIEW (original findings + the candidate's added comments)
{review}

{annotation_hint}

TASK — produce a fully REVISED review body (same three categories ❗事実 / 🎯求人適合 / ✍️文体, same format):
1. For every candidate comment, keep the comment in place and add a direct reply on the next line, formatted exactly as: `> 💬 回答: <日本語の回答>`
2. If the comment makes a VALID point (e.g. cites real evidence from the document or verified facts), revise that finding's 修正案 accordingly — or withdraw the finding entirely, replacing it with a one-line note `> 💬 回答: <理由により取り下げ>`. Do not cave to invalid arguments — if the objection is not supported by the document or verified facts, say so honestly and keep the 修正案.
3. When a comment asks for the fix at the SOURCE (e.g. 「参照元から編集」「元ファイルを直す」), work from the ACTUAL source file text above: rewrite the 修正案 so its 引用 matches the source file's current wording exactly, and name the target file in the reply (`> 💬 回答: … — 対象: profile: product_designer.md`). If the quoted line is not in any source file above, say so instead of guessing.
4. Findings the candidate did NOT comment on: reproduce them verbatim, unchanged.
5. Keep the 総評 (update it if findings changed) and any 和訳 section as-is.
6. If the dialogue SETTLES a matter that future reviews (of ANY document) should not re-flag — the candidate overruled a style opinion, or a recurring source-level point was decided — append at the very end a section exactly:
   `## 新規決定事項`
   with one bullet per settled matter, phrased as a standing instruction in Japanese (e.g. "「…」という表現は候補者の意図的な選択 — 再指摘しない"). Omit the section entirely if nothing was settled beyond this document.
7. Output ONLY the revised review body in markdown — no frontmatter, no preamble."""


def respond_to_annotations(doc_kind: str, md_path: Path, job: dict) -> Path:
    """Read the user's in-review annotations, reply to each, and revise the
    affected 修正案 — writing the result back as the new review (+ pristine
    baseline, so the dialogue can continue in further rounds). The old
    annotated version is archived first."""
    is_cur, review_path = review_is_current(md_path)
    if not review_path or not review_path.exists():
        raise FileNotFoundError(f"no review found for {md_path.name}")

    import re
    text = review_path.read_text(encoding="utf-8")
    m = re.match(r"\A(---\n.*?\n---\n)", text, flags=re.DOTALL)
    fm, body = (m.group(1), text[m.end():]) if m else ("", text)

    notes = detect_annotations(review_path)
    hint = ""
    if notes:
        hint = ("Candidate-added lines detected by diff (reply to each):\n"
                + "\n".join(f"- {n}" for n in notes[:30]))

    # 「参照元から編集」 requests are meaningless unless the LLM can see the
    # source files the quoted lines came from — inject the traced ones.
    src_blocks, seen_src = [], set()
    for _q, label in trace_finding_sources(review_path):
        if not label or label in seen_src:
            continue
        seen_src.add(label)
        kind, fname = label.split(": ", 1)
        d = next((d for k, d, _p in _SOURCE_GLOBS if k == kind), None)
        f = d / fname if d else None
        if f and f.exists():
            src_blocks.append(f"### {label}\n{f.read_text(encoding='utf-8')[:2500]}")
    sources = "\n\n".join(src_blocks) or "(no reusable source files traced for this review)"

    prompt = ANNOTATION_PROMPT.format(
        doc_kind=doc_kind,
        company=job.get("company", ""),
        job_title=job.get("title", ""),
        job_description=(job.get("description") or job.get("snippet") or "")[:3000],
        persona=_load_review_facts(),
        decisions=_load_decisions(),
        sources=sources[:8000],
        document=md_path.read_text(encoding="utf-8")[:6000],
        review=body[:6000],
        annotation_hint=hint,
    )
    system_prompt = (
        "You are a rigorous, honest application-document reviewer replying to the "
        "candidate's annotations. Output only the revised review body."
    )
    new_body, errors = None, []
    for prov, model in _review_chain():
        try:
            new_body = call_llm(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=system_prompt,
                temperature=0.2,
                max_tokens=4000,
                provider=prov,
                model=model,
                use_fallbacks=False,
            )
            break
        except Exception as e:
            errors.append(f"{prov}:{model}: {e}")
    if not new_body or not new_body.strip():
        raise RuntimeError("All providers failed — " + "; ".join(errors))

    from datetime import datetime
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    (ARCHIVE_DIR / f"{review_path.stem}_{datetime.now():%Y%m%d_%H%M%S}.md").write_text(text, encoding="utf-8")

    # Settled matters from this dialogue go to the ledger — every FUTURE
    # review reads it, so the same point is never argued twice.
    new_body = new_body.strip()
    parts = re.split(r"\n##\s*新規決定事項\s*\n", new_body, maxsplit=1)
    if len(parts) == 2:
        new_body, decided = parts[0].strip(), parts[1].strip()
        bullets = [l for l in decided.splitlines() if l.strip().startswith(("-", "*", "•"))]
        if bullets:
            stamp = f"{datetime.now():%Y-%m-%d} ({review_path.stem})"
            entry = f"\n### {stamp}\n" + "\n".join(bullets) + "\n"
            if DECISIONS_FILE.exists():
                DECISIONS_FILE.write_text(
                    DECISIONS_FILE.read_text(encoding="utf-8").rstrip() + "\n" + entry,
                    encoding="utf-8")
            else:
                DECISIONS_FILE.write_text(
                    "# レビュー決定台帳\n\n全レビューのプロンプトに注入され、既決事項の再指摘を防ぐ。\n" + entry,
                    encoding="utf-8")

    # Dialogue may withdraw findings or change the rubric — recompute the
    # score so the badge tracks the revised review, not the original.
    score, fact_block, style_nits = _extract_score(new_body)
    ready = score is not None and not fact_block and score >= get_score_threshold()
    for key, val in (("submission_score", score if score is not None else "null"),
                     ("style_nits", style_nits),
                     ("fact_block", "true" if fact_block else "false"),
                     ("submission_ready", "true" if ready else "false")):
        if re.search(rf"^{key}:", fm, flags=re.MULTILINE):
            fm = re.sub(rf"^{key}:.*$", f"{key}: {val}", fm, flags=re.MULTILINE)
        elif key == "style_nits":
            # Review predates the score/style split — add the field after
            # submission_score rather than appending past the closing "---".
            fm = re.sub(r"^(submission_score:.*)$", rf"\1\nstyle_nits: {val}",
                        fm, count=1, flags=re.MULTILINE)

    # Replace (not duplicate) the in-body score line — the LLM saw it in the
    # prompt and may have echoed the old one back verbatim.
    score_line = _score_line(score, fact_block)
    new_body = re.sub(r'\*\*提出スコア:\*\*.*\n?', '', new_body)
    if re.search(r'###\s*総評', new_body):
        new_body = re.sub(r'(###\s*総評)', f'{score_line}\n\n\\1', new_body, count=1)
    else:
        new_body = new_body.rstrip() + f"\n\n{score_line}\n"

    content = fm + new_body + "\n"
    review_path.write_text(content, encoding="utf-8")
    PRISTINE_DIR.mkdir(parents=True, exist_ok=True)
    (PRISTINE_DIR / review_path.name).write_text(content, encoding="utf-8")
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
    # Never mine the translation block for fixes — it is Japanese prose, not
    # findings, and any quotes in it are not replacements. Every heading the
    # translation has ever been filed under has to stay listed: reviews on disk
    # are not regenerated when the instruction changes, so dropping an old name
    # would start mining years of stored reviews for fixes. (全文和訳 →
    # 冒頭段落の和訳 → Bridge の和訳, as the letter's variable part moved.)
    text = re.split(r"\n#+\s*(?:全文和訳|冒頭段落の和訳|Bridge の和訳)",
                    text, maxsplit=1)[0]
    pairs = []
    # A finding starts with a list marker — "- ", "* " or a numbered "1." — then
    # the verbatim quote in **"..."**, and later offers 修正案:/Fix: "<replacement>"
    # (the replacement may or may not be wrapped in * / **). Split into one block
    # per finding so a quote is paired only with its own fix.
    blocks = re.split(r'\n(?=(?:[-*]\s+|\d+\.\s+)\*\*")', text)
    for block in blocks:
        mq = re.search(r'\*\*"(.+?)"\*\*', block, flags=re.DOTALL)
        if not mq:
            continue
        # Label may be bolded (**修正案**:) — the dialogue LLM drifts formats.
        mf = re.search(
            r'(?:修正案|Fix)\*{0,2}\s*[::]\s*\*{0,2}"(.+?)"\*{0,2}',
            block, flags=re.DOTALL,
        )
        if not mf:
            continue
        original = mq.group(1).strip()
        replacement = mf.group(1).strip()
        if original and replacement and original != replacement:
            pairs.append((original, replacement))
    return pairs


def apply_review_fixes(md_path: Path, review_path: Path,
                       only: set[str] | None = None) -> tuple[int, list[str]]:
    """Apply the review's suggested replacements to the document.

    Deterministic: each quoted original is replaced only where it matches the
    document verbatim. Returns (applied_count, unmatched_originals) — the
    unmatched ones need manual editing (the model paraphrased its quote, or
    the doc changed since the review). A pre-apply backup is written next to
    the review as .backups/<stem>.pre_apply.md.

    only: when given, restrict to fixes whose original is in the set (the UI
    lets the user pick a destination per fix).
    """
    doc = md_path.read_text(encoding="utf-8")
    backup = REVIEWS_DIR / ".backups" / f"{md_path.stem}.pre_apply.md"
    applied, unmatched = 0, []
    for original, replacement in parse_review_fixes(review_path):
        if only is not None and original not in only:
            continue
        if original in doc:
            doc = doc.replace(original, replacement, 1)
            applied += 1
        else:
            unmatched.append(original)
    if applied:
        # backup.parent, not REVIEWS_DIR: the target is REVIEWS_DIR/.backups, so
        # creating only REVIEWS_DIR left the write to fail wherever .backups did
        # not already happen to exist — losing the pre-apply copy at the one
        # moment it matters, right before the document is overwritten.
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
        md_path.write_text(doc, encoding="utf-8")
    return applied, unmatched


def _source_corpus() -> list[tuple[str, Path]]:
    """[(label, path)] of every reusable source file (profile/projects/…)."""
    corpus = []
    for kind, d, pat in _SOURCE_GLOBS:
        if d.exists():
            for f in sorted(d.glob(pat)):
                if f.name.startswith("archive"):
                    continue
                corpus.append((f"{kind}: {f.name}", f))
    return corpus


def _split_fm(text: str) -> tuple[str, str]:
    import re
    m = re.match(r"\A(---\n.*?\n---\n)", text, flags=re.DOTALL)
    return (m.group(1), text[m.end():]) if m else ("", text)


def fix_targets(review_path: Path) -> list[tuple[str, str, str | None, str | None]]:
    """[(original, replacement, source_label_or_None, why_not)] per parsed fix.

    source_label is set only when the quote matches a source file's BODY
    verbatim (frontmatter excluded) — i.e. the fix CAN be applied at the
    source. The UI uses this to offer a per-fix destination choice.

    When it is None, why_not says why, so the UI never silently omits the
    source option:
      "applied"     — the replacement is already in a source (applied earlier)
      "frontmatter" — quote lives only in a source's frontmatter (config, e.g.
                      role_tagline) — edit that deliberately, not via review
      "doc-only"    — the text is not in any master (LLM-generated per job)
    """
    files = _source_corpus()
    bodies = [(label, _split_fm(f.read_text(encoding="utf-8"))[1]) for label, f in files]
    fronts = [(label, _split_fm(f.read_text(encoding="utf-8"))[0]) for label, f in files]
    out = []
    for original, replacement in parse_review_fixes(review_path):
        src = next((label for label, body in bodies if original in body), None)
        why = None
        if not src:
            done = next((label for label, body in bodies if replacement in body), None)
            fm = next((label for label, front in fronts if original in front), None)
            why = f"applied:{done}" if done else (f"frontmatter:{fm}" if fm else "doc-only")
        out.append((original, replacement, src, why))
    return out


def apply_fixes_to_sources(review_path: Path,
                           only: set[str] | None = None) -> tuple[list[tuple[str, str]], list[str]]:
    """Apply review fixes to the reusable SOURCE files the quoted lines came
    from (profile / projects / toolkit / CL templates) — one edit there
    propagates to every future CV/CL, unlike apply_review_fixes which only
    patches the current document.

    Deterministic verbatim replace, same contract as apply_review_fixes.
    Returns (applied, unmatched):
      applied   — [(source_label, original), ...] actually replaced
      unmatched — originals that trace to a source file (normalized match)
                  but no longer match it verbatim (formatting drift / the
                  source changed since the review) — fix those by hand.
    Fixes whose quote is not found in any source file are skipped silently:
    they are document-level fixes, apply_review_fixes territory.
    Pre-edit backups: 15_reviews/.source_backups/<name>.<timestamp>.md

    only: when given, restrict to fixes whose original is in the set (the UI
    lets the user pick a destination per fix).
    """
    from datetime import datetime
    corpus = _source_corpus()
    backup_dir = REVIEWS_DIR / ".source_backups"
    applied: list[tuple[str, str]] = []
    unmatched: list[str] = []
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    for original, replacement in parse_review_fixes(review_path):
        if only is not None and original not in only:
            continue
        hit_label = None
        for label, f in corpus:
            content = f.read_text(encoding="utf-8")
            # Frontmatter is config (role_tagline, tags, …), not reviewable
            # prose — a quote matching only there must never be auto-replaced
            # (e.g. the settled brand tagline in a profile's role_tagline).
            fm, doc_body = _split_fm(content)
            if original in doc_body:
                backup_dir.mkdir(parents=True, exist_ok=True)
                (backup_dir / f"{f.stem}.{stamp}.md").write_text(content, encoding="utf-8")
                f.write_text(fm + doc_body.replace(original, replacement, 1), encoding="utf-8")
                applied.append((label, original))
                hit_label = label
                break
            if len(_norm(original)) >= 25 and _norm(original) in _norm(doc_body):
                hit_label = label  # traced but drifted — report, keep looking for verbatim
        else:
            if hit_label:
                unmatched.append(original)
    return applied, unmatched


def review_is_current(md_path: Path) -> tuple[bool, Path | None]:
    """(is_current, review_path): whether a review exists for md_path's CURRENT
    content. False+path = review exists but the doc was edited afterwards."""
    review_path = REVIEWS_DIR / f"{md_path.stem}_review.md"
    if not review_path.exists() or not md_path.exists():
        return False, review_path if review_path.exists() else None
    doc_sha = review_source_sha(md_path)
    head = review_path.read_text(encoding="utf-8")[:400]
    # Quotes optional: the file is written with them, but Obsidian rewrites the
    # frontmatter without them the first time the note is opened and edited, and
    # a substring test for the quoted form then failed to match its own stamp —
    # so any review the user had actually looked at reported itself stale.
    m = re.search(r'^reviewed_sha:\s*"?([0-9a-f]+)"?', head, re.MULTILINE)
    return (bool(m) and m.group(1) == doc_sha), review_path
