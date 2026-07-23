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
    # Note: only synonyms whose target resolves to a real skills.md entry
    # belong here — a target with no matching row silently scores 0 with no
    # error. tests/test_skill_sync.py enforces this; a removed alias below
    # was previously dead code (target never existed), not a scoring change.
    "js": "javascript",
    "javascript": "js",
    "ts": "typescript",
    "typescript": "ts",
    "py": "python",
    "python": "py",
    "scripting": "bash / shell",
    "shell scripting": "bash / shell",
    "shell": "bash / shell",
    "bash": "bash / shell",
    "react.js": "react",
    "reactjs": "react",
    "nextjs": "next.js",
    "node.js": "nodejs",
    "nodejs": "node.js",
    "docker / kubernetes": "docker / docker compose",
    "k8s": "docker / docker compose",
    "kubernetes": "docker / docker compose",
    "c#": "csharp",
    "csharp": "c#",
    "c++": "cpp",
    "cpp": "c++",
    "golang": "go",
    "go": "golang",
    # Additional common abbreviations
    "ci/cd": "continuous integration",
    "continuous integration": "ci/cd",
    "cv": "computer vision / vlm",
    "computer vision": "computer vision / vlm",
    "rest": "rest / websockets",
    "rest api": "rest / websockets",
    "api": "rest / websockets",
    "apis": "rest / websockets",
    "api integration": "rest / websockets",
    "websockets": "rest / websockets",
    "sql": "postgresql",
    "postgres": "postgresql",
    "llm": "local llm orchestration",
    "large language model": "local llm orchestration",
    "llm orchestration": "local llm orchestration",
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
    # Workflow / methodology synonyms
    "workflow": "workflow automation",
    "workflows": "workflow automation",
    "automation": "workflow automation",
    "workflow optimization": "workflow automation",
    "process automation": "workflow automation",
    "pipeline": "workflow automation",
    "n8n": "workflow automation",
    "zapier": "workflow automation",
    # Agentic / multi-agent phrasing — job posts split one competency into
    # many near-duplicate terms; route them all to the Multi-Agent Systems row.
    "agent workflows": "multi-agent systems",
    "agentic workflows": "multi-agent systems",
    "agentic systems": "multi-agent systems",
    "ai agents": "multi-agent systems",
    "autonomous agents": "multi-agent systems",
    "autonomous research agents": "multi-agent systems",
    "multi agent": "multi-agent systems",
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
    # Hyphenated keys: normalize_skill_name() converts "-" to " " before a
    # lookup, so a hyphenated key here would never match — use spaces.
    "low fidelity": "prototyping",
    "high fidelity": "prototyping",
    "cross functional": "cross-functional collaboration",
    "stakeholder communication": "cross-functional collaboration",
    "technical writing": "technical documentation",
    "documentation": "technical documentation",
    # Adobe tools — covered by equivalent experience (Affinity, GIMP, Krita, Procreate)
    "illustrator": "graphic design",
    "adobe illustrator": "graphic design",
    "indesign": "graphic design",
    "adobe indesign": "graphic design",
    "adobe creative suite": "graphic design",
    "adobe creative cloud": "graphic design",
    "creative suite": "graphic design",
    "affinity designer": "graphic design",
    "photoshop": "digital illustration",
    "adobe photoshop": "digital illustration",
    "gimp": "digital illustration",
    "krita": "digital illustration",
    "procreate": "digital illustration",
    # Engineering practice variants
    "refactoring": "code refactoring",
    "coding standards": "code standards",
    "code quality": "code standards",
    "code review": "code standards",
    "troubleshooting": "debugging",
    "problem diagnosis": "debugging",
    # AI-assisted / agentic coding tooling
    "claude code": "ai-assisted development",
    "agentic coding": "ai-assisted development",
    "ai coding": "ai-assisted development",
    "ai pair programming": "ai-assisted development",
    "copilot": "ai-assisted development",
    "database management": "data management",
    "data pipelines": "data management",
    "data pipeline": "data management",
    "data structuring": "data management",
    "data modeling": "data management",
    "data driven": "data-driven systems",
    # Game development variants (aspirational — partial credit via skills.md)
    "game dev": "game development",
    "gameplay programming": "gameplay systems",
    "gameplay": "gameplay systems",
    # Photography variants
    "photoshoot": "photography",
    "photoshoots": "photography",
    "photo shoot": "photography",
    "photo shoots": "photography",
    "raw editing": "raw photo editing",
    "photo editing": "raw photo editing",
    "darktable": "raw photo editing",
    "lightroom": "raw photo editing",
    "adobe lightroom": "raw photo editing",
    # Product building variants
    "product dev": "product development",
    "product building": "product development",
    # Web design variants
    "web designer": "web design",
    "website design": "web design",
    "landing page": "web design",
    "landing pages": "web design",
    "landing page design": "web design",
}


# Common job-extracted terms that are too generic/ambiguous to be treated as skills.
NON_SKILL_FILTER: set[str] = {
    "make", "less",
    "problem solving", "creative", "innovation", "innovative",
    "interpersonal", "communication", "teamwork", "leadership",
    "team leadership", "team building", "people leadership",
    "people management",
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


# "Design"/"Designer" alone is discipline-ambiguous — it covers physical/
# industrial design (gas pipe layout, automotive parts, mechanical CAD) just
# as much as the candidate's actual graphic/UI/product design work. Without
# word-boundary matching, this term partial-matches the candidate's own
# "Web Design"/"UI Design" skills (get_user_skill_level's substring path) and
# scored a Gas Designer posting 0.64 on skills alone. Only trust it when the
# SAME job also names a concrete digital-design tool/practice.
_AMBIGUOUS_DESIGN_TERMS = {"design", "designer", "design engineer", "cad", "cad design"}
_DIGITAL_DESIGN_SIGNALS = {
    "adobe", "photoshop", "illustrator", "affinity", "figma", "sketch",
    "indesign", "web design", "ui design", "ux design", "ui/ux", "ui", "ux",
    "front-end", "frontend", "front end", "html", "css", "javascript",
    "graphic design", "brand design", "visual design", "visual", "canva",
    "procreate", "after effects", "premiere", "framer", "webflow",
    "product design", "typography", "wireframe", "wireframing",
    "prototyping", "prototype", "branding", "layout", "portfolio",
}


def _has_digital_design_context(job_skills: list[str]) -> bool:
    """True if the job's skill list names a concrete digital-design tool or
    practice alongside a bare "design"/"designer" term — see
    _AMBIGUOUS_DESIGN_TERMS above for why that co-occurrence matters."""
    blob = " ".join(normalize_skill_name(s) for s in job_skills)
    return any(sig in blob for sig in _DIGITAL_DESIGN_SIGNALS)


# Roles whose "design" vocabulary is digital/creative by definition — a bare
# "Design" skill inside one of these disciplines is the candidate's actual
# strength, not a physical-design (gas/automotive/CAD) false friend.
_DIGITAL_ROLE_SET = {"product_designer", "creative_technologist", "technical_artist",
                     "web_developer", "camera_assistant"}
# One title keyword hit (2.0) or two skill/description hits (1.0 each) suffice.
_DIGITAL_ROLE_MIN_AFFINITY = 2.0


def _digital_role_affinity(job_title: str, job_skills: list[str],
                           job_description: str = "") -> float:
    """Total role-keyword affinity to digital/creative roles, summed across
    title + skill list + description (cv_generator.role_affinity, shared with
    CV template routing so the two paths can't drift). Replaces a title-only
    check that missed jobs whose evidence is spread thin — one
    creative_technologist keyword in the title is conclusive, but so are
    several product_designer keywords scattered across the skills and
    description with none individually in the title. Physical-design jobs
    (gas mains, automotive) hit none of these keywords, so they stay at 0
    and keep the untrusted-"design" demotion."""
    from cv_generator import role_affinity
    aff = role_affinity(job_title, job_skills, job_description)
    return sum(v for r, v in aff.items() if r in _DIGITAL_ROLE_SET)


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


# Skill-score shaping (see calculate_skill_match). `strength` saturates the
# absolute matched credit so that ~4-6 solid matches carry a score floor
# independent of how many skills the job listed — this is what stops a real
# match from collapsing to 0 under a long unmatched tail. The ceiling caps how
# far absolute strength alone can lift the score; a top score still needs
# breadth (high `coverage`).
_SKILL_SATURATION = 4.0
_SKILL_STRENGTH_CEILING = 0.6


def calculate_skill_match(job_skills: list[str], user_skills: dict, job_title: str = "",
                          job_description: str = "") -> dict:
    """
    Calculate skill match score with embedding fallback.
    Returns: {score, matched_skills, missing_skills, partial_skills}
    """
    if not job_skills:
        return {"score": 0.3, "matched": [], "missing": [], "partial": []}

    user_skill_list = _build_user_skill_embeddings(user_skills)
    has_design_context = (
        _has_digital_design_context(job_skills)
        or _digital_role_affinity(job_title, job_skills, job_description) >= _DIGITAL_ROLE_MIN_AFFINITY
    )

    matched = []
    partial = []
    missing = []
    total_weight = 0.0
    matched_weight = 0.0

    for job_skill in job_skills:
        # Skip non-skill terms (too generic/ambiguous)
        if _is_non_skill(job_skill):
            continue
        total_weight += 1.0

        # Bare "design"/"designer" with no accompanying digital-design signal
        # in this same job's skill list is discipline-ambiguous (see
        # _AMBIGUOUS_DESIGN_TERMS) — count it unmatched rather than let it
        # substring/embedding-match the candidate's own Web/UI design skills.
        if normalize_skill_name(job_skill) in _AMBIGUOUS_DESIGN_TERMS and not has_design_context:
            missing.append(job_skill)
            continue

        level = get_user_skill_level(user_skills, job_skill)

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

    # Two views of skill fit, combined so a long tail of unmatched niche/
    # duplicate terms can't zero out a candidate who genuinely covers the
    # core skills:
    #   coverage — weighted fraction of the job's skills the candidate holds.
    #     Honest breadth signal, but it sinks toward 0 when the LLM extracts
    #     many granular near-duplicate terms (denominator inflation), e.g.
    #     "Agent Workflows" + "Autonomous Research Agents" + "Multi-Agent
    #     Systems" as three separate rows for one competency.
    #   strength — absolute matched credit, saturating. Depends only on how
    #     much real match exists, NOT on the gap count, so it sets a floor a
    #     genuine match can't fall below. Zero matches -> matched_weight 0 ->
    #     strength 0, so this never invents a fit the candidate lacks (real
    #     gaps like "Distributed Compute" still lower coverage, as they should).
    coverage = matched_weight / total_weight if total_weight > 0 else 0.0
    strength = 1.0 - math.exp(-matched_weight / _SKILL_SATURATION)
    score = max(coverage, _SKILL_STRENGTH_CEILING * strength)

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
    # Hard facts first: smaller LLMs otherwise infer "based in Japan" from
    # scattered Japan references (remote hardware, past photography) even
    # though profile.md states the location explicitly.
    parts = [
        "--- KEY FACTS (authoritative) ---\n"
        "Current location: Edinburgh, Scotland, UK — settled resident since December 2025, UK work eligible.\n"
        "Do NOT frame this as an upcoming or future move, and never claim the candidate lives in, "
        "is near, or is relocating to the employer's location. The candidate's home is Edinburgh, full stop.\n"
        "Any mentions of Japan below refer to past work, photography subjects, or a "
        "remote compute machine — NOT the candidate's current location."
    ]
    # ethos.md gets a larger budget: at 2000 chars the model saw only the
    # local-AI mentions and never reached the deployment-agnostic /
    # "What I Do" sections, and reported a "local-first preference" mismatch
    # against cloud-heavy jobs.
    per_file_limit = {"ethos.md": 6500}
    for fname in persona_files:
        fpath = USER_PROFILE_DIR / fname
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"--- {fname} ---\n{content[:per_file_limit.get(fname, 2000)]}")
    _persona_cache = "\n\n".join(parts) if len(parts) > 1 else ""
    return _persona_cache


# The candidate is deployment-agnostic (cloud or local per constraint), but
# smaller/fallback models keep inventing a "local-first preference" and scoring
# cloud-heavy jobs as a values mismatch. Prompt instructions alone do not hold
# across the fallback provider chain, so violations are caught and scrubbed.
import re as _re_framing

_DEPLOY_FRAMING_RX = _re_framing.compile(
    r"local[-\s]?first|self[-\s]?hosted|ローカルファースト|セルフホスト", _re_framing.I
)


def _scrub_deployment_framing(text: str) -> str:
    """Drop sentences that frame the candidate as local-first / anti-cloud."""
    if not text or not _DEPLOY_FRAMING_RX.search(text):
        return text
    # Split on English and Japanese sentence ends, keeping the terminator.
    sentences = _re_framing.split(r"(?<=[.!?。])\s*", text)
    kept = [s for s in sentences if s and not _DEPLOY_FRAMING_RX.search(s)]
    return " ".join(kept).strip() or text


def _ollama_context_score(job_description: str, persona_summary: str,
                          brief: bool = False, _retries_left: int = 1) -> dict | None:
    """
    Ask the LLM to rate context/ethos alignment on a 0-100 scale.
    Returns {"score": float (0-1), "reasoning": str, ...} or None on failure.

    brief=True: English-only, 1-2 sentence reasoning, small token budget —
    for bulk scoring passes where only the score gates filtering. The long
    bilingual reasoning (brief=False) roughly 6-10x's the latency; reserve it
    for the few high-match jobs whose reports actually display it. The
    Japanese translation is added lazily at report time, not here.

    Reasoning that calls the candidate local-first is retried once, then
    scrubbed — see _scrub_deployment_framing.
    """
    if not job_description or not persona_summary:
        return None

    shared = f"""You are a career alignment analyst. Rate how well this job matches the candidate's personal philosophy, work style, and ethos.

## Candidate Profile
{persona_summary[:9000]}

## Job Description
{job_description[:5000]}

## Task
Score the alignment on 0-100 (0 = completely misaligned, 100 = perfect fit).
Consider: work philosophy, values, creative vs corporate culture, autonomy, tooling flexibility (picks cloud or local per constraint, bound to neither), multi-disciplinary creative-engineer fit.

Note: The candidate is deployment-agnostic. They run local models in personal research and standard enterprise cloud (AWS, hosted model APIs, managed services, third-party SaaS) in professional work, choosing per constraint — latency, cost, privacy, team toolchain — not per preference. This is portability, NOT a local-first bias. Do NOT describe the candidate as "local-first", do NOT treat a cloud or enterprise stack as a mismatch, and do NOT mention local-vs-cloud in the reasoning at all. Score on whether the candidate's core problem-solving ethos (reducing friction, automating pipelines, bridging design and engineering) aligns with the job's requirements."""

    # Style for both modes: plain, simple English. Short words, short
    # sentences, no jargon or filler. Say the one thing that drives the score.
    if brief:
        prompt = shared + """

Respond ONLY with JSON:
{"score": <number 0-100>, "reasoning_en": "<3-4 short, plain sentences>"}
Use simple words, short sentences. Say what fits, what does not, and the main reason for the score. No filler.
Plain prose only — NO markdown, NO bold, NO headers, NO bullet points, NO labels like "Fits:"/"Doesn't fit:". Just 3-4 flowing sentences.
BANNED: the reasoning must not contain "local-first", "local first", "self-hosted", "open-source preference", or any claim that cloud / enterprise / third-party tooling is a mismatch for this candidate. The candidate uses cloud and local equally.
"""
    else:
        prompt = shared + """

Respond ONLY with JSON:
{"score": <number 0-100>, "reasoning_en": "<3-4 short, plain sentences>", "reasoning_ja": "<短く平易な日本語で3〜4文>"}

Write plainly. Short words, short sentences, no jargon. Say what fits and what does not, and why — nothing more. Keep English and Japanese the same length and meaning.
Plain prose only — NO markdown, NO bold, NO headers, NO bullet points, NO labels like "Fits:"/"Doesn't fit:". Just 3-4 flowing sentences per language.
BANNED: neither language may contain "local-first" / "ローカルファースト", "self-hosted", "open-source preference", or any claim that cloud / enterprise / third-party tooling is a mismatch for this candidate. The candidate uses cloud and local equally.
"""

    try:
        from llm_client import call_llm as _call_llm
        content = _call_llm(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=(
                "You are a career alignment scoring engine. Output ONLY valid JSON. "
                "The candidate is deployment-agnostic: cloud and local are equally normal for them. "
                "Never call them local-first, never treat a cloud/enterprise stack as a values mismatch."
            ),
            temperature=0.1,
            max_tokens=300 if brief else 700,  # short reasoning → small budget → fast
        )

        import json, re
        matches = list(re.finditer(r'\{.*\}', content, re.DOTALL))
        for match in reversed(matches):
            try:
                data = json.loads(match.group(), strict=False)
                score = float(data.get("score", 50))
                reasoning_en = data.get("reasoning_en", data.get("reasoning", ""))
                reasoning_ja = data.get("reasoning_ja", "")
                # Combine: English + Japanese (for display in MD)
                if reasoning_ja:
                    reasoning = f"{reasoning_en}\n\n**和訳:** {reasoning_ja}"
                else:
                    reasoning = reasoning_en
                score = max(0, min(100, score)) / 100.0

                if _DEPLOY_FRAMING_RX.search(f"{reasoning_en} {reasoning_ja}"):
                    if _retries_left > 0:
                        retried = _ollama_context_score(
                            job_description, persona_summary, brief,
                            _retries_left=_retries_left - 1,
                        )
                        if retried is not None:
                            return retried
                    reasoning_en = _scrub_deployment_framing(reasoning_en)
                    reasoning_ja = _scrub_deployment_framing(reasoning_ja)
                    reasoning = (f"{reasoning_en}\n\n**和訳:** {reasoning_ja}"
                                 if reasoning_ja else reasoning_en)

                return {"score": round(score, 2), "reasoning": reasoning, "reasoning_en": reasoning_en, "reasoning_ja": reasoning_ja}
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
        return None
    except Exception:
        return None


def translate_to_ja(text_en: str) -> str:
    """Translate a short plain-English note to plain Japanese.

    Generic — used for both context-alignment reasoning and job summaries.
    Bulk passes generate English only (fast); this adds Japanese lazily, for
    just the few high-match jobs whose reports actually display it, so the
    bulk pass itself stays fast. Returns "" on failure (caller keeps
    English-only)."""
    if not text_en:
        return ""
    try:
        from llm_client import call_llm as _call_llm
        out = _call_llm(
            messages=[{"role": "user", "content":
                       "Translate to plain, simple Japanese. Short words, short "
                       "sentences, same meaning. Write it as ONE flowing paragraph — "
                       "no line breaks between sentences, no bullet points, no markdown. "
                       f"Output ONLY the Japanese, no preamble:\n\n{text_en}"}],
            system_prompt="You are a precise EN→JA translator. Output only the translation.",
            temperature=0.1,
            max_tokens=400,
        )
        return (out or "").strip()
    except Exception:
        return ""


def _ollama_job_summary(job_description: str, en_only: bool = False) -> dict | None:
    """Generate a summary of a job description.

    en_only=True: English only, for the bulk pass over every >=0.50 match —
    keeps the loop fast. Japanese is added lazily via translate_to_ja() for
    just the high-match jobs whose reports display it (see
    llm_context_backfill.py). en_only=False (default): original bilingual
    single-call behavior, used by the on-demand/interactive analyze_match
    path where per-job cost isn't in a tight bulk loop."""
    if not job_description or len(job_description) < 50:
        return None

    if en_only:
        prompt = f"""You are a job description summarizer. Summarize the following job description in 3-4 sentences.

Cover: role, main duties, required skills, and what makes this role distinctive. Use plain, simple words and short sentences. No markdown, no bullet points, no jargon.

Respond ONLY with JSON. The value MUST be a plain string (flowing prose,
3-4 short sentences) — NEVER a nested object, list, or markdown headings/bold:
{{"summary_en": "<3-4 short, plain sentences in English>"}}

## Job Description
{job_description[:5000]}
"""
    else:
        prompt = f"""You are a job description summarizer. Summarize the following job description in 3-4 sentences.

Cover: role, main duties, required skills, and what makes this role distinctive. Use plain, simple words and short sentences. No markdown, no bullet points, no jargon.

Respond ONLY with JSON. Both values MUST be plain strings (flowing prose,
3-4 short sentences) — NEVER nested objects, lists, or markdown headings/bold:
{{"summary_en": "<3-4 short, plain sentences in English>", "summary_ja": "<短く平易な日本語で3〜4文>"}}

## Job Description
{job_description[:5000]}
"""

    try:
        # Route through llm_client like every other LLM call (provider chain:
        # ANALYSIS_PROVIDER with FALLBACK_PROVIDER on transient errors) —
        # previously this hit Ollama directly and silently returned None
        # whenever Ollama wasn't running.
        from llm_client import call_llm as _call_llm
        content = _call_llm(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You are a job description summarizer. Output ONLY valid JSON.",
            temperature=0.2,
            max_tokens=280 if en_only else 450,
        )

        import json
        matches = list(re.finditer(r'\{.*\}', content, re.DOTALL))
        for match in reversed(matches):
            try:
                data = json.loads(match.group(), strict=False)

                def _flatten(v):
                    # LLMs sometimes nest the summary into {"role": ..., ...}
                    # despite the prompt — salvage by joining the string leaves
                    if isinstance(v, str):
                        return v.strip()
                    if isinstance(v, dict):
                        return " ".join(p for p in (_flatten(x) for x in v.values()) if p)
                    if isinstance(v, list):
                        return " ".join(p for p in (_flatten(x) for x in v) if p)
                    return ""

                summary_en = _flatten(data.get("summary_en", ""))
                summary_ja = _flatten(data.get("summary_ja", ""))
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

        # TF-IDF measures word overlap, not meaning: "Gas Designer" shares
        # "design / technical / drawings / project" with the persona and
        # saturates to 1.0 despite being a different field. Cap the fallback
        # so surface overlap can register a positive signal but never claim a
        # perfect fit — only the LLM read (context_source="llm") is trusted
        # to award a high context score. Raise the cap by enabling
        # --llm-context (option A).
        TFIDF_SCORE_CAP = 0.6
        normalized = min(normalized, TFIDF_SCORE_CAP)

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


def calculate_title_relevance(
    title: str, context_score: float | None = None, context_source: str | None = None
) -> float:
    """
    Check if the job title is relevant to target roles.
    Returns 1.0 if relevant, 0.0-0.1 if completely irrelevant.

    context_score/context_source let a confident LLM read of the full
    description (which understands e.g. "Specialist Technician" at an art
    school is relevant even though "technician" isn't in target_words)
    rescue titles the keyword whitelist doesn't recognize. The whitelist is
    a blunt safety net for when there's no LLM signal to rely on — it
    shouldn't override a full-context read that disagrees with it.
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
        return 0.0  # Hard exclusion (nurse, driver, etc.) always applies

    if not has_target:
        # No keyword hit — let a confident LLM context read rescue it
        # before falling back to the harsh 0.1 penalty.
        if context_source == "llm" and context_score is not None and context_score >= 0.6:
            return 1.0
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
    skill_match = calculate_skill_match(job_skills, user_skills, job.get("title", ""), job_description)
    exp_match = calculate_experience_match(job_level, user_exp)
    loc_match = calculate_location_match(job_location, job_work_style, user_exp)
    sal_match = calculate_salary_match(job_salary, config.get("min_salary_gbp", 30000))
    # Reuse pre-existing LLM context score instead of re-scoring: LLM scores
    # are expensive and must survive plain --reanalyze runs. Accepts the
    # canonical flag (context_source == "llm") plus both legacy schemas
    # (llm_context_tagged from run.py, match["context"] dict from
    # bulk_analyze_cloud.py).
    old_match = job.get("match") or {}
    legacy_ctx = old_match.get("context")
    ctx_source = "llm"
    if old_match.get("context_source") == "llm" or old_match.get("llm_context_tagged"):
        ctx_match = {
            "score": old_match.get("context_score", 0),
            "reasoning": old_match.get("context_reasoning", ""),
            "reasoning_en": old_match.get("context_reasoning_en", ""),
            "reasoning_ja": old_match.get("context_reasoning_ja", ""),
            "top_terms": old_match.get("context_top_terms", []),
        }
    elif isinstance(legacy_ctx, dict) and "score" in legacy_ctx:
        ctx_match = legacy_ctx
    else:
        # Use LLM for context scoring (or TF-IDF fallback)
        persona = _load_persona_summary()
        llm_ctx = None
        if persona and job_description:
            llm_ctx = _ollama_context_score(job_description, persona)
        if llm_ctx:
            ctx_match = llm_ctx
        else:
            ctx_match = calculate_context_match(job_description)  # TF-IDF fallback if LLM fails
            ctx_source = "tfidf"

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
    relevance = calculate_title_relevance(
        job.get("title", ""), context_score=ctx_match.get("score"), context_source=ctx_source
    )
    composite = composite * relevance

    # Determine tier. "Strong Match" asserts confirmed relevance, so it
    # requires a semantic (LLM) context read — a TF-IDF-only score is
    # word-overlap and can't tell "UI Designer" from "Gas Designer". Without
    # that confirmation a job is capped at "Good Match" no matter how high the
    # keyword-driven composite climbs. Enabling --llm-context (option A) lets
    # genuinely strong jobs reach the top tier again.
    if relevance < 0.5:
        tier = "🔴 Completely Irrelevant"
    elif composite >= 0.8 and ctx_source == "llm":
        tier = "🟢 Strong Match"
    elif composite >= 0.8:
        tier = "🟡 Good Match (未検証: LLM文脈スコア無し)"
    elif composite >= 0.6:
        tier = "🟡 Good Match"
    elif composite >= 0.4:
        tier = "🟠 Partial Match"
    else:
        tier = "🔴 Weak Match"

    # A) Bilingual job summary via LLM for 50%+ matches (skippable for batch mode).
    # Preserve an existing summary — like context scores, summaries are
    # expensive LLM output and must survive --reanalyze runs.
    summary_en = old_match.get("summary_en", "")
    summary_ja = old_match.get("summary_ja", "")
    if not summary_en and not summary_ja:
        if not skip_summary and composite >= 0.50 and job_description and len(job_description) >= 50:
            summary = _ollama_job_summary(job_description)
            if summary:
                summary_en = summary.get("summary_en", "")
                summary_ja = summary.get("summary_ja", "")

    # Per-role keyword affinity (title×2 + skills + description hits) — stored
    # so reports/debugging can see WHY a mixed-signal job was read as design
    # vs data vs creative-tech, and which profile it leans toward.
    from cv_generator import role_affinity as _role_affinity_fn
    role_aff = _role_affinity_fn(job.get("title", ""), job_skills, job_description)

    return {
        "composite_score": round(composite, 2),
        "tier": tier,
        "description_missing": description_missing,
        "skills": skill_match,
        "experience": exp_match,
        "location": loc_match,
        "salary": sal_match,
        "context_score": ctx_match["score"],
        "context_reasoning": ctx_match.get("reasoning", ""),
        "context_reasoning_en": ctx_match.get("reasoning_en", ""),
        "context_reasoning_ja": ctx_match.get("reasoning_ja", ""),
        "context_top_terms": ctx_match.get("top_terms", []),
        "context_source": ctx_source,
        "title_relevance": relevance,
        "weights": weights,
        "summary_en": summary_en,
        "summary_ja": summary_ja,
        "role_affinity": role_aff,
        "detected_role": max(role_aff, key=role_aff.get) if role_aff else "general",
    }


# --- Report Generation ---

# Job category taxonomy for Dataview filtering (Match Score List etc.).
# TITLE-ONLY on purpose — descriptions are full of trap words (see the
# experience-level classifier). A job can carry multiple categories.
_JOB_CATEGORY_KEYWORDS = {
    "design": ["designer", "design", "ui", "ux", "figma", "typograph"],
    "engineering": ["engineer", "developer", "programmer", "software",
                    "full stack", "fullstack", "devops", "sre", "technologist",
                    "technical", "data", "ai", "ml", "cloud"],
    "art": ["artist", "art", "illustrat", "3d", "animation", "animator",
            "vfx", "visual effects", "concept"],
    "marketing": ["marketing", "seo", "growth", "social media", "content",
                  "copywriter", "campaign"],
    "branding": ["brand", "branding"],
}


def classify_job_categories(title: str) -> list[str]:
    """Classify a job into categories (design/engineering/art/marketing/branding)
    from the TITLE only, word-boundary matched. Returns [] when nothing hits."""
    title_lower = (title or "").lower()
    cats = []
    for cat, keywords in _JOB_CATEGORY_KEYWORDS.items():
        for kw in keywords:
            # Trailing wildcard allowed (e.g. "illustrat" → illustrator/illustration)
            if re.search(r"(?<![a-z0-9])" + re.escape(kw), title_lower):
                cats.append(cat)
                break
    return cats


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
    # Collection route (how the job entered the queue), not the job board it came
    # from — `source` is the site, `route` is url_list / watched / scraper.
    route = job.get("route", "")
    route_yaml = f'\nroute: "{route}"' if route else ""
    scraped_at = job.get("scraped_at", "")
    saved_at = scraped_at[:10] if scraped_at else datetime.now().strftime("%Y-%m-%d")
    cv_link = f'\ncv: "[[{cv_filename.replace(".md", "")}]]"' if cv_filename else ""
    cl_link = f'\ncover_letter: "[[{cl_filename.replace(".md", "")}]]"' if cl_filename else ""
    categories = classify_job_categories(title)
    categories_yaml = "[" + ", ".join(categories) + "]" if categories else "[]"

    frontmatter = f"""---
match_score: {score}
match_score_pct: {score_pct}
tier: "{_tier_short(match['tier'])}"
company: "{company}"
title: "{title}"
categories: {categories_yaml}
location: "{location}"
source: "{source}"
type: "{jtype}"{route_yaml}
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

    dup_urls = job.get("duplicate_urls") or []
    dup_lines = [f"**Also posted at:** {u}" for u in dup_urls]

    lines = [
        frontmatter,
        f"",
        f"# Match Report: {title}",
        f"**Company:** {company}  |  **Location:** {location}",
        f"**URL:** {url}",
        *dup_lines,
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

    # Job Summary section (bilingual) — coerce to str: legacy data may hold
    # non-string values from LLM JSON quirks, and "\n".join() crashes on those
    summary_en = match.get("summary_en", "") or ""
    summary_ja = match.get("summary_ja", "") or ""
    if not isinstance(summary_en, str):
        summary_en = ""
    if not isinstance(summary_ja, str):
        summary_ja = ""
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
