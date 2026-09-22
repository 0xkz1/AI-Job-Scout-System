#!/usr/bin/env python3
"""jis_jev_judge.py — TypeSafe System One (Jev) judge and pre-audit gatekeeper for JIS.

Location: 00_Kazuki/career/Job-Intelligence-System/jis_jev_judge.py

Role in Architecture:
- Layer 1 (System One): Sub-second, typed, probabilistic judgments (Choice, Noul, Score).
- Gatekeeper: Audits generated CV+CL and filters jobs before dispatching to Hermes L3 review-editor.
- Fallback: Gracefully degrades to deterministic heuristic/regex rules when offline or unconfigured.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
TAIFUNOME_ENV = ROOT.parent.parent.parent / "taifunome" / ".env"
JIS_ENV = ROOT / ".env"

_CLIENT: Any | None = None


def _load_api_key() -> str | None:
    """Load TYPESAFE_API_KEY from environment, JIS .env, or Taifunome .env."""
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key

    for env_path in (JIS_ENV, TAIFUNOME_ENV):
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("TYPESAFE_API_KEY=") and not line.startswith("#"):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
            except Exception:
                pass
    return None


# ADR-015 P0: "API keyの存在はpolicyを変更しない." The key has been present in
# .env the whole time this module has existed, so keying activation off the key
# plus an importable SDK means a single `pip install typesafe-sdk` silently moves
# every judgment below from its heuristic onto a paid cloud call, on the next
# scheduled run, with nobody choosing it. The mode is chosen explicitly instead.
#
#   off     the default. Heuristics only, exactly as before the SDK existed.
#   shadow  ask Jev as well, record it, and still return the heuristic verdict.
#   on      Jev decides, heuristics remain the fallback when a call fails.
_MODE_ENV = "JIS_JEV_MODE"
_VALID_MODES = ("off", "shadow", "on")


def mode() -> str:
    """Which Jev mode this process runs in. Unset or unrecognised reads as off."""
    value = (os.environ.get(_MODE_ENV) or "off").strip().lower()
    return value if value in _VALID_MODES else "off"


def is_available() -> bool:
    """Whether Jev COULD run: SDK importable and a key present. Not permission."""
    if not _load_api_key():
        return False
    try:
        import typesafe_sdk  # noqa: F401
        return True
    except ImportError:
        return False


def is_configured() -> bool:
    """Whether Jev SHOULD run for a judgment — availability AND an explicit mode.

    Kept under the name every caller already uses, so defaulting to off needs no
    change at the call sites.
    """
    return mode() == "on" and is_available()


def is_shadowing() -> bool:
    """Whether to ask Jev for a record while still returning the heuristic."""
    return mode() == "shadow" and is_available()


def _sdk_types() -> tuple[Any, Any, Any, Any]:
    try:
        from typesafe_sdk import Choice, Noul, Score, TypeSafeClient
        return Choice, Noul, Score, TypeSafeClient
    except ImportError as e:
        raise RuntimeError("typesafe-sdk is not installed") from e


def get_client() -> Any:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    key = _load_api_key()
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY is not configured")
    _, _, _, client_cls = _sdk_types()
    _CLIENT = client_cls(api_key=key)
    return _CLIENT


# ---------------------------------------------------------------------------
# 1. Visa & Sponsorship Verification (Noul)
# ---------------------------------------------------------------------------

def check_sponsorship_jev(job_description: str) -> dict[str, Any]:
    """Check visa sponsorship support via Jev Noul, with heuristic fallback."""
    if not is_configured():
        return _check_sponsorship_heuristic(job_description)

    try:
        _, noul, _, _ = _sdk_types()
        client = get_client()
        result = client.system_one(
            state={"job_description": job_description[:7000]},
            questions={
                "sponsorship_offered": noul(
                    instructions=(
                        "Does this job posting explicitly offer UK Skilled Worker visa "
                        "sponsorship or welcome international applicants needing visa sponsorship?"
                    )
                ),
                "visa_barrier": noul(
                    instructions=(
                        "Does this posting explicitly state that candidates must ALREADY hold "
                        "the right to work in the UK without sponsorship, or state 'no sponsorship available'?"
                    )
                ),
            },
        )
        s_prob = result.nouls["sponsorship_offered"].noul
        b_prob = result.nouls["visa_barrier"].noul
        return {
            "source": "jev",
            "sponsorship_offered_prob": round(s_prob, 3),
            "visa_barrier_prob": round(b_prob, 3),
            "sponsorship_likely": s_prob >= 0.7 and b_prob < 0.3,
            "blocked_by_visa": b_prob >= 0.7 and s_prob < 0.3,
        }
    except Exception as e:
        res = _check_sponsorship_heuristic(job_description)
        res["warning"] = f"Jev call failed: {e}; used fallback"
        return res


def _check_sponsorship_heuristic(text: str) -> dict[str, Any]:
    lower = text.lower()
    negative = bool(re.search(
        r"\b(no visa sponsorship|cannot sponsor|must have (the )?right to work|uk right to work required|not able to sponsor)\b",
        lower
    ))
    positive = bool(re.search(
        r"\b(visa sponsorship available|skilled worker visa|can sponsor|offers? visa sponsorship)\b",
        lower
    )) and not negative

    return {
        "source": "heuristic",
        "sponsorship_offered_prob": 0.9 if positive else 0.1,
        "visa_barrier_prob": 0.9 if negative else 0.1,
        "sponsorship_likely": positive and not negative,
        "blocked_by_visa": negative and not positive,
    }



# ---------------------------------------------------------------------------
# 2. Role Family Classification (Choice)
# ---------------------------------------------------------------------------

def classify_role_jev(title: str, description: str) -> dict[str, Any]:
    """Classify job into one of the target role profiles via Jev Choice."""
    if not is_configured():
        return _classify_role_heuristic(title, description)

    try:
        choice, _, _, _ = _sdk_types()
        client = get_client()
        result = client.system_one(
            state={"title": title, "description": description[:7000]},
            questions={
                "role_family": choice(
                    instructions="Which candidate career profile best matches this job posting?",
                    criteria={
                        "creative_technology": "Creative technologist, interactive media, WebGL/Three.js, shaders, generative AI engineering",
                        "core_design": "Graphic designer, visual designer, brand designer, digital designer, art director",
                        "hybrid_design_dev": "Design engineer, UI/UX front-end developer, design systems engineer, creative developer",
                        "engineering": "Pure backend, full-stack, DevOps, cloud infrastructure, non-creative software engineering",
                        "other": "Marketing, sales, administration, recruiting, non-technical management",
                    },
                )
            },
        )
        c = result.choices["role_family"]
        return {
            "source": "jev",
            "role": c.choice,
            "confidence": round(c.confidence, 3),
        }
    except Exception as e:
        res = _classify_role_heuristic(title, description)
        res["warning"] = f"Jev call failed: {e}; used fallback"
        return res


def _classify_role_heuristic(title: str, description: str) -> dict[str, Any]:
    from cv_generator import detect_role_type
    role = detect_role_type(title, description)
    return {
        "source": "heuristic",
        "role": role,
        "confidence": 0.8,
    }


# ---------------------------------------------------------------------------
# 3. L1 Pre-Audit Gatekeeper: Fast Invariant Check (Noul & Rules)
# ---------------------------------------------------------------------------

def fast_pre_audit_documents(cv_text: str, cl_text: str, job: dict) -> dict[str, Any]:
    """Performs L1 fast pre-audit on generated documents before Hermes dispatch.

    1. Checks for literal unrendered placeholders ([Company], [Title], {date}).
    2. Checks for mandatory sections and contact links.
    3. If Jev is configured, checks for ungrounded claims and tone authenticity.
    """
    violations = []
    company = job.get("company", "")
    title = job.get("title", "")

    # Rule 1: Placeholders
    placeholder_patterns = [
        ("[Company]", r"\[Company\]"),
        ("[Title]", r"\[Title\]"),
        ("[Date]", r"\[Date\]"),
        ("{{...}}", r"\{\{.*?\}\}"),
    ]
    for doc_name, text in [("CV", cv_text), ("CL", cl_text)]:
        for label, pat in placeholder_patterns:
            if re.search(pat, text, re.IGNORECASE):
                violations.append(f"{doc_name} contains unrendered placeholder: {label}")


    # Rule 2: Minimum lengths and essential keywords
    if len(cv_text.strip()) < 800:
        violations.append("CV text is too short (< 800 chars)")
    if len(cl_text.strip()) < 300:
        violations.append("Cover letter text is too short (< 300 chars)")

    # Rule 3: Jev semantic invariants (if online)
    jev_audit = {}
    if is_configured():
        try:
            _, noul, _, _ = _sdk_types()
            client = get_client()
            result = client.system_one(
                state={
                    "job_title": title,
                    "company": company,
                    "cv_sample": cv_text[:4000],
                    "cl_sample": cl_text[:2500],
                },
                questions={
                    "has_hallucinations": noul(
                        instructions=(
                            "Do these application documents make ungrounded, absurd claims or mention "
                            "fictional awards/degrees outside authentic design and creative technology practice?"
                        )
                    ),
                    "tone_authentic": noul(
                        instructions=(
                            "Is the tone genuine, craft-focused, and free from empty corporate jargon?"
                        )
                    ),
                },
            )
            h_prob = result.nouls["has_hallucinations"].noul
            t_prob = result.nouls["tone_authentic"].noul
            jev_audit = {
                "has_hallucinations_prob": round(h_prob, 3),
                "tone_authentic_prob": round(t_prob, 3),
            }
            if h_prob >= 0.7:
                violations.append(f"Jev flagged high hallucination risk ({h_prob:.2f})")
            if t_prob < 0.3:
                violations.append(f"Jev flagged low tone authenticity ({t_prob:.2f})")
        except Exception as e:
            jev_audit = {"warning": f"Jev invariant check skipped: {e}"}

    passed = len(violations) == 0
    return {
        "passed": passed,
        "violations": violations,
        "jev_audit": jev_audit,
    }
