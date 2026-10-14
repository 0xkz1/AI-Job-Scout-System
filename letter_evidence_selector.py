"""Experimental CL routing: title-led profiles, literal facts, no generated prose."""
from __future__ import annotations

import re

import cover_letter_generator as cl
import cv_generator as cv

# These are selection preferences, not new facts or claims of job qualification.
PROFILES = [
    ("conversation", r"conversational?\s+(?:AI\s+)?design|conversation designer|dialogdesign|konversationsdesign|会話.*設計|対話.*デザイ",
     "product_designer", [("taifunome-research-platform", r"^Building"),
                          ("asset-weaver-obsidian-plugin", r"onboarding"),
                          ("portfolio_website", r"aria-modal")]),
    ("infrastructure", r"infrastructure|platform engineer|devops|site reliability|インフラ|基盤エンジニア",
     "platform_engineer", [("web3-node-ops", r"live services"),
                          ("ai-job-scout-system", r"^I designed"),
                          ("taifunome-research-platform", r"^Building")]),
    ("ai_workflow", r"AI solution architect|AI engineer|LLM engineer|machine learning|KI.*entwick|人工知能|機械学習",
     "research_engineer", [("ai-job-scout-system", r"^I designed"),
                          ("personal-priority-orchestrator", r"retrieval"),
                          ("taifunome-research-platform", r"^Building")]),
    ("implementation", r"(?:enterprise )?solutions engineer|implementation specialist|導入.*エンジニア",
     "implementation_specialist", [("ai-job-scout-system", r"^I built"),
                                   ("personal-priority-orchestrator", r"retrieval"),
                                   ("asset-weaver-obsidian-plugin", r"onboarding")]),
    ("research", r"research engineer|data analyst|data analysis|content analyst|リサーチ|データ分析",
     None, [("taifunome-research-platform", r"^Building"),
            ("ai-job-scout-system", r"^I built"),
            ("personal-priority-orchestrator", r"retrieval"),
            ("taifunome_studio", r"open-source intelligence")]),
    ("editorial", r"content editor|editorial designer|コンテンツ.*編集|redakteur",
     "content_analyst", [("taifunome_studio", r"open-source intelligence"),
                         ("portfolio_website", r"continuous narrative")]),
    ("web", r"front.?end|web developer|web engineer|interface developer|Web.*エンジニア|フロントエンド|ウェブ開発",
     "frontend_developer", [("taifunome-research-platform", r"^Building"),
                           ("portfolio_website", r"vanilla JavaScript"),
                           ("asset-weaver-obsidian-plugin", r"onboarding")]),
    ("product_interface", r"product designer|service designer|UX.*designer|UI.*designer|produktdesigner|プロダクト.*デザイ|サービス.*デザイ",
     "product_designer", [("taifunome-research-platform", r"^Building"),
                         ("asset-weaver-obsidian-plugin", r"onboarding"),
                         ("portfolio_website", r"aria-modal")]),
    ("visual", r"graphic.*designer|brand identity designer|grafikdesigner|digital designer|technical artist|illustrator|グラフィック|ビジュアル.*デザイ",
     None, [("taifunome-research-platform", r"^Building"),
            ("logo-design-for-myself", r"logo"),
            ("feral-bestiary-plate-001", r"visual language")]),
    ("interactive", r"creative technologist|creative technology|クリエイティブ.*テクノロ|kreativ.*technolog",
     "creative_technologist", [("taifunome-research-platform", r"^Building"),
                              ("taifunome-research-platform", r"TAIFU mode"),
                              ("portfolio_website", r"vanilla JavaScript")]),
]


def keyword_hits(posting: str, keywords: list[str]) -> int:
    """A 'visionary' posting does not ask for computer 'vision'."""
    return sum(bool(re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", posting, re.I))
               for k in keywords if k)


def choose_letter_evidence(job: dict) -> tuple[dict, list[dict]]:
    title, description = job["title"], job.get("description") or ""
    old_role = cv.detect_role_type(title, description)
    resolved = {**job, "original_role_type": old_role, "role_type": old_role,
                "letter_focus": None, "evidence_scope": "outside_prepared_scope",
                "evidence_gaps": [], "letter_role_reason": "no authored selection profile"}
    if len(description.strip()) < 200:
        resolved["evidence_scope"] = "insufficient_description"
        return resolved, []
    # Hardware 'frontend' is a different discipline from a browser frontend.
    if re.search(r"\b(?:ASIC|FPGA|VLSI)\b", title, re.I):
        resolved["letter_role_reason"] = "hardware frontend is outside the prepared web scope"
        return resolved, []
    profile = next((p for p in PROFILES if re.search(p[1], title, re.I)), None)
    if profile is None:
        return resolved, []
    focus, _, hint, priorities = profile
    if focus == "product_interface" and re.search(
            r"laser cutting|laser engrav|sublimation|personalised products|personalized products", description, re.I):
        resolved["letter_role_reason"] = "physical-product evidence/profile required; digital UX is insufficient"
        return resolved, []
    if focus == "interactive" and re.search(
            r"generative AI production pipeline|architect.{0,60}(?:generative )?AI|AI workflows", description, re.I):
        focus, _, hint, priorities = next(p for p in PROFILES if p[0] == "ai_workflow")
    role = hint or old_role
    # German/Japanese graphic titles may not be in the older CV role dictionary.
    if focus == "visual" and role == "general":
        role = "graphic_designer"
    resolved.update(role_type=role, letter_focus=focus,
                    letter_role_reason="title profile:" + focus)
    if focus == "conversation":
        resolved["evidence_gaps"].append("past conversation-flow, dialogue-management and voice delivery unconfirmed")
    if focus == "interactive" and re.search(r"physical|play.test|children|robotic|electronics|物理|子ども|児童|physisch", description, re.I):
        resolved["evidence_gaps"].append("physical/play-tested prototypes and child-user testing unconfirmed")
    live = {f["source_id"] for f in cl._load_evidence_bank()}
    facts = [f for f in cl._load_letter_facts() if role in f["roles"] and f["source_id"] in live]
    selected, groups = [], set()
    for source_id, pattern in priorities:
        matching = [f for f in facts if f["source_id"] == source_id and re.search(pattern, f["fact"], re.I)]
        matching.sort(key=lambda f: -keyword_hits(title + "\n" + description, f["keywords"]))
        if not matching:
            continue
        fact = matching[0]
        if fact in selected or (fact["group"] and fact["group"] in groups):
            continue
        selected.append(fact)
        if fact["group"]:
            groups.add(fact["group"])
        if len(selected) == 3:
            break
    resolved["evidence_scope"] = "covered" if selected else "no_grounded_evidence"
    return resolved, selected
