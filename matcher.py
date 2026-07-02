"""
Match Analyzer
==============
Compares user profile (skills, experience, preferences) with job analysis
to calculate a match score and generate a detailed match report.
"""

import math
import re
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
ABOUT_FILE = USER_PROFILE_DIR / "00-about.md"


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
    Extract key experience facts from 00-about.md.
    """
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

    # Rough extraction from timeline
    if "2020" in content and "2024" in content:
        exp["years_python"] = 4
        exp["years_automation"] = 4
        exp["years_linux"] = 4

    if "2017" in content and "2019" in content:
        exp["years_creative"] = 2

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
}


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

    # Partial match (substring)
    for category, skills in user_skills.items():
        for skill in skills:
            user_norm = normalize_skill_name(skill["name"])
            if normalized in user_norm or user_norm in normalized:
                return LEVEL_WEIGHTS.get(skill["level"], 0.3) * 0.7

    # Synonym / abbreviation check
    if normalized in SKILL_SYNONYMS:
        synonym = SKILL_SYNONYMS[normalized]
        for category, skills in user_skills.items():
            for skill in skills:
                if normalize_skill_name(skill["name"]) == normalize_skill_name(synonym):
                    return LEVEL_WEIGHTS.get(skill["level"], 0.3)

    return 0.0


def _build_user_skill_embeddings(user_skills: dict):
    """Pre-build embeddings for all user skills. Returns list of (normalized_name, name, level)."""
    all_skills = []
    for category, skills in user_skills.items():
        for skill in skills:
            all_skills.append((normalize_skill_name(skill["name"]), skill["name"], skill["level"]))
    return all_skills


def _skill_name_embedding_similarity(job_skill: str, user_skill_list: list) -> float:
    """Return max embedding similarity between job_skill and any user skill."""
    if not SKLEARN_AVAILABLE or not user_skill_list:
        return 0.0
    try:
        user_names = [s[0] for s in user_skill_list]
        all_names = [normalize_skill_name(job_skill)] + user_names
        # Don't use stop_words - removes short abbreviations like "ml", "ai", "py"
        model = TfidfVectorizer(ngram_range=(1, 2), stop_words=None)
        vecs = model.fit_transform(all_names)
        sims = cosine_similarity(vecs[0:1], vecs[1:])
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
        "entry_level": 1,
        "mid_senior": 3,
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
    # Total experience gives more flexibility
    total_years = sum(
        v for k, v in user_exp.items()
        if k.startswith("years_") and isinstance(v, (int, float))
    )
    # Use whichever signals more experience
    user_total = max(user_years, total_years) or user_years

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
    if not job_loc or job_loc == "remote":
        score = 0.9  # Remote is excellent
        notes.append("✅ Fully remote")
        remote_flag = True
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


# --- Main Analysis ---

DEFAULT_WEIGHTS = {
    "skills": 0.40,
    "experience": 0.25,
    "location": 0.20,
    "salary": 0.15,
}


def analyze_match(job: dict, config: dict, weights: dict | None = None) -> dict:
    """
    Run all match analyses and return combined result.
    Pass custom weights via config['weights'] or weights parameter.
    """
    user_skills = load_user_skills()
    user_exp = load_user_experience()

    analysis = job.get("analysis", {})
    job_skills = analysis.get("skills", [])
    job_level = analysis.get("experience_level", "unknown")
    job_work_style = analysis.get("work_style", "unknown")
    job_salary = analysis.get("salary", {})
    job_location = job.get("location", "")

    # Individual scores
    skill_match = calculate_skill_match(job_skills, user_skills)
    exp_match = calculate_experience_match(job_level, user_exp)
    loc_match = calculate_location_match(job_location, job_work_style, user_exp)
    sal_match = calculate_salary_match(job_salary, config.get("min_salary_gbp", 30000))

    # Weighted composite — accept custom weights from config or parameter
    w = weights or config.get("weights", DEFAULT_WEIGHTS)
    weights = {
        "skills": w.get("skills", 0.40),
        "experience": w.get("experience", 0.25),
        "location": w.get("location", 0.20),
        "salary": w.get("salary", 0.15),
    }

    composite = (
        skill_match["score"] * weights["skills"]
        + exp_match["score"] * weights["experience"]
        + loc_match["score"] * weights["location"]
        + sal_match["score"] * weights["salary"]
    )

    # Determine tier
    if composite >= 0.8:
        tier = "🟢 Strong Match"
    elif composite >= 0.6:
        tier = "🟡 Good Match"
    elif composite >= 0.4:
        tier = "🟠 Partial Match"
    else:
        tier = "🔴 Weak Match"

    return {
        "composite_score": round(composite, 2),
        "tier": tier,
        "skills": skill_match,
        "experience": exp_match,
        "location": loc_match,
        "salary": sal_match,
        "weights": weights,
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
    frontmatter = f"""---
match_score: {score}
match_score_pct: {score_pct}
tier: "{_tier_short(match['tier'])}"
company: "{company}"
title: "{title}"
location: "{location}"
skills_score: {int(match['skills']['score'] * 100)}
experience_score: {int(match['experience']['score'] * 100)}
location_score: {int(match['location']['score'] * 100)}
salary_score: {int(match['salary']['score'] * 100)}
url: "{url}"
---"""

    lines = [
        frontmatter,
        f"",
        f"# Match Report: {title}",
        f"**Company:** {company}  |  **Location:** {location}",
        f"**URL:** {url}",
        f"",
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
    ]:
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

    # Related Documents section (links to CV and cover letter)
    related = []
    if cv_filename:
        related.append(f"- **CV:** [{cv_filename}](../00_cvs/{cv_filename})")
    if cl_filename:
        related.append(f"- **Cover Letter:** [{cl_filename}](../00_cover-letters/{cl_filename})")
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
