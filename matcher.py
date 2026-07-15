"""
Match Analyzer
==============
Compares user profile (skills, experience, preferences) with job analysis
to calculate a match score and generate a detailed match report.
"""

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

# --- User Profile Loading ---

# Hardcoded to career project root since __file__ may be in workspace
USER_PROFILE_DIR = Path("/media/kz003/atelier/00_Kazuki")

SKILLS_FILE = USER_PROFILE_DIR / "skills.md"
ABOUT_FILE = USER_PROFILE_DIR / "about.md"


# --- Skill Embedding Fallback (lightweight TF-IDF) ---

_embedding_model = None


def _get_embedding_model():
    """Lazy init TF-IDF model. Returns None if sklearn unavailable."""
    global _embedding_model
    if _embedding_model is None and SKLEARN_AVAILABLE:
        _embedding_model = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
    return _embedding_model


def build_skill_embeddings(skill_names: list[str]):
    """Build TF-IDF matrix for a list of skill names."""
    if not SKLEARN_AVAILABLE or not skill_names:
        return None
    model = _get_embedding_model()
    if model is None:
        return None
    try:
        return model, model.fit_transform(skill_names)
    except Exception:
        return None


def skill_similarity(name_a: str, name_b: str) -> float:
    """Return cosine similarity [0,1] between two skill names."""
    if not SKLEARN_AVAILABLE:
        return 0.0
    # Don't use stop_words - removes short abbreviations like "ml", "ai", "py"
    model = TfidfVectorizer(ngram_range=(1, 2), stop_words=None)
    try:
        vecs = model.fit_transform([name_a, name_b])
        return float(cosine_similarity(vecs[0:1], vecs[1:2])[0, 0])
    except Exception:
        return 0.0


def load_user_skills() -> dict[str, list[str]]:
    """
    Parse skills.md and return categorized skills.
    Returns: {category: [skill_names]}
    """
    skills = {}
    current_category = None

    if not SKILLS_FILE.exists():
        return skills

    content = SKILLS_FILE.read_text(encoding="utf-8")

    for line in content.split("\n"):
        # Category headers: ## Category Name
        cat_match = re.match(r"^##\s+(.+)$", line)
        if cat_match:
            current_category = cat_match.group(1).strip()
            skills[current_category] = []
            continue

        # Table rows: | **Skill Name** | Level | Notes |
        row_match = re.match(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(\w+)\s*\|", line)
        if row_match and current_category:
            skill_name = row_match.group(1).strip()
            level = row_match.group(2).strip().lower()
            if level == "level":  # Skip header row
                continue
            skills[current_category].append({"name": skill_name, "level": level})

    return skills


def load_user_experience() -> dict[str, Any]:
    """
    Extract key experience facts from about.md using robust regex.
    """
    import datetime
    current_year = datetime.datetime.now().year

    exp = {
        "years_python": 0,
        "years_linux": 0,
        "years_creative": 0,
        "years_automation": 0,
        "location": "Edinburgh, UK",
        "work_eligibility": "UK eligible",
        "availability": "20-50 hours/week",
        "preferred_roles": [
            "Development Support",
            "Creative Technologist",
            "Technical Artist",
            "Web Developer",
            "Game Development",
        ],
    }

    if not ABOUT_FILE.exists():
        return exp

    content = ABOUT_FILE.read_text(encoding="utf-8")

    def extract_years(pattern: str) -> int:
        # Matches 'YYYY' or 'YYYY – Present' using a more flexible middle section
        match = re.search(rf"{pattern}.*?(\d{{4}})\s*[–\-]?\s*Present", content, re.IGNORECASE)
        if match:
            start_year = int(match.group(1))
            return max(1, current_year - start_year + 1)
        return 0

    # Based on about.md content structure
    # Feral: (2023 – Present) -> python/automation/linux context?
    # Architectural Visualization: (2025 – Present) -> creative context
    
    if "Feral" in content:
        yrs = extract_years("Feral")
        exp["years_python"] = yrs
        exp["years_automation"] = yrs
        exp["years_linux"] = yrs

    if "Architectural Visualization" in content:
        exp["years_creative"] = extract_years("Architectural Visualization")

    return exp


# --- Matching Logic ---

LEVEL_WEIGHTS = {
    "expert": 1.0,
    "advanced": 0.9,
    "proficient": 0.8,
    "intermediate": 0.6,
    "working knowledge": 0.5,
    "familiar": 0.4,
    "basic": 0.3,
    "unknown": 0.1,
    # Additional synonyms
    "beginner": 0.2,
    "entry": 0.2,
    "advanced intermediate": 0.7,
    "competent": 0.75,
    "skilled": 0.8,
    "working": 0.5,
}


# Common abbreviation / synonym mapping for skill names
SKILL_SYNONYMS = {
    "ml": "machine learning",
    "machine learning": "ml",
    "ai": "artificial intelligence",
    "ai/ml": "machine learning",
    "js": "javascript",
    "javascript": "js",
    "ts": "typescript",
    "typescript": "ts",
    "py": "python",
    "python": "py",
    "react.js": "react",
    "reactjs": "react",
    "next.js": "nextjs",
    "node.js": "nodejs",
    "nodejs": "node.js",
    "docker / kubernetes": "docker",
    "k8s": "kubernetes",
    "aws": "amazon web services",
    "amazon web services": "aws",
    "c#": "csharp",
    "csharp": "c#",
    "c++": "cpp",
    "cpp": "c++",
    "gcp": "google cloud platform",
    "golang": "go",
    "go": "golang",
    # Additional common abbreviations
    "ci/cd": "continuous integration",
    "continuous integration": "ci/cd",
    "mlops": "machine learning operations",
    "nlp": "natural language processing",
    "cv": "computer vision",
    "rest": "rest api",
    "api": "rest api",
    "sql": "postgresql",
    "postgres": "postgresql",
    "kubernetes": "k8s",
    "tf": "tensorflow",
    "pytorch": "torch",
    "hf": "huggingface",
    "llm": "large language model",
    "rag": "retrieval augmented generation",
    # Design synonyms — map job description variants to skills.md entries
    "design": "visual design",
    "designer": "visual design",
    "ui/ux": "ui/ux design",
    "ui ux": "ui/ux design",
    "ux": "ux design",
    "ux design": "ui/ux design",
    "ui design": "ui/ux design",
    "product design": "ui/ux design",
    "design thinking": "ui/ux design",
    "design system": "design systems",
    "component library": "design systems",
    "graphic design": "visual design",
    "art direction": "visual design",
    "visual communication": "visual design",
    "animation": "motion graphics",
    "motion design": "motion graphics",
    # Workflow / methodology synonyms
    "agile methodology": "agile",
    "agile development": "agile",
    "scrum": "agile",
    "kanban": "agile",
    "sprint planning": "agile",
    "iterative development": "agile",
    "rapid prototyping": "prototyping",
    "prototype": "prototyping",
    "wireframing": "prototyping",
    "wireframe": "prototyping",
    "mockup": "prototyping",
    "low-fidelity": "prototyping",
    "high-fidelity": "prototyping",
    "cross-functional": "cross-functional collaboration",
    "stakeholder communication": "cross-functional collaboration",
    "technical writing": "technical documentation",
    "documentation": "technical documentation",
}


# Common job-extracted terms that are too generic/ambiguous to be treated as skills.
NON_SKILL_FILTER: set[str] = {
    "make", "less",
    "problem solving", "creative", "innovation", "innovative",
    "interpersonal", "communication", "teamwork", "leadership",
    "time management", "critical thinking", "analytical",
    "analytical skills", "attention to detail", "problem solver",
    "proactive", "self motivated", "self-starter", "fast learner",
    "adaptability", "flexible", "multitasking", "multitask",
    "organizational", "organized", "planning", "prioritization",
    "customer service", "presentation", "presentation skills",
    "negotiation", "mentoring",
    "marketing", "sales", "administration", "management",
    "operations", "strategy", "business development",
}


def _is_non_skill(skill_name: str) -> bool:
    """Check if skill name is in non-skill filter (case-insensitive)."""
    return skill_name.lower().strip() in NON_SKILL_FILTER


def normalize_skill_name(name: str) -> str:
    """Normalize skill name for comparison."""
    return name.lower().strip().replace("-", " ").replace("_", " ")


def get_user_skill_level(user_skills: dict, skill_name: str) -> float:
    """Find user's proficiency level for a skill (0.0-1.0)."""
    normalized = normalize_skill_name(skill_name)

    for category, skills in user_skills.items():
        for skill in skills:
            if normalize_skill_name(skill["name"]) == normalized:
                return LEVEL_WEIGHTS.get(skill["level"], 0.3)

    # Synonym / abbreviation check
    if normalized in SKILL_SYNONYMS:
        synonym = SKILL_SYNONYMS[normalized]
        for category, skills in user_skills.items():
            for skill in skills:
                if normalize_skill_name(skill["name"]) == normalize_skill_name(synonym):
                    return LEVEL_WEIGHTS.get(skill["level"], 0.3)

    # Partial match (substring) — use word boundaries to prevent "java" matching "javascript"
    for category, skills in user_skills.items():
        for skill in skills:
            user_norm = normalize_skill_name(skill["name"])
            if re.search(r'\b' + re.escape(normalized) + r'\b', user_norm) or \
               re.search(r'\b' + re.escape(user_norm) + r'\b', normalized):
                return LEVEL_WEIGHTS.get(skill["level"], 0.3) * 0.7

    return 0.0


def _build_user_skill_embeddings(user_skills: dict):
    """Pre-build embeddings for all user skills. Returns list of (normalized_name, name, level)."""
    all_skills = []
    for category, skills in user_skills.items():
        for skill in skills:
            all_skills.append((normalize_skill_name(skill["name"]), skill["name"], skill["level"]))
    return all_skills


_EMBEDDING_MODEL_CACHE: dict | None = None


def _build_embedding_model(user_skill_list: list) -> tuple:
    """Build TF-IDF model once for all user skills."""
    global _EMBEDDING_MODEL_CACHE
    if _EMBEDDING_MODEL_CACHE is not None:
        return _EMBEDDING_MODEL_CACHE
    if not SKLEARN_AVAILABLE or not user_skill_list:
        _EMBEDDING_MODEL_CACHE = (None, None)
        return None, None
    try:
        user_names = [s[0] for s in user_skill_list]
        model = TfidfVectorizer(ngram_range=(1, 2), stop_words=None)
        model.fit(user_names)
        _EMBEDDING_MODEL_CACHE = (model, user_names)
        return model, user_names
    except Exception:
        _EMBEDDING_MODEL_CACHE = (None, None)
        return None, None


def _skill_name_embedding_similarity(job_skill: str, user_skill_list: list) -> float:
    """Return max embedding similarity between job_skill and any user skill.
    Uses cached TF-IDF model (fitted once on all user skills) for speed.
    """
    if not SKLEARN_AVAILABLE or not user_skill_list:
        return 0.0
    try:
        model, user_names = _build_embedding_model(user_skill_list)
        if model is None:
            return 0.0
        normalized = normalize_skill_name(job_skill)
        # Transform the single job skill against pre-fitted model
        job_vec = model.transform([normalized])
        user_vecs = model.transform(user_names)
        sims = cosine_similarity(job_vec, user_vecs)
        return float(sims.max())
    except Exception:
        return 0.0


def calculate_skill_match(job_skills: list[str], user_skills: dict) -> dict:
    """
    Calculate skill match score with embedding fallback.
    Returns: {score, matched_skills, missing_skills, partial_skills}
    """
    if not job_skills:
        return {"score": 0.3, "matched": [], "missing": [], "partial": []}

    user_skill_list = _build_user_skill_embeddings(user_skills)

    matched = []
    partial = []
    missing = []
    total_weight = 0.0
    matched_weight = 0.0

    for job_skill in job_skills:
        # Skip non-skill terms (too generic/ambiguous)
        if _is_non_skill(job_skill):
            continue
        level = get_user_skill_level(user_skills, job_skill)
        total_weight += 1.0

        if level >= 0.6:
            matched.append({"skill": job_skill, "level": level})
            matched_weight += 1.0  # Full match weight
        elif level >= 0.35:
            partial.append({"skill": job_skill, "level": level})
            matched_weight += 0.35  # Partial credit
        else:
            # Try embedding fallback for unmatched skills
            embed_sim = _skill_name_embedding_similarity(job_skill, user_skill_list)
            if embed_sim >= 0.85:
                # Treat as full match via semantic similarity
                matched.append({"skill": job_skill, "level": embed_sim})
                matched_weight += 1.0
            elif embed_sim >= 0.70:
                partial.append({"skill": job_skill, "level": embed_sim})
                matched_weight += 0.35
            else:
                missing.append(job_skill)

    # Raw proportion of coverage
    raw_score = matched_weight / total_weight if total_weight > 0 else 0.0

    # Also factor: what % of job skills were at least partially covered?
    covered = len(matched) + len(partial)
    coverage_ratio = covered / total_weight if total_weight > 0 else 0.0

    # Penalty for large gaps (many skills completely missing)
    gap_penalty = 0.0
    if coverage_ratio < 0.25:
        gap_penalty = 0.15
    elif coverage_ratio < 0.50:
        gap_penalty = 0.05

    # Combine: weighted coverage with gap penalty
    score = max(0.0, coverage_ratio - gap_penalty)

    # Boost for strong individual matches
    if matched:
        avg_match = sum(m["level"] for m in matched) / len(matched)
        score = min(1.0, score * (0.6 + 0.4 * avg_match))

    return {
        "score": round(score, 2),
        "matched": matched,
        "partial": partial,
        "missing": missing,
    }


def calculate_experience_match(job_level: str, user_exp: dict) -> dict:
    """
    Match job experience level with user background.
    Normalized to 0-1 scale based on proximity.
    """
    level_map = {
        "internship": 0,
        "entry_level": 1,
        "mid": 2,
        "senior": 3,
        "director": 5,
        "unknown": 2,
    }

    # User experience: sum all relevant years
    user_years = max(
        user_exp.get("years_python", 0),
        user_exp.get("years_linux", 0),
        user_exp.get("years_automation", 0),
        user_exp.get("years_creative", 0),
    )
    # Use the max of specific skill years (prevent summing overlapping years)
    user_total = user_years

    job_years = level_map.get(job_level, 2)

    # Score based on how well user experience overlaps with job requirements
    # If user has more than needed → still high match (overqualified is okay)
    # If user has less → penalize but not too harshly
    if user_total >= job_years:
        score = min(1.0, 0.85 + 0.05 * (user_total - job_years))
    else:
        diff = job_years - user_total
        if diff <= 1:
            score = 0.75  # Slightly under but close
        elif diff <= 2:
            score = 0.55  # Moderate gap
        else:
            score = 0.30  # Significant gap

    return {
        "score": round(score, 2),
        "job_level": job_level,
        "user_estimated_years": user_total,
        "note": f"Job asks for ~{job_level.replace('_', ' ')} ({job_years}+ years), you have ~{user_total} years relevant exp",
    }


def _is_remote_friendly(job_loc: str, work_style: str) -> bool:
    """Determine if the job is remote/hybrid friendly."""
    loc = job_loc.lower()
    style = work_style.lower() if work_style else ""
    if style in ("remote", "hybrid"):
        return True
    if "remote" in loc or "hybrid" in loc:
        return True
    return False


def _get_remote_score(job_loc: str, work_style: str) -> tuple:
    """Return (base_score, note) for location being UK-wide or remote."""
    loc = job_loc.lower()
    # If work style explicitly remote/hybrid
    if work_style and work_style in ("remote", "hybrid"):
        return 0.70, f"✅ {work_style.title()} work available (UK-wide)"
    if "remote" in loc:
        return 0.70, "✅ Remote work available (UK-wide)"
    if "hybrid" in loc:
        return 0.65, "✅ Hybrid work available"
    return None, None


def calculate_location_match(job_location: str, job_work_style: str, user_exp: dict) -> dict:
    """
    Match location and work style preferences.
    Returns 0.0-1.0 to allow actual variance in composite score.
    """
    user_loc = user_exp.get("location", "").lower()
    job_loc = (job_location or "").lower()
    work_style = (job_work_style or "").lower()

    score = 0.0
    notes = []
    remote_flag = False

    # Work style detection
    is_remote = _is_remote_friendly(job_loc, work_style)

    # Location match tiered scoring
    if job_loc == "remote" or (not job_loc and work_style == "remote"):
        score = 0.9  # Remote is excellent
        notes.append("✅ Fully remote")
        remote_flag = True
    elif not job_loc:
        score = 0.4  # Location not specified, neutral
        notes.append("⚠️ Location not specified")
    elif "edinburgh" in job_loc or "glasgow" in job_loc:
        score = 1.0  # Exact city match is perfect
        notes.append("✅ Exact location match (Edinburgh/Glasgow)")
    elif "scotland" in job_loc:
        score = 0.85  # Same country region
        notes.append("✅ Scotland-based")
    elif "london" in job_loc:
        # Remote-friendly London roles get a boost
        if is_remote:
            score = 0.60
            notes.append("ℹ️ London-based (remote/hybrid available)")
            remote_flag = True
        else:
            score = 0.35  # Major city but far
            notes.append("⚠️ London-based (requires relocation)")
    elif "manchester" in job_loc or "birmingham" in job_loc:
        if is_remote:
            score = 0.50
            notes.append("ℹ️ North/Mid England (remote/hybrid available)")
            remote_flag = True
        else:
            score = 0.25  # Northern England, possible but not great
            notes.append("⚠️ North/Mid England (possible commute/relocate)")
    elif any(city in job_loc for city in ["aberdeen", "dundee", "stirling", "inverness"]):
        score = 0.85  # Scotland cities, same region
        notes.append("✅ Scotland-based")
    elif any(city in job_loc for city in ["newcastle", "leeds", "sheffield", "liverpool"]):
        if is_remote:
            score = 0.50
            notes.append("ℹ️ Northern England (remote/hybrid available)")
            remote_flag = True
        else:
            score = 0.40  # Northern England, still accessible
            notes.append("ℹ️ Northern England (possible commute/relocate)")
    # UK-wide / remote with OK
    elif "united kingdom" in job_loc or "uk" in job_loc:
        rs = _get_remote_score(job_loc, work_style)
        if rs[0] is not None:
            score = rs[0]
            notes.append(rs[1])
            remote_flag = True
        else:
            score = 0.55  # UK-wide but not remote
            notes.append("ℹ️ UK-wide (location flexible)")
    # Europe / EU remote
    elif any(term in job_loc for term in ["europe", "eu ", "european"]) or job_loc.strip() == "eu":
        if is_remote:
            score = 0.60
            notes.append("✅ Europe / EU (remote work available)")
            remote_flag = True
        else:
            # Non-remote EU roles
            score = 0.20
            notes.append("⚠️ EU-based (possible relocation needed)")
    else:
        rs = _get_remote_score(job_loc, work_style)
        if rs[0] is not None:
            score = rs[0]
            notes.append(rs[1])
            remote_flag = True
        else:
            score = 0.15  # Unknown or non-UK
            notes.append(f"⚠️ Location: {job_location}")

    # Work style bonus/penalty (applied on top but capped at 1.0)
    work_style_bonus = 0.0
    if work_style == "remote":
        work_style_bonus = 0.05  # Small bonus for remote
        if "✅" not in str(notes):
            notes.append("✅ Work style: remote")
    elif work_style == "hybrid":
        work_style_bonus = 0.02
        notes.append("✅ Hybrid work")
    elif work_style == "onsite":
        if score < 0.5:
            work_style_bonus = -0.10  # Penalty: far away AND onsite
            notes.append("❌ On-site required (severe penalty with distant location)")
        else:
            notes.append("⚠️ On-site required")

    # Also factoring in work style from job location text
    if "remote" in job_loc and work_style != "remote":
        work_style_bonus = max(work_style_bonus, 0.03)
        if "fully remote" not in str(notes).lower():
            notes.append("✅ Mentions remote in location")

    final_score = min(1.0, max(0.0, score + work_style_bonus))
    return {"score": round(final_score, 2), "notes": notes}


def calculate_salary_match(job_salary: dict, min_expected: int = 30000) -> dict:
    """
    Match salary expectations. Returns 0.0-1.0 based on how well salary meets expectations.
    """
    # No salary info at all
    if not job_salary:
        return {"score": 0.60, "note": "Salary not specified"}

    if not job_salary.get("max") and not job_salary.get("min"):
        return {"score": 0.60, "note": "Salary not specified"}

    max_sal = job_salary.get("max", 0) or 0
    min_sal = job_salary.get("min", 0) or 0

    # Verify period is annual (not hourly)
    period = job_salary.get("period", "annual")

    if max_sal and max_sal < min_expected * 0.5:
        # Likely hourly rate mistakenly parsed as annual
        if period == "hourly":
            # Convert hourly to annual roughly (37.5 hrs/wk, 52 wks)
            max_sal = max_sal * 37.5 * 52 / 1000  # In thousands roughly
            min_sal = min_sal * 37.5 * 52 / 1000 if min_sal else 0
            if max_sal:
                max_sal = max_sal * 1000  # Back to actual
                min_sal = min_sal * 1000 if min_sal else 0

    if max_sal >= min_expected * 1.5:
        score = 1.0
        note = f"✅ £{max_sal:,.0f} well above minimum £{min_expected:,}"
    elif max_sal >= min_expected * 1.2:
        score = 0.95
        note = f"✅ £{max_sal:,.0f} comfortably above minimum £{min_expected:,}"
    elif max_sal >= min_expected:
        score = 0.85
        note = f"✅ £{max_sal:,.0f} meets minimum £{min_expected:,}"
    elif max_sal >= min_expected * 0.8:
        score = 0.65
        note = f"⚠️ £{max_sal:,.0f} slightly below minimum £{min_expected:,}"
    elif min_sal and min_sal >= min_expected:
        score = 0.75
        note = f"⚠️ Range £{min_sal:9,.0f}-£{max_sal:,.0f} meets minimum at low end"
    elif max_sal > 0:
        score = 0.35
        note = f"❌ £{max_sal:,.0f} well below minimum £{min_expected:,}"
    else:
        score = 0.60
        note = "Salary not specified"

    return {"score": round(score, 2), "note": note}


# --- Context / Ethos Matching (Phase 2) ---

from context_loader import ContextLoader

# Lazy-loaded context fragments (cached globally for batch efficiency)
_context_loader_instance = None
_context_fragments = None


def _get_context_text() -> str:
    """Load and cache user persona context text from 00_Kazuki/."""
    global _context_loader_instance, _context_fragments
    if _context_fragments is not None:
        return _context_fragments
    _context_loader_instance = ContextLoader()
    fragments = _context_loader_instance.load_all_contexts()
    _context_fragments = _context_loader_instance.get_combined_context_string()
    return _context_fragments


# --- Ollama LLM Context Match ---

import os as _os
import requests as _requests
import time as _time

_OLLAMA_CTX_ENDPOINT = _os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/chat")
_OLLAMA_CTX_MODEL = _os.getenv("OLLAMA_CONTEXT_MODEL", _os.getenv("OLLAMA_MODEL", "gemma-4-26b-a4b-it-gguf"))
_OLLAMA_CTX_TIMEOUT = int(_os.getenv("OLLAMA_TIMEOUT", "120"))
_OLLAMA_CTX_KEEP_ALIVE = _os.getenv("OLLAMA_KEEP_ALIVE", "10m")

_persona_cache = None

def _load_persona_summary() -> str:
    """Load and condense persona docs for the LLM prompt."""
    global _persona_cache
    if _persona_cache is not None:
        return _persona_cache
    persona_files = ["ethos.md", "about.md", "profile.md", "interests.md"]
    parts = []
    for fname in persona_files:
        fpath = USER_PROFILE_DIR / fname
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"--- {fname} ---\n{content[:2000]}")
    _persona_cache = "\n\n".join(parts) if parts else ""
    return _persona_cache


def _ollama_context_score(job_description: str, persona_summary: str) -> dict | None:
    """
    Ask Ollama LLM to rate context/ethos alignment on 0-100 scale.
    Returns {"score": float (0-1), "reasoning": str} or None on failure.
    """
    if not job_description or not persona_summary:
        return None

    prompt = f"""You are a career alignment analyst. Rate how well this job matches the candidate's personal philosophy, work style, and ethos.

## Candidate Profile
{persona_summary[:3000]}

## Job Description
{job_description[:5000]}

## Task
Score the alignment on 0-100 (0 = completely misaligned, 100 = perfect fit).
Consider: work philosophy, values, creative vs corporate culture, autonomy, local-first/open-source ethos, multi-disciplinary creative-engineer fit.

Note: The candidate is highly pragmatic in professional environments. Their personal ethos (e.g., running local AI, private agents, local-first workflows) represents their independent creative ideals and personal research preferences, but they are fully open to, and capable of, working with standard enterprise cloud services, third-party APIs, and corporate workflows. Do not penalize the score simply because a job uses cloud/enterprise systems instead of local-first tools; instead, focus on whether the candidate's core problem-solving ethos (e.g., reducing friction, automating pipelines, bridging design and engineering) aligns with the job's requirements.

Respond ONLY with JSON:
{{"score": <number 0-100>, "reasoning_en": "<detailed explanation in English — as long as needed to justify the score>", "reasoning_ja": "<日本語での説明 — スコアの根拠を詳しく書く>"}}

The reasoning should explain WHY this score, citing specific aspects of the job and candidate profile. Length is up to your judgment — write more for complex/nuanced cases, less for obvious ones. Be specific about what aligns or misaligns.
"""

    try:
        from llm_client import call_llm as _call_llm
        content = _call_llm(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You are a career alignment scoring engine. Output ONLY valid JSON.",
            temperature=0.1,
            max_tokens=4096,
        )

        import json, re
        matches = list(re.finditer(r'\{.*\}', content, re.DOTALL))
        for match in reversed(matches):
            try:
                data = json.loads(match.group())
                score = float(data.get("score", 50))
                reasoning_en = data.get("reasoning_en", data.get("reasoning", ""))
                reasoning_ja = data.get("reasoning_ja", "")
                # Combine: English + Japanese (for display in MD)
                if reasoning_ja:
                    reasoning = f"{reasoning_en}\n\n**和訳:** {reasoning_ja}"
                else:
                    reasoning = reasoning_en
                score = max(0, min(100, score)) / 100.0
                return {"score": round(score, 2), "reasoning": reasoning, "reasoning_en": reasoning_en, "reasoning_ja": reasoning_ja}
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
        return None
    except Exception:
        return None


def _ollama_job_summary(job_description: str) -> dict | None:
    """Generate a bilingual (English + Japanese) summary of a job description using Ollama."""
    if not job_description or len(job_description) < 50:
        return None

    prompt = f"""You are a job description summarizer. Summarize the following job description in 3-5 sentences.

Focus on: role, key responsibilities, required skills, team/company culture, and what makes this role distinctive.

Respond ONLY with JSON:
{{"summary_en": "<3-5 sentence summary in English>", "summary_ja": "<3-5文の日本語要約>"}}

## Job Description
{job_description[:5000]}
"""

    payload = {
        "model": _OLLAMA_CTX_MODEL,
        "messages": [
            {"role": "system", "content": "You are a job description summarizer. Output ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "keep_alive": _OLLAMA_CTX_KEEP_ALIVE,
    }

    try:
        resp = _requests.post(
            _OLLAMA_CTX_ENDPOINT,
            json=payload,
            timeout=_OLLAMA_CTX_TIMEOUT,
        )
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")

        import json
        matches = list(re.finditer(r'\{.*\}', content, re.DOTALL))
        for match in reversed(matches):
            try:
                data = json.loads(match.group())
                summary_en = data.get("summary_en", "")
                summary_ja = data.get("summary_ja", "")
                if summary_en or summary_ja:
                    return {"summary_en": summary_en, "summary_ja": summary_ja}
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
        return None
    except Exception:
        return None


def calculate_context_match(job_description: str) -> dict:
    """
    Calculate how well the job description aligns with the user's
    personal brand / philosophy / identity.

    Uses TF-IDF cosine similarity (fast). The heavy Ollama LLM-based
    context match is invoked separately via run.py --llm-context.
    """
    # --- TF-IDF fallback ---
    if not SKLEARN_AVAILABLE or not job_description:
        return {"score": 0.5, "reasoning": "", "top_terms": []}

    # Ensure context fragments are loaded
    _ = _get_context_text()
    global _context_loader_instance
    fragments = _context_loader_instance.load_all_contexts() if _context_loader_instance else []

    # Also get the raw ContextLoader fragments for per-doc comparison
    if not fragments:
        return {"score": 0.5, "reasoning": "No persona context loaded", "top_terms": []}

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        doc_scores = []
        best_sim = 0.0
        best_source = ""
        best_terms = []

        for frag in fragments:
            doc_text = frag.get("content", "")
            if not doc_text or len(doc_text) < 50:
                continue

            vec = TfidfVectorizer(
                ngram_range=(1, 2),
                stop_words="english",
                max_features=2000,
            )
            tfidf = vec.fit_transform([doc_text, job_description])
            sim = float(cosine_similarity(tfidf[0:1], tfidf[1:2])[0, 0])
            doc_scores.append(sim)

            if sim > best_sim:
                best_sim = sim
                best_source = frag.get("source", "")
                feature_names = vec.get_feature_names_out()
                job_vec = tfidf[1].toarray()[0]
                top_idx = job_vec.argsort()[-5:][::-1]
                best_terms = [feature_names[i] for i in top_idx if job_vec[i] > 0]

        best_sim = max(doc_scores) if doc_scores else 0.0

        # Score interpretation
        if best_sim >= 0.25:
            tier = "strong alignment"
        elif best_sim >= 0.12:
            tier = "moderate alignment"
        elif best_sim >= 0.04:
            tier = "slight alignment"
        else:
            tier = "minimal alignment"

        # Build reasoning
        reasons = []
        if best_terms:
            reasons.append(f"Resonant keywords: {', '.join(best_terms[:5])}")
        if best_sim >= 0.12:
            reasons.append(f"Language aligns with personal brand ({tier}) — best source: {best_source}")
        else:
            reasons.append(f"Job language differs from personal brand style ({tier})")

        # Normalize raw similarity to 0-1 range.
        # TF-IDF cosine similarity between persona docs and short job
        # metadata typically falls in 0.015-0.098 (measured on 507 jobs).
        # A raw *2.5 multiplier only produced 4-24% scores, squashing the
        # 29% weight to negligible contribution. Linear stretch maps the
        # observed 1st-99th percentile range to 0-100%.
        RAW_FLOOR = 0.015   # P1 observed
        RAW_CEIL = 0.079    # P99 observed
        if best_sim <= RAW_FLOOR:
            normalized = 0.0
        elif best_sim >= RAW_CEIL:
            normalized = 1.0
        else:
            normalized = (best_sim - RAW_FLOOR) / (RAW_CEIL - RAW_FLOOR)

        return {
            "score": round(normalized, 2),
            "raw_similarity": round(best_sim, 3),
            "reasoning": " | ".join(reasons),
            "top_terms": best_terms[:5],
            "tier": tier,
        }

    except Exception as e:
        return {"score": 0.5, "reasoning": f"Context analysis unavailable: {e}", "top_terms": []}


# --- Main Analysis ---

DEFAULT_WEIGHTS = {
    "skills": 0.35,
    "experience": 0.25,
    "location": 0.10,
    "salary": 0.01,
    "context": 0.29,
}


def calculate_title_relevance(title: str) -> float:
    """
    Check if the job title is relevant to target roles.
    Returns 1.0 if relevant, 0.0-0.1 if completely irrelevant.
    """
    if not title:
        return 0.5
        
    title_lower = title.lower()
    
    # Target keywords representing the candidate's field
    target_words = {
        "creative", "technologist", "technology", "development", "developer", "engineer", "engineering",
        "artist", "art", "technical", "web", "designer", "design", "builder", "programmer", "software",
        "qa", "testing", "data", "analyst", "analytics", "automation", "system", "systems", "admin",
        "administrator", "scrum", "product", "project", "game", "games", "frontend", "backend", "fullstack",
        "cloud", "devops", "infrastructure", "it", "support", "workflow", "pipeline", "tools", "tooling",
        "3d", "vfx", "rendering", "visualization", "graphics", "ui", "ux", "front-end", "back-end",
        "arbitrage", "scraping", "scraper"
    }
    
    words = re.findall(r'\b\w+\b', title_lower)
    has_target = any(w in target_words for w in words)
    
    # Explicit exclusion domains (red flags for non-IT / non-tech / non-creative)
    exclusion_words = {
        "nurse", "nursing", "care", "home", "cook", "chef", "driver", "driving", "warehouse", 
        "surveyor", "cleaner", "receptionist", "clinician", "medical", "practitioner", "therapist",
        "teaching", "teacher", "headteacher", "lecturer", "tutor", "salesperson", "cashier", "retail",
        "barista", "waiter", "waitress", "bartender", "delivery", "courier", "security", "guard",
        "psychologist", "psychiatrist", "psychology"
    }
    
    construction_words = {"construction", "site manager", "quantity surveyor", "bricklayer", "plumber", "electrician", "carpenter"}
    
    has_exclusion = any(w in exclusion_words for w in words) or any(cw in title_lower for cw in construction_words)
    
    if has_exclusion:
        return 0.0
        
    if not has_target:
        return 0.1  # Low score for completely unrelated titles
        
    return 1.0

def analyze_match(job: dict, config: dict, weights: dict | None = None, skip_summary: bool = False) -> dict:
    """
    Run all match analyses and return combined result.
    Pass custom weights via config['weights'] or weights parameter.
    If skip_summary=True, skip LLM job summary generation (faster batch mode).
    """
    user_skills = load_user_skills()
    user_exp = load_user_experience()

    analysis = job.get("analysis", {})
    job_skills = analysis.get("skills", [])
    job_level = analysis.get("experience_level", "unknown")
    job_work_style = analysis.get("work_style", "unknown")
    job_salary = analysis.get("salary", {})
    job_location = job.get("location", "")
    job_description = job.get("description", "") or job.get("snippet", "")

    # Detect if description is genuinely missing (< 100 chars means nothing useful)
    description_missing = not job_description or len(job_description.strip()) < 100

    if description_missing:
        # Build a minimal pseudo-description from metadata only (for partial scoring)
        parts = [job.get("title", ""), job.get("company", "")]
        if job_skills:
            parts.append("Skills: " + ", ".join(job_skills))
        if job_level and job_level != "unknown":
            parts.append(f"Experience level: {job_level}")
        if job_work_style and job_work_style != "unknown":
            parts.append(f"Work style: {job_work_style}")
        emp_types = analysis.get("employment_types", [])
        if emp_types and emp_types != ["unknown"]:
            parts.append("Employment: " + ", ".join(emp_types))
        job_description = ". ".join(p for p in parts if p)

    # Individual scores
    skill_match = calculate_skill_match(job_skills, user_skills)
    exp_match = calculate_experience_match(job_level, user_exp)
    loc_match = calculate_location_match(job_location, job_work_style, user_exp)
    sal_match = calculate_salary_match(job_salary, config.get("min_salary_gbp", 30000))
    # Check for pre-existing LLM context score from batch analysis
    existing_ctx = job.get("match", {}).get("context", {})
    if isinstance(existing_ctx, dict) and "score" in existing_ctx:
        ctx_match = existing_ctx
    else:
        # Use LLM for context scoring (or TF-IDF fallback)
        persona = _load_persona_summary()
        if persona and job_description:
            llm_ctx = _ollama_context_score(job_description, persona)
            if llm_ctx:
                ctx_match = llm_ctx
            else:
                ctx_match = calculate_context_match(job_description)  # TF-IDF fallback if Ollama fails
        else:
            ctx_match = calculate_context_match(job_description)

    # Weighted composite — accept custom weights from config or parameter
    w = weights or config.get("weights", DEFAULT_WEIGHTS)
    weights = {
        "skills": w.get("skills", 0.40),
        "experience": w.get("experience", 0.25),
        "location": w.get("location", 0.10),
        "salary": w.get("salary", 0.05),
        "context": w.get("context", 0.20),
    }

    composite = (
        skill_match["score"] * weights["skills"]
        + exp_match["score"] * weights["experience"]
        + loc_match["score"] * weights["location"]
        + sal_match["score"] * weights["salary"]
        + ctx_match["score"] * weights["context"]
    )

    # Title relevance filter
    relevance = calculate_title_relevance(job.get("title", ""))
    composite = composite * relevance

    # Determine tier
    if relevance < 0.5:
        tier = "🔴 Completely Irrelevant"
    elif composite >= 0.8:
        tier = "🟢 Strong Match"
    elif composite >= 0.6:
        tier = "🟡 Good Match"
    elif composite >= 0.4:
        tier = "🟠 Partial Match"
    else:
        tier = "🔴 Weak Match"

    # A) Generate bilingual job summary via LLM for 50%+ matches (skippable for batch mode)
    summary_en = ""
    summary_ja = ""
    if not skip_summary and composite >= 0.50 and job_description and len(job_description) >= 50:
        summary = _ollama_job_summary(job_description)
        if summary:
            summary_en = summary.get("summary_en", "")
            summary_ja = summary.get("summary_ja", "")

    return {
        "composite_score": round(composite, 2),
        "tier": tier,
        "description_missing": description_missing,
        "skills": skill_match,
        "experience": exp_match,
        "location": loc_match,
        "salary": sal_match,
        "context_score": ctx_match["score"],
        "context_reasoning": ctx_match["reasoning"],
        "context_reasoning_en": ctx_match.get("reasoning_en", ""),
        "context_reasoning_ja": ctx_match.get("reasoning_ja", ""),
        "context_top_terms": ctx_match.get("top_terms", []),
        "title_relevance": relevance,
        "weights": weights,
        "summary_en": summary_en,
        "summary_ja": summary_ja,
    }


# --- Report Generation ---

def make_safe_name(company: str, title: str) -> str:
    """Create a unified safe base name for all generated files (match, CV, CL)."""
    safe_company = re.sub(r'[^\w\s-]', '', company).strip().replace(' ', '_')[:30]
    safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:50]
    return f"{safe_company}_{safe_title}"


def _tier_short(tier: str) -> str:
    """Extract short tier name without emoji for frontmatter."""
    return tier.replace("🟢 ", "").replace("🟡 ", "").replace("🟠 ", "").replace("🔴 ", "").strip()


def generate_match_report(job: dict, match: dict, cv_filename: str | None = None, cl_filename: str | None = None) -> str:
    """
    Generate a Markdown match report with YAML frontmatter for Obsidian Dataview.
    Optionally include links to generated CV and cover letter files.
    """
    title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    location = job.get("location", "Unknown")
    url = job.get("url", "")
    score = match['composite_score']
    score_pct = int(score * 100)

    # YAML frontmatter for Dataview queries
    source = job.get("source", "unknown")
    jtype = job.get("type", "auto")
    scraped_at = job.get("scraped_at", "")
    saved_at = scraped_at[:10] if scraped_at else datetime.now().strftime("%Y-%m-%d")
    cv_link = f'\ncv: "[[{cv_filename.replace(".md", "")}]]"' if cv_filename else ""
    cl_link = f'\ncover_letter: "[[{cl_filename.replace(".md", "")}]]"' if cl_filename else ""
    
    frontmatter = f"""---
match_score: {score}
match_score_pct: {score_pct}
tier: "{_tier_short(match['tier'])}"
company: "{company}"
title: "{title}"
location: "{location}"
source: "{source}"
type: "{jtype}"
saved_at: {saved_at}
skills_score: {int(match['skills']['score'] * 100)}
experience_score: {int(match['experience']['score'] * 100)}
location_score: {int(match['location']['score'] * 100)}
salary_score: {int(match['salary']['score'] * 100)}
context_score: {int(match.get('context_score', 0) * 100)}
url: "{url}"{cv_link}{cl_link}
---"""

    # Warning banner if description was missing
    description_missing = match.get("description_missing", False)
    desc_warning = []
    if description_missing:
        desc_warning = [
            f"",
            f"> [!WARNING]",
            f"> **⚠️ 求人説明文が取得できませんでした / Job description unavailable**",
            f"> スコアはタイトル・会社名・メタデータのみをもとにした推定値です。信頼性は低いため参考程度にとどめてください。",
            f"> *(Scores are estimated from title/company/metadata only — treat as unreliable.)*",
            f"",
        ]

    lines = [
        frontmatter,
        f"",
        f"# Match Report: {title}",
        f"**Company:** {company}  |  **Location:** {location}",
        f"**URL:** {url}",
        f"",
        *desc_warning,
        f"## 🎯 Overall Match: {match['tier']} ({score_pct}%)",
        f"",
        f"---",
        f"",
        f"## 📊 Breakdown",
        f"",
        f"| Dimension | Score | Weight | Weighted |",
        f"|-----------|-------|--------|----------|",
    ]

    for dim, key in [
        ("Skills", "skills"),
        ("Experience", "experience"),
        ("Location", "location"),
        ("Salary", "salary"),
        ("Context/Ethos", "context_score"),
    ]:
        if key == "context_score":
            m_score = match.get("context_score", 0)
            w = match["weights"].get("context", 0) * 100
            weighted = m_score * match["weights"].get("context", 0) * 100
            lines.append(f"| {dim} | {m_score*100:.0f}% | {w:.0f}% | {weighted:.0f}% |")
        else:
            m = match[key]
            w = match["weights"][key.lower()] * 100
            weighted = m["score"] * match["weights"][key.lower()] * 100
            lines.append(f"| {dim} | {m['score']*100:.0f}% | {w:.0f}% | {weighted:.0f}% |")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## 🛠 Skills Match ({match['skills']['score']*100:.0f}%)",
        f"",
    ])

    if match["skills"]["matched"]:
        lines.append("### ✅ Strong Match")
        for skill in match["skills"]["matched"]:
            lines.append(f"- **{skill['skill']}** (your level: {skill['level']*100:.0f}%)")

    if match["skills"]["partial"]:
        lines.append("")
        lines.append("### 🟡 Partial Match")
        for s in match["skills"]["partial"]:
            lines.append(f"- **{s['skill']}** (your level: {s['level']*100:.0f}%)")

    if match["skills"]["missing"]:
        lines.append("")
        lines.append("### ❌ Missing / Gap")
        for s in match["skills"]["missing"][:10]:
            lines.append(f"- {s}")
        if len(match["skills"]["missing"]) > 10:
            lines.append(f"- ... and {len(match['skills']['missing']) - 10} more")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## 📈 Experience Match ({match['experience']['score']*100:.0f}%)",
        f"",
        f"- {match['experience']['note']}",
        f"",
        f"## 📍 Location & Work Style ({match['location']['score']*100:.0f}%)",
        f"",
    ])

    for note in match["location"]["notes"]:
        lines.append(f"- {note}")

    lines.extend([
        f"",
        f"## 💰 Salary Match ({match['salary']['score']*100:.0f}%)",
        f"",
        f"- {match['salary']['note']}",
        f"",
        f"---",
        f"",
    ])

    # Context/Ethos section
    ctx_reasoning = match.get("context_reasoning", "")
    ctx_score = match.get("context_score", 0)
    ctx_reasoning_en = match.get("context_reasoning_en", "")
    ctx_reasoning_ja = match.get("context_reasoning_ja", "")
    lines.extend([
        f"",
        f"## 🧠 Context & Ethos Alignment ({ctx_score*100:.0f}%)",
        f"",
    ])
    if ctx_reasoning:
        # The reasoning may already contain "English\n\n**和訳:** Japanese"
        # Format as proper markdown paragraphs
        parts = ctx_reasoning.split("\n\n")
        for part in parts:
            part = part.strip()
            if part:
                # Each paragraph as-is (not bullet-wrapped, to allow full text)
                lines.append(part)
                lines.append("")
    elif not ctx_reasoning:
        lines.append("- No context analysis available")
        lines.append("")
    lines.extend([
        f"---",
        f"",
    ])

    # Job Summary section (bilingual)
    summary_en = match.get("summary_en", "")
    summary_ja = match.get("summary_ja", "")
    if summary_en or summary_ja:
        lines.extend([
            f"## 📋 求人概要 (Job Summary)",
            f"",
        ])
        if summary_en:
            lines.extend([
                f"### English",
                f"",
                summary_en,
                f"",
            ])
        if summary_ja:
            lines.extend([
                f"### 日本語",
                f"",
                summary_ja,
                f"",
            ])
        lines.extend([
            f"---",
            f"",
        ])

    # Related Documents section (links to CV and cover letter)
    related = []
    if cv_filename:
        cv_name = cv_filename.replace(".md", "")
        related.append(f"- **CV:** [[{cv_name}]]")
    if cl_filename:
        cl_name = cl_filename.replace(".md", "")
        related.append(f"- **Cover Letter:** [[{cl_name}]]")
    if related:
        lines.append(f"## 📎 Related Documents")
        lines.append(f"")
        lines.extend(related)
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

    lines.append(f"*Generated by Job Scraper Match Analyzer*")

    return "\n".join(lines)


def save_match_report(job: dict, match: dict, output_dir: str, cv_filename: str | None = None, cl_filename: str | None = None) -> str:
    """
    Save match report as Markdown file.
    Returns the file path.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    base = make_safe_name(job.get("company", "unknown"), job.get("title", "unknown"))
    filename = f"{base}.md"
    filepath = Path(output_dir) / filename

    report = generate_match_report(job, match, cv_filename=cv_filename, cl_filename=cl_filename)
    filepath.write_text(report, encoding="utf-8")

    return str(filepath)
