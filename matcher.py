"""
Match Analyzer
==============
Compares user profile (skills, experience, preferences) with job analysis
to calculate a match score and generate a detailed match report.
"""

import math
import threading
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
PORTFOLIO_DIR = USER_PROFILE_DIR / "01-portfolio" / "projects"

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
        # The Notes column is captured too: it names the concrete tools and
        # evidence ("GitHub Actions workflow automation", "Claude Code") that a
        # bare skill name hides, and _llm_skill_coverage needs it to judge a
        # requirement like "Github" or "Claude" that no row is titled after.
        row_match = re.match(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(\w+)\s*\|(.*)$", line)
        if row_match and current_category:
            skill_name = row_match.group(1).strip()
            level = row_match.group(2).strip().lower()
            if level == "level":  # Skip header row
                continue
            notes = row_match.group(3).strip().strip("|").strip()
            skills[current_category].append(
                {"name": skill_name, "level": level, "notes": notes})

    return skills


# Which words in a timeline label name which skill. A label can name several
# ("Python/Linux/Automation"), so each is matched against the label's own words.
_TIMELINE_SKILL_WORDS = {
    "years_python": ("python",),
    "years_linux": ("linux",),
    "years_automation": ("automation",),
    "years_creative": ("digital art", "3d", "photography", "design"),
    "years_web": ("web dev", "web development"),
    "years_ai": ("ai/ml", "ai / ml", "machine learning"),
}

# "2019-present", "2019 – present", "2019 to present", and closed "2019-2023".
_TIMELINE_SPAN = re.compile(
    r"(?P<start>(?:19|20)\d{2})\s*(?:[-–—]|to)\s*(?P<end>present|(?:19|20)\d{2})",
    re.IGNORECASE,
)

# "roughly 5 years effective". A span says when something started, not that it
# ran without a break, and this practice was intermittent — Python began in 2019
# and amounts to about 5 years, not 8. Where a line states the effective figure
# it wins outright, because the span cannot know about the gaps.
_TIMELINE_EFFECTIVE = re.compile(
    r"(?:roughly|about|approximately|around|~)?\s*(?P<years>\d{1,2})\s*years?\s+effective",
    re.IGNORECASE,
)

# The document's own qualification of its own spans: "roughly 4 years of paid
# work between Jul 2019 and Jul 2023".
_PAID_WORK = re.compile(
    r"(?:roughly|about|approximately|around|~)?\s*(?P<years>\d{1,2})\s*years?\s+of\s+paid\s+work",
    re.IGNORECASE,
)


def load_user_experience() -> dict[str, Any]:
    """Experience facts, read from timeline.md's explicit list.

    It used to read about.md, keyed on the literal string "Feral", inferring
    Python/Linux/automation years from a creative project's date range — its own
    comment ended in a question mark. Rewording a heading zeroed it: about.md's
    `### "Feral" — Narrative World Development (2023 – Present)` became
    `### TAIFUNOME — Independent Studio (2023 – Present)` with Feral demoted to
    a bullet, and since the regex's `.` does not cross newlines, nothing
    matched. years_python, years_linux and years_automation all became 0 and
    user_estimated_years halved from 4 to 2, silently, on a prose edit.

    timeline.md states the same facts outright under "Skills Acquisition
    Timeline" and always did. Reading that is both accurate and robust: the
    spans are labelled, so a reworded sentence elsewhere cannot silently zero
    them.

    Two different numbers come out of it, and conflating them is what would
    overstate the CV:

    - `years_*` are calendar spans — how long this person has been doing the
      thing at all. Python since 2019 is 8.
    - `years_professional` is what an employer means by "N+ years experience".
      timeline.md qualifies its own span: "worked in stretches rather than
      continuously — roughly 4 years of paid work between Jul 2019 and Jul
      2023". When the profile says that, it is the honest answer and it is what
      calculate_experience_match scores against.
    """
    import datetime
    current_year = datetime.datetime.now().year

    exp: dict[str, Any] = {
        "years_python": 0,
        "years_linux": 0,
        "years_creative": 0,
        "years_automation": 0,
        "years_professional": 0,
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

    timeline = USER_PROFILE_DIR / "timeline.md"
    if not timeline.exists():
        return exp
    content = timeline.read_text(encoding="utf-8")

    section = re.search(
        r"^##\s*Skills Acquisition Timeline\s*$(.*?)(?=^##\s|\Z)",
        content, re.M | re.S,
    )
    if section:
        for line in section.group(1).splitlines():
            label = re.match(r"\s*-\s*\*\*(?P<label>[^*]+)\*\*", line)
            if not label:
                continue
            stated = _TIMELINE_EFFECTIVE.search(line)
            if stated:
                years = int(stated.group("years"))
            elif "intermittent" in line.lower():
                # The line has declared its own span unreliable and given no
                # figure to replace it, so there is no honest number here.
                # Falling through to the span would do exactly what the word
                # warns against: "Photography: 2020-present, intermittent" read
                # as a span claims 7 years and, through max(), was overriding a
                # stated 3 for the same skill group.
                continue
            else:
                span = _TIMELINE_SPAN.search(line)
                if not span:
                    continue
                end_raw = span.group("end").lower()
                end = current_year if end_raw == "present" else int(end_raw)
                years = max(1, end - int(span.group("start")) + 1)
            words = label.group("label").lower()
            for key, needles in _TIMELINE_SKILL_WORDS.items():
                if any(n in words for n in needles):
                    exp[key] = max(exp.get(key, 0), years)

    paid = _PAID_WORK.search(content)
    if paid:
        exp["years_professional"] = int(paid.group("years"))

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
    "git": "git / github",
    "github": "git / github",
    "gitlab": "git / github",
    "version control": "git / github",
    "pull requests": "git / github",
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
    "genai": "generative ai",
    "gen ai": "generative ai",
    "diffusion models": "generative ai",
    "comfyui": "generative ai",
    "stable diffusion": "generative ai",
    "model orchestration": "local llm orchestration",
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
    # Brand/identity synonyms — map job description variants to the
    # brand identity / logo design / storytelling rows added for the
    # graphic_designer role split (TAIFUNOME, My Personal Identity Mark,
    # Feral Bestiary are the evidence backing these).
    "brand": "brand identity",
    "branding": "brand identity",
    "brand design": "brand identity",
    "brand strategy": "brand identity",
    "visual identity": "brand identity",
    "identity design": "brand identity",
    "logo": "logo design",
    "logo designer": "logo design",
    "wordmark": "logo design",
    "storytelling": "storytelling / narrative design",
    "brand storytelling": "storytelling / narrative design",
    "narrative design": "storytelling / narrative design",
    "narrative": "storytelling / narrative design",
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
    "responsive design": "web design",
    "frontend": "web design",
    "front end": "web design",
    "frontend development": "web design",
    "frontend architecture": "web design",
    "component based architecture": "design systems",
    "component driven development": "design systems",
    # Retargeted 2026-09-05 when skills.md split "Node.js / Express" in two:
    # Express is one 139-line internal API, Node.js is the plugin runtime and
    # the tooling. A posting asking for "backend development" is asking about
    # the latter, and pointing these at the row that no longer exists would
    # have scored every such posting 0 in silence.
    "backend services": "node.js",
    "backend development": "node.js",
    "agentic frameworks": "multi-agent systems",
    "data orchestration": "workflow automation",
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
    # Qualities/outcomes a posting lists as if they were skills — scoring them
    # only inflates the denominator (user call, 2026-07-24).
    "usability", "accessibility", "component libraries", "component library",
    "cost efficiency", "storybook", "performance optimization",
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
#
# web_developer was removed 2026-08-25. Its keyword list is shared with CV
# routing and mixes genuine front-end terms with "software engineer", "software
# developer", "backend engineer", "python developer" — and a title hit counts
# double, so ANY posting titled "Software Engineer" reached this threshold on
# its title alone and unlocked a bare "Design" requirement. Lloyds Banking
# Group's insider-risk engineering role did exactly that: skills 0.66, of which
# the matched terms were Agile, Design, Git, Kanban, Kubernetes, React, Scrum
# while the two that actually describe the job, Azure and Java, were the
# misses. Demoting "Design" there takes it to 0.56.
#
# Measured by scoring the whole database both ways: 79 postings change, every
# one of them downward, by a median 0.16 and up to 0.48. That matters more
# than it would have, because the 2026-08-24 reweighting moved
# skills from 0.20 to 0.45 of the composite — a reproducible error is still an
# error, and it now carries more than twice the leverage.
#
# The cost is a handful of .NET/PHP "Web Developer" postings losing the unlock.
# That is the right trade: their skill lists name no HTML, CSS, JavaScript,
# Figma or UI/UX at all, so "design" in them means software design. A web job
# whose design work is real names one of those, and _has_digital_design_context
# catches it directly without going through role affinity.
_DIGITAL_ROLE_SET = {"product_designer", "graphic_designer", "creative_technologist",
                     "technical_artist", "camera_assistant"}
# One title keyword hit (2.0) or two skill/description hits (1.0 each) suffice.
# NOT raised above 2.0: measured on the shipped keyword lists, "Visual
# Designer", "Interaction Designer", "Motion Designer", "Digital Designer",
# "Midweight Designer", "Technical Artist" and "Artworker" all score EXACTLY
# 2.0 from their titles, so any higher bar would drop real design disciplines.
# The fix for over-firing belongs in the role set above, not in this number.
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


def _singularize(name: str) -> str:
    """Best-effort singular of the LAST word ("component libraries" ->
    "component library"). Job posts name skills in the plural while skills.md and
    SKILL_SYNONYMS are singular, so the plural silently missed.

    Safe by construction: the result is only ever used as a LOOKUP KEY. A bogus
    stem ("aws" -> "aw", "css" -> "cs") matches no entry and changes nothing, so
    this can never invent a skill the candidate lacks.
    """
    words = name.split()
    if not words:
        return name
    last = words[-1]
    if len(last) > 3 and last.endswith("ies"):
        last = last[:-3] + "y"
    elif len(last) > 4 and last.endswith(("ches", "shes", "sses", "xes")):
        last = last[:-2]
    elif len(last) > 3 and last.endswith("s") and not last.endswith(("ss", "us", "is")):
        last = last[:-1]
    else:
        return name
    return " ".join(words[:-1] + [last])


def get_user_skill_level(user_skills: dict, skill_name: str) -> float:
    """Find user's proficiency level for a skill (0.0-1.0)."""
    normalized = normalize_skill_name(skill_name)
    # Try the plural-stripped form too (see _singularize) — lookup key only.
    singular = _singularize(normalized)
    candidates = [normalized] if singular == normalized else [normalized, singular]

    for cand in candidates:
        for category, skills in user_skills.items():
            for skill in skills:
                if normalize_skill_name(skill["name"]) == cand:
                    return LEVEL_WEIGHTS.get(skill["level"], 0.3)

    # Synonym / abbreviation check
    normalized = next((c for c in candidates if c in SKILL_SYNONYMS), normalized)
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
# Markers of a scrape that captured page scaffolding instead of the posting.
# Matched against the leading slice only: a real description may legitimately
# mention "JavaScript", but it does not OPEN with a script tag or a JWT.
_JUNK_DESC_MARKERS = (
    "window.addeventlistener", "document.createelement", "var tokendata",
    "<script", "settimeout(", "function(e)", "eyjhbgci", "gtag(", "datalayer.push",
)
_JUNK_DESC_SCAN = 800


def is_junk_description(text: str) -> bool:
    """True when a description is page machinery (tracker JS, JWT blobs) rather
    than the job posting. Such text must be treated as a MISSING description,
    not scored as prose — see the description_missing branch in analyze_match."""
    head = (text or "")[:_JUNK_DESC_SCAN].lower()
    return any(m in head for m in _JUNK_DESC_MARKERS)


_SKILL_SATURATION = 4.0
_SKILL_STRENGTH_CEILING = 0.6
# Floor on the coverage denominator: a job that named fewer than this many real
# requirements has not said enough for "fraction covered" to mean anything, so
# it is scored as if it had asked for this many. Set to the saturation point so
# the two views agree on what "enough requirements" is.
_SKILL_MIN_REQS = 4.0


# Where a posting stops stating requirements and starts listing wishes. Matched
# against the description, so the phrasing is the employer's, not ours.
_PREFERRED_SECTION = re.compile(
    r"what will set you apart|nice[\s-]?to[\s-]?have|desirable|preferred qualification"
    r"|bonus points|advantageous|would be a plus|it'?s a plus|not essential"
    r"|even better if|you might also",
    re.IGNORECASE,
)

# "Programming fluency in at least one language (Python, C++, JavaScript)" is ONE
# requirement, and the extractor returns it as three.
_ANY_ONE_OF = re.compile(
    r"at least one|one or more|any of|either|one of the following|or similar|such as",
    re.IGNORECASE,
)


def _locate(term: str, haystack_lower: str) -> list[int]:
    """Every word-boundary position of a skill term in a lowered description.

    Falls back to the term's longest word when the whole phrase is absent: the
    LLM extractor expands what it reads ("Unreal" comes back as "Unreal
    Engine"), and a term that cannot be located cannot be placed in a section.
    """
    for probe in (term, max(term.split(), key=len, default="") if " " in term else ""):
        if not probe or len(probe) < 3:
            continue
        hits = [m.start() for m in re.finditer(
            r"(?<![a-z0-9])" + re.escape(probe.lower()) + r"(?![a-z0-9])", haystack_lower)]
        if hits:
            return hits
    return []


def _unrequired_skills(job_skills: list[str], job_description: str,
                       user_skills: dict) -> set[str]:
    """Skills the posting NAMES but does not REQUIRE, so failing to hold one is
    not a gap in the candidate.

    The extractor returns one flat list, and it is drawn to concrete tool names
    — which is exactly where a posting's optional section lives. Moth's Creative
    Technologist role asks for "programming fluency in at least one language
    (Python, C++, JavaScript/TypeScript)", generative-AI familiarity and a
    portfolio; the six skills extracted from it were Arduino, Blender, C++,
    Python, Unity and Unreal Engine, five of which come from "What will set you
    apart" or from the unchosen half of that one-language list. Scored as
    requirements, a candidate who satisfies the stated requirement outright
    reads as holding one skill in six.

    Two things are recognised, both from the posting's own words:

      - anything whose only mention falls after a "nice to have" heading
      - the siblings of an "at least one of X, Y, Z" list, once one of them is
        held. Only DIRECT holdings count as satisfying the list, not the
        embedding or LLM rescues, so this can never manufacture a match.

    Being unrequired does not remove a skill's credit — holding a nice-to-have
    still counts for the candidate. It only stops the absence counting against
    them.
    """
    text = job_description or ""
    if not text:
        return set()
    lower = text.lower()
    unrequired: set[str] = set()

    heading = _PREFERRED_SECTION.search(text)
    cut = heading.start() if heading else None

    located = {s: _locate(s, lower) for s in job_skills}

    if cut is not None:
        for skill, hits in located.items():
            if hits and all(h >= cut for h in hits):
                unrequired.add(skill)

    # Sentence-level: an "any one of" cue and the skills named beside it.
    for sentence in re.split(r"(?<=[.!?\n])", text):
        if not _ANY_ONE_OF.search(sentence):
            continue
        s_lower = sentence.lower()
        here = [s for s in job_skills if _locate(s, s_lower)]
        if len(here) < 2:
            continue
        if any(get_user_skill_level(user_skills, s) >= 0.6 for s in here):
            unrequired.update(s for s in here
                              if get_user_skill_level(user_skills, s) < 0.6)

    return unrequired


def calculate_skill_match(job_skills: list[str], user_skills: dict, job_title: str = "",
                          job_description: str = "", llm_coverage: dict | None = None) -> dict:
    """
    Calculate skill match score with embedding fallback.
    Returns: {score, matched_skills, missing_skills, partial_skills}
    """
    if not job_skills:
        return {"score": 0.3, "matched": [], "missing": [], "partial": []}

    user_skill_list = _build_user_skill_embeddings(user_skills)
    unrequired = _unrequired_skills(job_skills, job_description, user_skills)
    has_design_context = (
        _has_digital_design_context(job_skills)
        or _digital_role_affinity(job_title, job_skills, job_description) >= _DIGITAL_ROLE_MIN_AFFINITY
    )

    matched = []
    partial = []
    missing = []
    unattributed = []
    total_weight = 0.0
    matched_weight = 0.0

    for job_skill in job_skills:
        # Skip non-skill terms (too generic/ambiguous)
        if _is_non_skill(job_skill):
            continue
        # Same idea, but decided per job by the LLM instead of a hand-kept list:
        # extraction noise and non-skills ("16Personalities", perks, contract
        # terms) must not sit in the denominator as if they were requirements.
        if ((llm_coverage or {}).get(job_skill) or {}).get("verdict") == "not_a_skill":
            continue
        # Bare "design"/"designer" with no accompanying digital-design signal in
        # this same job's skill list is discipline-ambiguous (see
        # _AMBIGUOUS_DESIGN_TERMS): it covers gas mains and automotive CAD as
        # readily as UI work, and it is as often the VERB the posting used
        # ("design and develop detection capabilities") as a requirement at all.
        #
        # Neither answer about it is a measurement. Calling it matched hands the
        # candidate's 90% design skill to a security engineering role; calling it
        # missing asserts both that the job requires design and that the
        # candidate lacks it, and the second half is simply false — they are a
        # designer. So it leaves the denominator entirely, exactly like the two
        # skips above: the job is scored on the terms that do mean something.
        if normalize_skill_name(job_skill) in _AMBIGUOUS_DESIGN_TERMS and not has_design_context:
            unattributed.append(job_skill)
            continue
        total_weight += 1.0

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
                # Last resort: the LLM's coverage verdict (see
                # _llm_skill_coverage). Only ever RESCUES what the deterministic
                # passes already gave up on — it can't overturn a dictionary
                # match — and the displayed level comes from the covering
                # skills.md row, not from the model.
                verdict = (llm_coverage or {}).get(job_skill) or {}
                v, by = verdict.get("verdict"), verdict.get("by")
                by_level = get_user_skill_level(user_skills, by) if by else 0.0
                if v == "full" and by_level > 0:
                    matched.append({"skill": job_skill, "level": by_level, "via": by})
                    matched_weight += 1.0
                elif v == "partial" and by_level > 0:
                    partial.append({"skill": job_skill, "level": by_level, "via": by})
                    matched_weight += 0.35
                elif job_skill in unrequired:
                    # Named by the posting, not asked for by it — see
                    # _unrequired_skills. The candidate does not hold it and was
                    # never required to, so it is neither credit nor gap and
                    # leaves the denominator it was provisionally counted into.
                    unattributed.append(job_skill)
                    total_weight -= 1.0
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
    #
    # The denominator is floored at _SKILL_MIN_REQS because a ratio is only
    # meaningful once the job has stated enough requirements to be a ratio of
    # anything. Unfloored, coverage rewarded vague postings: the same
    # "Geotechnical Design Engineer" scraped three times scored 0.96, 0.24 and
    # 0.00 off the SAME single match ("Design"), purely because each scrape
    # extracted a different number of skill rows — a 1-row posting handed a
    # geotechnical job a 96% skill fit. Measured against review verdicts across
    # 122 documents, that made this component anti-correlated with real fit
    # (r=-0.15) while context alone reached r=+0.62: postings that spelled their
    # requirements out were penalised for it, and vague ones floated to the top.
    coverage = matched_weight / max(total_weight, _SKILL_MIN_REQS) if total_weight > 0 else 0.0
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
        # Named requirements that were scored as neither. Reported rather than
        # dropped silently, because "Design" vanishing from a posting that lists
        # it is exactly the kind of thing that looks like a bug when it is a
        # refusal to guess which discipline the word meant.
        "unattributed": unattributed,
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

    # What a posting means by "N+ years" is paid work, not how long someone has
    # owned the skill. timeline.md states both — spans since 2019, and "roughly
    # 4 years of paid work between Jul 2019 and Jul 2023" — and scoring against
    # the span would claim 8 years where the profile says 4. That is the same
    # overstatement as listing a logo mark that is still a sketch.
    #
    # max() over the spans, not sum, when no paid-work figure is stated: the
    # spans overlap, so adding them counts one year several times.
    user_total = user_exp.get("years_professional", 0) or max(
        user_exp.get("years_python", 0),
        user_exp.get("years_linux", 0),
        user_exp.get("years_automation", 0),
        user_exp.get("years_creative", 0),
    )

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


_REMOTE_TARGETS_CACHE: list[str] | None = None


def _remote_target_countries() -> list[str]:
    """Target countries for remote roles, from config.yaml (priority order)."""
    global _REMOTE_TARGETS_CACHE
    if _REMOTE_TARGETS_CACHE is not None:
        return _REMOTE_TARGETS_CACHE
    default = ["germany", "netherlands", "luxembourg", "france", "sweden",
              "norway", "finland", "switzerland", "austria", "spain"]
    try:
        import yaml
        cfg_path = Path(__file__).parent / "config.yaml"
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
        got = [c.lower().strip() for c in cfg.get("remote_target_countries", [])]
        _REMOTE_TARGETS_CACHE = got or default
    except Exception:
        _REMOTE_TARGETS_CACHE = default
    return _REMOTE_TARGETS_CACHE


# Country -> extra surface forms (adjective, endonym, main cities) for loc match.
_COUNTRY_ALIASES = {
    "germany": ["german", "deutschland", "berlin", "munich", "hamburg"],
    "netherlands": ["dutch", "holland", "amsterdam", "rotterdam"],
    "luxembourg": ["luxembourgish"],
    "france": ["french", "paris"],
    "sweden": ["swedish", "stockholm"],
    "norway": ["norwegian", "oslo"],
    "finland": ["finnish", "helsinki"],
    "switzerland": ["swiss", "zurich", "zürich", "geneva"],
    "austria": ["austrian", "vienna", "wien"],
    "spain": ["spanish", "madrid", "barcelona"],
}

_UK_MARKERS = ("united kingdom", "uk", "scotland", "england", "wales", "britain",
               "edinburgh", "glasgow", "london", "manchester", "birmingham",
               "dundee", "aberdeen", "leeds", "bristol")
# Matched with word boundaries, not as substrings. "uk" is two letters and sits
# inside ordinary place names — Fukuoka, Tsukuba, Fukushima all contain it, and a
# substring test read every one of them as the United Kingdom: the posting then
# skipped the international branch entirely and was scored against the UK city
# tiers. Found 2026-08-19 while adding the Japan search, on "Tsukuba, Ibaraki,
# Japan". The same trap is why exclude_description_keywords is word-bounded.
_UK_RE = re.compile(r"\b(" + "|".join(re.escape(m) for m in _UK_MARKERS) + r")\b")

_AMERICAS_RE = re.compile(
    r"\b(u\.?s\.?a?|united states|americas?|californ\w*|new york|canada|"
    r"latam|brazil|mexico|seattle|san francisco|los angeles|austin|"
    r"boston|chicago|denver|atlanta)\b")
# US state abbreviations after a comma ("San Francisco, CA").
_US_STATE_ABBR_RE = re.compile(r",\s*(ca|ny|tx|wa|ma|il|co|ga|or|fl|nc|va|pa|az)\b")


# Japan, by the shapes LinkedIn writes: "Tokyo, Tokyo, Japan", "Greater Tokyo
# Area", "Kanagawa, Japan". The prefecture names carry the ones that never say
# "Japan" at all.
_JAPAN_RE = re.compile(
    r"\b(japan|japanese|tokyo|osaka|kyoto|yokohama|nagoya|fukuoka|sapporo|kobe|"
    r"kawasaki|saitama|chiba|kanagawa|hyogo|aichi|hokkaido|ibaraki|tochigi|"
    r"tsukuba|shibuya|shinjuku|minato)\b|日本")


def _japan_verdict(is_remote: bool) -> dict:
    """Japan is the one foreign market that is not foreign to the candidate:
    citizenship, no visa question, native language, and a CV that exists in
    Japanese. So remote scores with the target markets rather than as the
    unknown-but-plausible 0.45 any other non-target country gets.

    It is held just under them because of the clock, not the market — JST runs
    8-9h ahead of the UK, so a role with synchronous hours is a night shift.
    That is the same objection the US branch carries, in the other direction.

    On-site is out of scope for exactly the reason every other country's is: the
    search does not fund a move, and the candidate lives in the UK.
    """
    if is_remote:
        return {"score": 0.82,
                "notes": ["✅ Remote — Japan (home market, right to work; "
                          "JST is 8-9h ahead of the UK — verify the overlap)"]}
    return {"score": 0.10, "notes": ["❌ Japan on-site (relocation out of scope)"]}


def _classify_international_location(loc: str, is_remote: bool,
                                     country: str | None = None) -> dict | None:
    """Score clearly non-UK / region-tagged locations for the multi-country
    remote expansion. Returns a final match dict, or None to fall through to the
    UK city tiers. UK-marked locations always fall through (return None).

    `country` (from _infer_country, i.e. the Adzuna country code) is checked BEFORE
    the location text, because the text route needs every place name spelled out:
    "Deutschland" matched and scored 0.20 as German on-site, while "Hagsfeld,
    Karlsruhe" and "España" missed every alias and landed on 0.15 "location
    unknown" — same countries, and 0.15 sat ABOVE the 0.20 that on-site abroad is
    supposed to get, so an unrecognised spelling quietly scored better than a
    recognised one.
    """
    if country:
        cl = country.strip().lower()
        if cl == "uk":
            return None  # UK handled by the detailed city tiers below
        if cl == "us":
            if is_remote:
                return {"score": 0.18,
                        "notes": ["⚠️ US/Americas remote — timezone mismatch "
                                  "(night shift from UK/JP)"]}
            return {"score": 0.05, "notes": ["❌ US/Americas on-site (out of scope)"]}
        if cl == "japan":
            return _japan_verdict(is_remote)
        if cl in _remote_target_countries():
            if is_remote:
                return {"score": 0.85,
                        "notes": [f"✅ Remote — {country} (target market)"]}
            return {"score": 0.20,
                    "notes": [f"⚠️ {country} on-site (relocation out of scope)"]}
        if cl in ("europe", "worldwide"):
            if is_remote:
                return {"score": 0.80 if cl == "europe" else 0.72,
                        "notes": [f"✅ {country} remote (in-scope)"]}
            return {"score": 0.20,
                    "notes": [f"⚠️ {country} on-site (relocation out of scope)"]}
        # A named country outside the target list is still abroad, so on-site is out
        # of scope; remote is unknown-but-plausible rather than scored as a fit.
        if is_remote:
            return {"score": 0.45,
                    "notes": [f"⚠️ Remote — {country} (not a target market; "
                              f"verify timezone and right to work)"]}
        return {"score": 0.10,
                "notes": [f"❌ {country} on-site (out of scope)"]}

    if not loc:
        return None
    if _UK_RE.search(loc):
        return None  # UK handled by the detailed city tiers below

    # Americas / US: timezone mismatch = night shift from UK/JP.
    if _AMERICAS_RE.search(loc) or _US_STATE_ABBR_RE.search(loc):
        if is_remote:
            return {"score": 0.18,
                    "notes": ["⚠️ US/Americas remote — timezone mismatch (night shift from UK/JP)"]}
        return {"score": 0.05, "notes": ["❌ US/Americas on-site (out of scope)"]}

    # Japan before the target list: it is scored on different grounds (see
    # _japan_verdict) and its prefecture names match nothing else here.
    if _JAPAN_RE.search(loc):
        return _japan_verdict(is_remote)

    # Target countries (priority markets) — remote in-scope, on-site not.
    for country in _remote_target_countries():
        forms = [country] + _COUNTRY_ALIASES.get(country, [])
        if any(f in loc for f in forms):
            if is_remote:
                return {"score": 0.85,
                        "notes": [f"✅ Remote — {country.title()} (target market)"]}
            return {"score": 0.20,
                    "notes": [f"⚠️ {country.title()} on-site (relocation out of scope)"]}

    # Europe / EU / EMEA generic.
    if any(t in loc for t in ("europe", "european", "eu ", "emea")) or loc.strip() in ("eu", "europe"):
        if is_remote:
            return {"score": 0.80, "notes": ["✅ Europe / EMEA remote (in-scope)"]}
        return {"score": 0.20, "notes": ["⚠️ EU-based on-site (relocation out of scope)"]}

    # Worldwide / global / anywhere.
    if any(t in loc for t in ("worldwide", "global", "anywhere")):
        if is_remote or "remote" in loc:
            return {"score": 0.72, "notes": ["✅ Worldwide remote (in-scope, verify timezone)"]}

    return None


def _is_remote_friendly(job_loc: str, work_style: str) -> bool:
    """Determine if the job is remote/hybrid friendly."""
    loc = job_loc.lower()
    style = work_style.lower() if work_style else ""
    if style in ("remote", "hybrid"):
        return True
    if "remote" in loc or "hybrid" in loc:
        return True
    return False


# What a posting SAYS about where a remote worker may sit, as opposed to what its
# location field happens to contain. Ordered most specific first: "remote —
# anywhere in Europe" must read as Europe, not as worldwide.
#
# MEASURED 2026-08-29: 76 of 5148 postings state a scope in prose at all (46 of
# them remote). That is the whole population the `stated` confidence can ever
# have, which is why remote_scope is a DERIVED field carrying its confidence
# rather than an extracted one.
_SCOPE_STATED = (
    ("remote_uk", re.compile(
        r"remote (?:within|in|across|from) (?:the )?(?:uk|united kingdom)"
        r"|must be (?:based|located) in the (?:uk|united kingdom)"
        r"|uk[-\s]based (?:only|remote)|uk residents only", re.IGNORECASE)),
    ("remote_eu", re.compile(
        r"remote (?:within|in|across|from) (?:the )?(?:eu|europe)"
        r"|must be (?:based|located) in (?:the )?(?:eu|europe)"
        r"|eu[-\s]based (?:only|remote)|anywhere in europe|europe[-\s]wide", re.IGNORECASE)),
    ("remote_worldwide", re.compile(
        r"work from anywhere|anywhere in the world|remote[^.\n]{0,12}anywhere",
        re.IGNORECASE)),
)


def classify_remote_scope(job_location: str, work_style: str, country: str | None,
                          description: str | None = None) -> tuple[str, str]:
    """(scope, confidence) — how far this arrangement travels, and how sure.

    scope:      onsite | hybrid | remote_uk | remote_country | remote_eu
                | remote_worldwide | remote_americas | remote_unscoped | unknown
    confidence: stated | inferred | unknown

    This exists because "remote" is a boolean the strategy cannot use. A role that
    is remote-within-the-UK stops working the day the visa does; a role that is
    remote-across-Europe does not. Both are `work_style: remote`, and the
    difference between them decides which one is worth taking in 2027.

    `inferred` is the normal case and NOTHING may gate on it. Measured over the
    1294 remote postings in the corpus, the location text resolves 769 to the UK,
    187 to Europe and 55 to Japan, leaves 258 unresolved and 23 empty — so a
    quarter of them are a guess dressed as a field, and the confidence is the
    only thing standing between that guess and a decision.

    A note on `remote_worldwide`: it is nearly extinct here. The two boards that
    supplied "anywhere in the world" postings (remoteok, weworkremotely) were
    dropped from `sources` and purged on 2026-08-29, taking 54 postings with
    them. The live distinction is UK versus Europe, not "work from anywhere".
    """
    style = (work_style or "").lower()
    loc = (job_location or "").lower()
    is_remote = _is_remote_friendly(loc, style)

    if style == "onsite":
        return "onsite", "inferred"
    if style == "hybrid":
        return "hybrid", "inferred"
    if not is_remote:
        return "unknown", "unknown"

    for scope, rx in _SCOPE_STATED:
        if rx.search(description or ""):
            return scope, "stated"

    cl = (country or "").strip().lower()
    if cl == "uk" or (not cl and _UK_RE.search(loc)):
        return "remote_uk", "inferred"
    if cl == "us" or (not cl and (_AMERICAS_RE.search(loc) or _US_STATE_ABBR_RE.search(loc))):
        return "remote_americas", "inferred"
    if cl == "worldwide" or any(t in loc for t in ("worldwide", "global", "anywhere")):
        return "remote_worldwide", "inferred"
    if cl == "europe" or any(t in loc for t in ("europe", "european", "emea")) or loc.strip() in ("eu", "europe"):
        return "remote_eu", "inferred"
    if cl == "japan" or (not cl and _JAPAN_RE.search(loc)):
        return "remote_country", "inferred"
    if cl and cl not in ("", "uk"):
        return "remote_country", "inferred"
    for target in _remote_target_countries():
        forms = [target] + _COUNTRY_ALIASES.get(target, [])
        if any(f in loc for f in forms):
            return "remote_country", "inferred"
    # Remote, and the posting gives nothing to place it. A quarter of them.
    return "remote_unscoped", "unknown"


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


def calculate_location_match(job_location: str, job_work_style: str, user_exp: dict,
                             country: str | None = None) -> dict:
    """
    Match location and work style preferences.
    Returns 0.0-1.0 to allow actual variance in composite score.

    `country` is the authoritative country label when the caller has one (see
    _infer_country, which reads the Adzuna country code out of source_site). Pass
    it: matching on the location TEXT alone depends on a hand-kept list of place
    names, so "Deutschland" scored 0.20 as German on-site while "Hagsfeld,
    Karlsruhe" and "España" fell through to 0.15 "location unknown" — same country,
    different spelling. The alias list cannot be completed by hand; the country code
    does not need to be.
    """
    user_loc = user_exp.get("location", "").lower()
    job_loc = (job_location or "").lower()
    work_style = (job_work_style or "").lower()

    score = 0.0
    notes = []
    remote_flag = False

    # Work style detection
    is_remote = _is_remote_friendly(job_loc, work_style)

    # International region classification (multi-country remote expansion).
    # Fires only for clearly non-UK / region-tagged locations; UK + generic
    # "remote" fall through to the detailed tiers below.
    intl = _classify_international_location(job_loc, is_remote, country)
    if intl is not None:
        return intl

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
# Length of the assembled persona before PERSONA_CHAR_BUDGET is applied, so a
# test can tell "fits" from "was cut to fit". See _load_persona_summary.
_persona_assembled_chars = 0

# Large enough that nothing is cut today (the assembled persona, with the
# portfolio subset, is ~55,000 characters). It is a runaway guard, not a budget
# to spend down: context carries 0.64 of the composite, so a persona the scorer
# cannot see is the most expensive saving available.
PERSONA_CHAR_BUDGET = 64000

# The Havas Lynx posting is 9,608 characters and the previous 5,000 cut it in
# half, so role_fit was judged on the generic agency duties in the first half
# while the sections naming the actual work — visual thinking upstream of the
# brief, AI used to reach a concept in hours — sat past the cut. 12,000 sends
# 99.3% of the corpus whole (5,000 sent 89.3%).
JOB_DESC_CHAR_BUDGET = 12000


def _load_persona_summary() -> str:
    """Load and condense persona docs for the LLM prompt."""
    global _persona_cache
    if _persona_cache is not None:
        return _persona_cache
    # skills.md and timeline.md were absent, so every prompt built from this —
    # context scoring above all — was asked whether the candidate suits a job
    # while holding no list of what they can do and no employment history. The
    # scorer answered on ethos alone, which is why an n8n Billing Specialist
    # reached 92: "reduce friction, automate" is a genuine match of values, and
    # nothing in the prompt said the work is accounting.
    #
    # Most load-bearing first, because the tail of a long persona is what a
    # small model stops attending to.
    persona_files = ["profile.md", "skills.md", "timeline.md", "education.md",
                     "ethos.md", "about.md", "interests.md",
                     "cover-letter-evidence.md"]
    # Portfolio project files, which no scoring path had ever read. The scorer
    # wrote "no evidence of AI-assisted brainstorming in their portfolio" about
    # a portfolio it had never been shown.
    #
    # A subset, not the directory. Measured against 387 stored CV reviews,
    # role_fit undershoots graphic_designer postings by 23.2 points and
    # creative_technologist by -4.4 — it reads this candidate as an engineer,
    # and 14 of the 19 project files are systems write-ups that would deepen
    # exactly that reading. These five are the ones evidencing design and art
    # as work delivered. Ordered design-first for the same attention reason.
    #
    # sketch-of-tomoki-my-elder-brother.md is deliberately absent: it is
    # artwork, not design, and role_fit is not asking about artwork.
    portfolio_files = ["logo-design-for-myself.md",
                       "connecting-the-dots-a-personal-graph-of-creative-practice.md",
                       "taifunome.md",
                       "hive-floral-pod-3d-conceptual-art.md",
                       "so-close-yet-so-far-encounter-with-a-fox.md"]
    # Hard facts first: smaller LLMs otherwise infer "based in Japan" from
    # scattered Japan references (remote hardware, past photography) even
    # though profile.md states the location explicitly.
    parts = [
        "--- KEY FACTS (authoritative) ---\n"
        "Current location and work eligibility are recorded in profile.md.\n"
        "Do NOT frame a past relocation as an upcoming move, and never claim the candidate lives in, "
        "is near, or is relocating to the employer's location.\n"
        "Any mentions of Japan below refer to past work, photography subjects, or a "
        "remote compute machine — NOT the candidate's current location."
    ]
    # ethos.md gets a larger budget: at 2000 chars the model saw only the
    # local-AI mentions and never reached the deployment-agnostic /
    # "What I Do" sections, and reported a "local-first preference" mismatch
    # against cloud-heavy jobs.
    #
    # skills.md is 12,128 characters and timeline.md 5,996, so at the 2,000
    # default they would arrive as a fragment of their first section. They are
    # the evidence for "can this person do the work", which is the question the
    # 2,000 default was never sized for.
    #
    # life_goal.md is deliberately absent from persona_files. It says the job
    # funds the real goal, which is equally true of every posting and separates
    # none of them — and while it lived inside ethos.md it sat in the same
    # prompt as the fit question, inviting "well, any job funds the art".
    #
    # These limits are sized to admit each file whole, with headroom, because
    # the previous set cut where nothing had asked them to: skills.md lost
    # 5,628 of its 12,128 characters and profile.md 2,880 of 4,880, so the
    # axis that asks "could they do this job" was answered from half the
    # evidence. A limit still exists so one file that grows without bound
    # cannot starve the files after it — that is the only job it has.
    per_file_limit = {"profile.md": 6000, "skills.md": 14000, "timeline.md": 8000,
                      "education.md": 3000, "ethos.md": 8000, "about.md": 4000,
                      "interests.md": 3000, "cover-letter-evidence.md": 4000}
    for fname in persona_files:
        fpath = USER_PROFILE_DIR / fname
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"--- {fname} ---\n{content[:per_file_limit.get(fname, 4000)]}")
    portfolio = []
    for fname in portfolio_files:
        fpath = PORTFOLIO_DIR / fname
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8").strip()
            if content:
                portfolio.append(f"--- portfolio/{fname} ---\n{content[:6000]}")
    if portfolio:
        parts.append("--- PORTFOLIO (work delivered, not claimed) ---\n"
                     + "\n\n".join(portfolio))
    persona = "\n\n".join(parts) if len(parts) > 1 else ""
    # The length BEFORE the budget cut. Without it there is nothing to test:
    # asserting len(_load_persona_summary()) <= PERSONA_CHAR_BUDGET compares the
    # cut string against the size it was cut to, which is true by construction
    # and stays true no matter how much evidence the cut is discarding. That
    # tautology shipped once and passed while the portfolio was being dropped.
    global _persona_assembled_chars
    _persona_assembled_chars = len(persona)
    # The one place the persona is truncated. It used to be truncated twice:
    # here per file, and again by the prompt at 14,000 characters — which the
    # per-file limits summed past, to 25,429. about.md, interests.md and
    # cover-letter-evidence.md were read, capped, joined and then discarded
    # entirely by that second cut, and ethos.md arrived at 16% of itself, so
    # the `ethos` axis was scored nearly blind and cover-letter-evidence.md —
    # the file that exists to evidence "can they do the work" — never reached
    # the model at all. Callers must send what this returns, whole.
    _persona_cache = persona[:PERSONA_CHAR_BUDGET]
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


# Requirements judged per LLM call. Sized so the JSON reply stays well inside
# max_tokens even for verbose skill names (see the 75-skill truncation above).
_COVERAGE_BATCH = 20


def _resolve_by(by: str, known: dict) -> str:
    """Map an LLM-reported covering skill onto a real skills.md row name.

    Returns "" when it matches no row — an unattributable credit is dropped
    rather than trusted, so the model cannot invent a skill the candidate lacks.
    """
    exact = known.get(normalize_skill_name(by))
    if exact:
        return exact
    # "Name (level) [category] — notes" → "Name"
    head = re.split(r"\s*[(\[—]", by, maxsplit=1)[0].strip()
    exact = known.get(normalize_skill_name(head))
    if exact:
        return exact
    # Last resort: a known row named somewhere inside the string. Longest first
    # so "Local LLM Orchestration" wins over a shorter row it contains.
    hay = normalize_skill_name(by)
    for norm in sorted(known, key=len, reverse=True):
        if re.search(r"\b" + re.escape(norm) + r"\b", hay):
            return known[norm]
    return ""


def _llm_skill_coverage(job_title: str, job_description: str, job_skills: list[str],
                        user_skills: dict) -> dict | None:
    """Ask the LLM which of a job's required skills the candidate actually covers.

    The dictionary path (exact → SKILL_SYNONYMS → substring → TF-IDF) can only
    match shared words, so a paraphrase with no lexical overlap ("Software
    Engineering" vs "Code Standards"/"Python") silently reads as a gap, and the
    synonym dict can never enumerate job-posting vocabulary. A bare-name
    embedding fallback was measured and REJECTED: nomic-embed-text scores
    "Mechanical Design ~ Visual Design" at 0.707, above every genuine pair, so
    it would resurrect the physical-design false positives the ambiguity guards
    exist to stop (see _AMBIGUOUS_DESIGN_TERMS). Two-word skill names carry too
    little context to disambiguate discipline.

    The LLM gets what the embedding lacked — the job title and description — so
    it can tell a gas-pipe "Design Engineer" from a UI one. It returns which
    CANDIDATE skill covers each requirement; the level shown to the user is then
    looked up from skills.md for that skill, never invented by the model.

    Returns {job_skill: {"verdict": "full"|"partial"|"none", "by": <skill name>}}
    or None on failure. Callers treat None as "no opinion" and keep the
    dictionary verdict.
    """
    if not job_skills or not user_skills:
        return None

    # A 75-skill posting produced JSON longer than max_tokens, so the response
    # was truncated mid-object, failed to parse, and the whole job silently got
    # NO verdict at all. Judge in fixed-size batches instead, so cost and output
    # length scale with the list rather than the model's token ceiling.
    if len(job_skills) > _COVERAGE_BATCH:
        merged: dict = {}
        for i in range(0, len(job_skills), _COVERAGE_BATCH):
            part = _llm_skill_coverage(job_title, job_description,
                                       job_skills[i:i + _COVERAGE_BATCH], user_skills)
            if part:
                merged.update(part)
        return merged or None

    catalogue = []
    for category, skills in user_skills.items():
        for skill in skills:
            # Notes carry the concrete evidence ("GitHub Actions workflow
            # automation", "Claude Code / agentic coding") that lets the model
            # credit a requirement no row is literally titled after.
            note = (skill.get("notes") or "").strip()
            line = f"- {skill['name']} ({skill['level']}) [{category}]"
            if note:
                line += f" — {note[:180]}"
            catalogue.append(line)
    if not catalogue:
        return None

    prompt = f"""You decide which of a job's required skills a candidate already covers.

## Candidate's skills (the ONLY skills they have — nothing else may be claimed)
{chr(10).join(catalogue)}

## The job
Title: {job_title}
Description: {(job_description or '')[:3000]}

## Required skills to judge
{chr(10).join('- ' + s for s in job_skills)}

## Task
For EACH required skill, decide:
  "full"        — a candidate skill above clearly covers it (same thing, or a direct superset)
  "partial"     — a candidate skill is adjacent/related but does not fully cover it
  "none"        — the candidate has nothing that covers it
  "not_a_skill" — the term is not a professional skill at all, so it should not
                  be scored either way: personality tests (16Personalities,
                  Myers-Briggs), perks, company names, locations, contract terms,
                  vague qualities (cost efficiency, attention to detail), or
                  extraction noise. Use this ONLY for non-skills — a real skill
                  the candidate lacks is "none", never "not_a_skill".

Rules:
- Use the JOB TITLE and DESCRIPTION to read what a required skill MEANS here.
  "Design" at a gas/mechanical/automotive engineering job is physical CAD design
  and is NOT covered by the candidate's Web/UI/Visual Design skills — answer
  "none". The same word at a web/product job IS covered.
- "by" must be ONLY the candidate skill's NAME, copied exactly as written above
  — nothing else. Do NOT include the level, the [category], or the notes.
  Correct: "Multi-Agent Systems".  Wrong: "Multi-Agent Systems (intermediate) [ML / AI]".
- Do NOT be generous. If the candidate genuinely lacks a platform or tool
  (AWS, Azure, GCP, Salesforce, a specific framework they never listed),
  answer "none". Inventing coverage produces a false CV claim.
- Judge every required skill, using its exact spelling as the key.

Respond ONLY with JSON:
{{"<required skill>": {{"verdict": "full|partial|none|not_a_skill", "by": "<candidate skill or empty>"}}, ...}}"""

    try:
        from llm_client import call_llm as _call_llm
        content = _call_llm(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=("You are a strict skill-coverage adjudicator. Output ONLY valid JSON. "
                           "Never credit a skill the candidate did not list. "
                           "Read the job description to disambiguate what a skill word means."),
            temperature=0.0,
            max_tokens=1500,
        )
        import json as _json
        matches = list(re.finditer(r'\{.*\}', content, re.DOTALL))
        known = {normalize_skill_name(s["name"]): s["name"]
                 for skills in user_skills.values() for s in skills}
        # Models echo the requirement with their own casing ("AI Tools" for the
        # job's "Ai Tools"). Map every verdict back onto the job's EXACT string
        # so callers can look it up directly — a case mismatch silently dropped
        # the verdict before.
        job_key = {normalize_skill_name(s): s for s in job_skills}
        for m in reversed(matches):
            try:
                raw = _json.loads(m.group(), strict=False)
            except (ValueError, TypeError):
                continue
            out = {}
            for job_skill, verdict in raw.items():
                if isinstance(verdict, str):
                    verdict = {"verdict": verdict, "by": ""}
                if not isinstance(verdict, dict):
                    continue
                v = str(verdict.get("verdict", "none")).lower().strip()
                if v not in ("full", "partial", "none", "not_a_skill"):
                    continue
                by = str(verdict.get("by", "") or "").strip()
                # Reject a "by" that is not a real skills.md row — the model
                # occasionally answers with the JOB's wording instead. It also
                # likes to echo the whole catalogue line back ("Multi-Agent
                # Systems (intermediate) [ML / AI] — Hermes 9-agent…"), so strip
                # the level/category/notes decoration before matching, then fall
                # back to finding a known row named inside the string.
                by = _resolve_by(by, known) if by else ""
                if v in ("full", "partial") and not by:
                    # Unattributable credit is not credit — the model sometimes
                    # cites a phrase from the JOB AD ("Supporting recruitment
                    # activity") as the covering skill. Record the refusal as
                    # "none" rather than dropping the entry: discarding it left
                    # the job with no verdict at all, so it looked uncovered and
                    # was retried forever, when the honest answer is simply that
                    # the candidate does not cover it.
                    v, by = "none", ""
                key = job_key.get(normalize_skill_name(job_skill))
                if not key:
                    continue  # a requirement this job never listed
                out[key] = {"verdict": v, "by": by}
            if out:
                return out
        return None
    except Exception:
        return None


_UNQUOTED_VALUE = _re_framing.compile(
    r'("(?:reasoning_en|reasoning_ja|role_requirement)"\s*:\s*)(?!["\d\[{])([^\n]+?)(,?)\s*\n',
)


def _close_truncated_json(content: str) -> str | None:
    """Salvage the complete key/value pairs from a reply that was cut off.

    The parser below looks for `{...}`, which needs a closing brace, so a reply
    truncated mid-sentence matches nothing at all and the whole call is recorded
    as a failure. That is the wrong loss: this prompt asks for `ethos` and
    `role_fit` FIRST and the long bilingual reasoning last, so the numbers are
    complete and only the prose is cut. Moth's Creative Technologist posting
    came back with ethos 88 and role_fit 72 followed by a sentence that stopped
    mid-word, and was recorded as unscored.

    Truncation is a property of the prompt, not of the key: the persona summary
    alone is 55k characters, so the request runs to ~61.5k and the completion
    budget is what gives. Raising max_tokens was tried for the same symptom
    (see the note on the call below, 300 -> 600/900) and does not address a
    prompt that grows.

    Cuts at the last complete pair at depth 1 — never inside a string — and
    closes the brace. Returns None when nothing complete survives.
    """
    start = content.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    cut = -1
    for i in range(start, len(content)):
        ch = content[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return None  # not truncated — the ordinary path handles it
        elif ch == "," and depth == 1:
            cut = i
    if cut < 0:
        return None
    return content[start:cut] + "}"


def _repair_json(blob: str) -> str:
    """Put quotes back on a prose value the model left bare.

    The brief prompt asks for four fields and gets three of them right; the
    long free-text one comes back as `"reasoning_en": The candidate's ethos
    aligns...` often enough to matter. json.loads(strict=False) does not help —
    an unquoted value is a syntax error, not a control-character one — so the
    whole reply was discarded and _ollama_context_score returned None. That is
    the mode the nightly backfill runs in, so new postings were silently
    losing their context score entirely.

    Only the known prose keys are touched, and only when the value does not
    already open with a quote, digit, or bracket.
    """
    def _fix(m: _re_framing.Match) -> str:
        value = m.group(2).rstrip().rstrip(',')
        # Backslashes and inner quotes would just move the syntax error along,
        # and neither carries meaning in a sentence of prose.
        value = value.replace("\\", "").replace('"', "'")[:1500]
        return f'{m.group(1)}"{value}"{m.group(3)}\n'

    return _UNQUOTED_VALUE.sub(_fix, blob)


def _ollama_context_score(job_description: str, persona_summary: str,
                          brief: bool = True, _retries_left: int = 1) -> dict | None:
    """
    Ask the LLM to rate context/ethos alignment on a 0-100 scale.
    Returns {"score": float (0-1), "reasoning": str, ...} or None on failure.

    brief=True (the default since 2026-08-26): English-only reasoning. The long
    bilingual form asks for the same 3-4 sentences TWICE, in English and in
    Japanese, and that is what overruns the reply. The completion stops far
    short of max_tokens — 353 to 1020 characters against a 900-token (~3600
    character) budget — because the persona alone is 55k characters and the
    whole request runs to ~61.5k, so what is left to emit is a few hundred
    tokens whatever max_tokens says. Raising it was tried (300 -> 600/900) and
    is not the lever.

    Measured over the same six postings, one call each:

      bilingual   2 of 6 replies truncated   scores .20 .75 .65 .15 .35 .15
      brief       0 of 6 truncated           scores .25 .75 .60 .15 .40 .10

    Identical judgement — every difference is 0.05 or less, far inside the
    0.48 spread this scorer shows across repeat draws of one posting — and
    nothing is cut. Shrinking the PERSONA to the same end would be deleting the
    candidate's own evidence, which has been shipped and reverted here before
    (see _load_persona_summary): it is the input that must stay whole, and the
    duplicated output that need not.

    Japanese is not lost, it is deferred: llm_context_backfill translates
    context_reasoning_en for jobs above its threshold, so the reports a human
    reads stay bilingual while bulk scoring does not pay for it. Pass
    brief=False to ask for both languages in one call.

    role_fit rewards seniority in the posting and the CV reviews do not agree.
    The measurements, and the fix that was tried and reverted, are recorded on
    the prompt below — read that before attempting it again.

    Reasoning that calls the candidate local-first is retried once, then
    scrubbed — see _scrub_deployment_framing.
    """
    if not job_description or not persona_summary:
        return None

    # KNOWN, UNFIXED: role_fit rewards seniority in the posting. Controlling for
    # role, it rises monotonically from entry to senior in all six buckets with
    # enough data — graphic_designer 34.0/33.7/49.3, product_designer
    # 42.9/47.1/62.5, web_developer 38.2/44.2/66.3, research_engineer
    # 20.8/24.8/48.8, general 22.3/24.5/38.4, creative_technologist -/65.3/76.2.
    # It says this candidate can do a Senior Graphic Designer job better than a
    # Junior one. The CV reviews disagree: they rate internship, entry and mid
    # postings within 2 points of each other, while role_fit is harsher on
    # entry than mid by 6.6 points (95% CI [+0.8, +12.4]) and on internship by
    # 14.3 ([+4.6, +23.7]). Not a length effect — r(role_fit, description
    # length) = +0.013 over 2,266 postings.
    #
    # DO NOT "fix" this by stating the level in the prompt. That was tried:
    # a `## Seniority this posting is pitched at` block naming the level, with
    # an instruction to judge against that level's bar and "do not reward a
    # posting for asking for more". Measured on 47 CV-reviewed jobs, two thirds
    # junior, both arms in one run: junior scores did not move (34.8 -> 34.4)
    # and mid/senior rose (56.4 -> 60.7), so the junior-vs-control residual gap
    # WIDENED from +13.0 to +17.7, 95% CI on the change [+0.4, +9.1]. Naming
    # the level made the model more generous to senior postings and did nothing
    # for junior ones — the opposite of the instruction it was given. Overall r
    # rose +0.215 -> +0.333 with CI [+0.003, +0.243], a lower bound one sample
    # from null, and rho did not separate at all; for a ranking, rho is the
    # measure that matters. Reverted.
    shared = f"""You are a career alignment analyst. Rate this job against the candidate on TWO separate axes.

## Candidate Profile
{persona_summary}

## Job Description
{job_description[:JOB_DESC_CHAR_BUDGET]}

## Task
Score each axis 0-100, independently. Do not let one influence the other.

1. `ethos` — would this candidate WANT this job? Work philosophy, values, creative vs corporate culture, autonomy, multi-disciplinary creative-engineer fit.

2. `role_fit` — could this candidate DO this job? Judge the actual duties and required expertise against what the profile evidences. This is where a job that shares the candidate's values but demands expertise they do not have must score low. Ask what the posting says the person will DO all day, and whether the profile shows that work having been done. A posting whose core requirement appears nowhere in the profile scores under 30 on this axis no matter how appealing the company is.

Name the core requirement you judged `role_fit` on, in `role_requirement`.

Note: The candidate is deployment-agnostic. They run local models in personal research and standard enterprise cloud (AWS, hosted model APIs, managed services, third-party SaaS) in professional work, choosing per constraint — latency, cost, privacy, team toolchain — not per preference. This is portability, NOT a local-first bias. Do NOT describe the candidate as "local-first", do NOT treat a cloud or enterprise stack as a mismatch, and do NOT mention local-vs-cloud in the reasoning at all."""

    # Style for both modes: plain, simple English. Short words, short
    # sentences, no jargon or filler. Say the one thing that drives the score.
    if brief:
        prompt = shared + """

Respond ONLY with JSON:
{"ethos": <number 0-100>, "role_fit": <number 0-100>, "role_requirement": "<the duty or expertise you judged role_fit on>", "reasoning_en": "<3-4 short, plain sentences>"}
Use simple words, short sentences. Say what fits, what does not, and the main reason for the score. No filler.
Plain prose only — NO markdown, NO bold, NO headers, NO bullet points, NO labels like "Fits:"/"Doesn't fit:". Just 3-4 flowing sentences.
BANNED: the reasoning must not contain "local-first", "local first", "self-hosted", "open-source preference", or any claim that cloud / enterprise / third-party tooling is a mismatch for this candidate. The candidate uses cloud and local equally.
"""
    else:
        prompt = shared + """

Respond ONLY with JSON:
{"ethos": <number 0-100>, "role_fit": <number 0-100>, "role_requirement": "<the duty or expertise you judged role_fit on>", "reasoning_en": "<3-4 short, plain sentences>", "reasoning_ja": "<短く平易な日本語で3〜4文>"}

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
            # 300 was sized for a reply carrying one score and a sentence. The
            # two-axis prompt adds role_fit and role_requirement, and at 300 the
            # JSON is cut mid-string — the parser finds no closing brace and the
            # whole call returns None. brief=True is the mode the nightly runs
            # (llm_context_backfill), so every new posting silently lost its
            # context score. Measured: 300 truncates, 500 completes.
            max_tokens=600 if brief else 900,
        )

        import json, re
        candidates = [m.group() for m in re.finditer(r'\{.*\}', content, re.DOTALL)]
        if not candidates:
            # No closing brace anywhere: the reply was cut off. The scores come
            # first and are complete — see _close_truncated_json.
            salvaged = _close_truncated_json(content)
            if salvaged:
                candidates = [salvaged]
        for match in reversed(candidates):
            try:
                data = json.loads(_repair_json(match), strict=False)
                # role_fit IS the score. Both axes are asked for and only one is
                # used, which looks wasteful and is the whole mechanism: asked
                # for ethos alone the model rated an n8n Billing Specialist 92,
                # because "reduce friction, automate" genuinely matches the
                # candidate's values and nothing made it weigh that the work is
                # accounting. Given somewhere else to put "the work is
                # adjacent", the fit judgement gets strict.
                #
                # Measured against 316 stored CV review scores: the old single
                # score r=+0.294, this prompt's ethos +0.382, its role_fit
                # +0.459 — and every blend of the two scores below role_fit on
                # its own, consistently across five samples. ethos is kept in
                # the record because it is the half a reader wants when
                # deciding whether to apply anyway.
                score = float(data.get("role_fit", data.get("score", 50)))
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

                # Which model produced this, not just "an LLM did". context carries
                # 0.64 of the composite weight, and the provider chain silently
                # changes what answers: when all ten Mistral keys hit their monthly
                # limit mid-run, scoring fell through to ollama, recorded
                # indistinguishably. Stored so a weaker model's scores can be found
                # and refreshed later — `--reanalyze --llm-context` skips anything
                # already tagged "llm", so without this they never would be.
                import llm_client as _lc
                out = {"score": round(score, 2), "reasoning": reasoning,
                       "reasoning_en": reasoning_en, "reasoning_ja": reasoning_ja,
                       "provider": _lc.current_provider()}
                # The axis that did not become the score, and the requirement it
                # was judged against — the reader's evidence for a number that
                # is now mostly low. Absent on a reply that predates the
                # two-axis prompt, so callers must treat them as optional.
                if "ethos" in data:
                    try:
                        out["ethos"] = max(0.0, min(100.0, float(data["ethos"]))) / 100.0
                    except (TypeError, ValueError):
                        pass
                if data.get("role_requirement"):
                    out["role_requirement"] = str(data["role_requirement"])[:200]
                return out
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
{job_description[:JOB_DESC_CHAR_BUDGET]}
"""
    else:
        prompt = f"""You are a job description summarizer. Summarize the following job description in 3-4 sentences.

Cover: role, main duties, required skills, and what makes this role distinctive. Use plain, simple words and short sentences. No markdown, no bullet points, no jargon.

Respond ONLY with JSON. Both values MUST be plain strings (flowing prose,
3-4 short sentences) — NEVER nested objects, lists, or markdown headings/bold:
{{"summary_en": "<3-4 short, plain sentences in English>", "summary_ja": "<短く平易な日本語で3〜4文>"}}

## Job Description
{job_description[:JOB_DESC_CHAR_BUDGET]}
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

        # Normalize raw similarity to 0-1 range by stretching the observed
        # P1-P99 band. Re-measured on 588 postings against the persona as it
        # stands now: P1 0.008, P50 0.048, P99 0.136. The previous pair (0.015,
        # 0.079) came from 507 postings and a smaller persona, and against
        # today's distribution 21% of jobs sat at or above that ceiling —
        # everything in the top fifth compressed onto one value.
        RAW_FLOOR = 0.008   # P1 observed, n=588
        RAW_CEIL = 0.136    # P99 observed, n=588
        if best_sim <= RAW_FLOOR:
            normalized = 0.0
        elif best_sim >= RAW_CEIL:
            normalized = 1.0
        else:
            normalized = (best_sim - RAW_FLOOR) / (RAW_CEIL - RAW_FLOOR)

        # TF-IDF measures word overlap, not meaning: "Gas Designer" shares
        # "design / technical / drawings / project" with the persona and
        # saturates despite being a different field. Cap the fallback so
        # surface overlap can register a positive signal but never claim a fit
        # the LLM has not confirmed — only context_source="llm" is trusted to
        # award a high context score.
        #
        # 0.30, not 0.6, because the axis under it changed meaning. The cap was
        # set when context asked "would this candidate want this job" and
        # averaged ~0.46; since 5dedcf8 it asks "could they do it" and the
        # LLM-scored median is 0.30. At 0.6 an unread job outranked roughly
        # 85% of read ones on an axis carrying 0.64 of the composite, which is
        # how four trade postings — Mechanical Designer, Electrical Designer,
        # Sales Engineer - Rockfall and Geotechnical — reached the generation
        # set with a skills score of 0.0, held out only by an
        # exclude_title_keywords entry.
        #
        # Scaled into the band rather than clipped at the top of it. A hard
        # min() put 52% of postings on the cap exactly, discarding the ordering
        # the similarity had just computed — the same "one value for everything
        # above a line" flaw as the stale RAW_CEIL above it. Multiplying keeps
        # the full 0..cap gradient, so a job the model never read ranks at most
        # as high as a typical read one, and unread jobs still sort among
        # themselves.
        TFIDF_SCORE_CAP = 0.30
        normalized = normalized * TFIDF_SCORE_CAP

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


def composite_weights(config: dict | None = None, override: dict | None = None) -> dict:
    """The weights a composite must be computed from: the CONFIG's, not the ones
    stored on the job.

    Every pass that rewrites a composite used to build this dict for itself off
    `job["match"]["weights"]` — llm_context_backfill, rescore_context and
    run.py's --llm-context loop all did. That reads a SNAPSHOT of the weights as
    they were when the job was last fully scored, so the moment config.yaml
    changes, those passes keep scoring on the old ones and the database splits
    into two populations that cannot be compared.

    That is not hypothetical. The reweighting on 2026-08-24 moved skills from
    0.20 to 0.45 and context from 0.64 to 0.40; Lloyds Banking Group's Software
    Engineer report still showed "Skills 20% | Role Fit 64%" days later, over a
    composite computed from them, because nothing had re-scored it through
    analyze_match. llm_context_backfill's own fallback was a third set again
    (skills 0.4, experience 0.25), matching neither the config nor
    DEFAULT_WEIGHTS.

    `override` is for a caller deliberately scoring against something other than
    the shipped weights — a grid search, a what-if — and is the only way to get
    anything else.
    """
    w = override or (config or {}).get("weights") or DEFAULT_WEIGHTS
    return {
        "skills": w.get("skills", 0.40),
        "experience": w.get("experience", 0.25),
        "location": w.get("location", 0.10),
        "salary": w.get("salary", 0.05),
        "context": w.get("context", 0.20),
    }


# Japanese titles carry no word boundaries, so the tokeniser below reduces
# "QAエンジニア" to one unknown token and the English whitelist cannot hit it. Every
# Japanese-titled posting therefore fell to the 0.1 penalty: measured on the 26
# Japan postings of 2026-08-21, all 16 written in Japanese scored 0.02-0.05 while
# their English-titled neighbours scored 0.19-0.73 — with comparable skills (0.45)
# and LLM context (0.45). The whitelist was rejecting a language, not a role.
#
# The role vocabulary comes from config's keyword_aliases, which already maps each
# searched English keyword onto its Japanese equivalents, so the search terms and
# the relevance check cannot drift apart. The generic nouns below mirror the
# English target_words, which are likewise role words rather than exact titles.
_JA_GENERIC_TARGETS = (
    "エンジニア", "デザイナー", "デザイン", "開発", "設計", "実装", "制作",
    "プログラマ", "アーティスト", "テクニカル", "テクノロジ", "クリエイティブ",
    "品質保証", "テスト", "検証", "データ", "分析", "自動化", "運用", "保守",
    "インフラ", "クラウド", "システム", "ソフトウェア", "アプリ", "ウェブ",
    "フロントエンド", "バックエンド", "プロデューサー", "ディレクター",
    "コンサルタント", "サポート", "ツール", "基盤",
)

# Mirrors exclusion_words. Without these the fix would open the gate rather than
# translate it: a Japanese nursing or driving post has no English keyword either,
# so it would sail through on a generic noun instead of being excluded.
_JA_EXCLUSIONS = (
    "看護", "介護", "保育", "医師", "薬剤師", "歯科", "調理", "料理", "接客",
    "ドライバー", "運転", "配送", "配達", "警備", "清掃", "販売", "店舗",
    "美容", "セラピスト", "教員", "教師", "講師", "塾", "施工", "土木", "建築士",
    "大工", "電気工事", "配管",
)

_ja_target_cache: tuple[str, ...] | None = None


def _ja_target_terms() -> tuple[str, ...]:
    """Japanese role terms: the configured search aliases plus generic nouns."""
    global _ja_target_cache
    if _ja_target_cache is None:
        terms = set(_JA_GENERIC_TARGETS)
        try:
            from selection import load_config
            for aliases in (load_config().get("keyword_aliases") or {}).values():
                terms.update(a for a in aliases if a)
        except Exception:
            pass
        _ja_target_cache = tuple(terms)
    return _ja_target_cache


def _runway_fit(contract_months, config: dict) -> str:
    """Does a fixed-length engagement finish before the visa does?

    fits | ends_after_expiry | unknown. Deterministic, no model call, and
    `unknown` is the honest answer for most postings: measured 2026-08-29, only
    246 of 5202 postings state a length at all (analyzer.contract_duration_months).

    This is a fact about time, not about eligibility. "ends_after_expiry" says the
    contract runs past 2027-10-09 — it does NOT say the job is unavailable, that
    sponsorship is needed, or that anything is impossible. What to do with a role
    that outlasts the visa is a human decision, and the sponsorship flag beside it
    is evidence for that decision rather than an answer to it.
    """
    if not isinstance(contract_months, (int, float)) or contract_months <= 0:
        return "unknown"
    from selection import months_until_expiry  # local import: avoids a cycle

    left = months_until_expiry(config)
    if left is None:
        return "unknown"
    return "fits" if contract_months <= left else "ends_after_expiry"


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
    # Substring, not token: Japanese is written without spaces, so there is no
    # word to look up.
    has_exclusion = has_exclusion or any(x in title for x in _JA_EXCLUSIONS)

    if has_exclusion:
        return 0.0  # Hard exclusion (nurse, driver, etc.) always applies

    if not has_target:
        has_target = any(t.lower() in title_lower for t in _ja_target_terms())

    if not has_target:
        # No keyword hit — let a confident LLM context read rescue it
        # before falling back to the harsh 0.1 penalty.
        if context_source == "llm" and context_score is not None and context_score >= 0.6:
            return 1.0
        return 0.1  # Low score for completely unrelated titles

    return 1.0


def _context_is_contradicted(stored_score, skills_score, draws: int, config: dict) -> bool:
    """Does a stored context score disagree with the skills score badly enough
    to be worth measuring again?

    Context is the noisy term and skills is the reproducible one, so the two
    disagreeing is evidence about the context score, not about the job. Only a
    disagreement in one direction counts — a low context under strong skills —
    and only until the job has been drawn `max_draws` times, which caps the
    extra spend at one call per job for the lifetime of the database.
    """
    cfg = config.get("context_rescore") or {}
    if not cfg.get("enabled"):
        return False
    if draws >= int(cfg.get("max_draws", 2)):
        return False
    if not isinstance(stored_score, (int, float)) or not isinstance(skills_score, (int, float)):
        return False
    return (stored_score <= float(cfg.get("context_max", 0.30))
            and skills_score >= float(cfg.get("skills_min", 0.50)))


def analyze_match(job: dict, config: dict, weights: dict | None = None, skip_summary: bool = False,
                  skip_llm_context: bool = False) -> dict:
    """
    Run all match analyses and return combined result.
    Pass custom weights via config['weights'] or weights parameter.
    If skip_summary=True, skip LLM job summary generation (faster batch mode).
    If skip_llm_context=True, score context with TF-IDF instead of calling the
    LLM. For jobs the config filter already rejected: they are kept in the DB so
    that loosening a keyword later needs no re-scrape, but a rejected posting
    does not need a model's opinion to sit there — and a stored LLM context is
    still reused when one exists, so nothing already paid for is thrown away.
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

    # Detect if description is genuinely missing. Length alone is not enough:
    # a failed scrape can return kilobytes of tracker JavaScript, which is worse
    # than an empty string because it passes the length test and then gets fed to
    # the LLM context scorer as if it were prose (69 adzuna entries did exactly
    # this, and 32 of them landed inside the top 30% on context scores up to
    # 0.88 derived from reading a JWT).
    description_missing = (
        not job_description
        or len(job_description.strip()) < 100
        or is_junk_description(job_description)
    )

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

    # Individual scores. Skill coverage is an LLM verdict computed ONCE per job
    # and stored on the job (see _llm_skill_coverage / skill_coverage_backfill),
    # so offline reruns (recompute_skill_scores) reuse it for free.
    llm_coverage = analysis.get("skill_coverage")
    skill_match = calculate_skill_match(job_skills, user_skills, job.get("title", ""),
                                        job_description, llm_coverage=llm_coverage)
    exp_match = calculate_experience_match(job_level, user_exp)
    # Pass the inferred country so location scoring does not depend on whether the
    # place name happens to be in _COUNTRY_ALIASES.
    job_country = _infer_country(job)
    loc_match = calculate_location_match(job_location, job_work_style, user_exp,
                                         country=job_country)
    sal_match = calculate_salary_match(job_salary, config.get("min_salary_gbp", 30000))
    # Reuse pre-existing LLM context score instead of re-scoring: LLM scores
    # are expensive and must survive plain --reanalyze runs. Accepts the
    # canonical flag (context_source == "llm") plus both legacy schemas
    # (llm_context_tagged from run.py, match["context"] dict from
    # bulk_analyze_cloud.py).
    old_match = job.get("match") or {}
    legacy_ctx = old_match.get("context")
    ctx_source = "llm"
    stored_llm = bool(old_match.get("context_source") == "llm"
                      or old_match.get("llm_context_tagged"))
    # A score already on the job is one draw unless it says otherwise; anything
    # measured before this field existed predates the count.
    ctx_draws = int(old_match.get("context_draws") or (1 if stored_llm else 0))
    if stored_llm:
        stored_ctx = {
            "score": old_match.get("context_score", 0),
            "reasoning": old_match.get("context_reasoning", ""),
            "reasoning_en": old_match.get("context_reasoning_en", ""),
            "reasoning_ja": old_match.get("context_reasoning_ja", ""),
            "top_terms": old_match.get("context_top_terms", []),
            # Carry the recorded provider forward, or a rerun that reuses the stored
            # score would blank it and lose the only record of what produced it.
            "provider": old_match.get("context_provider"),
            "ethos": old_match.get("context_ethos"),
            "role_requirement": old_match.get("context_role_requirement"),
        }
        redraw = (not skip_llm_context) and _context_is_contradicted(
            stored_ctx["score"], skill_match["score"], ctx_draws, config
        )
    else:
        stored_ctx = None
        redraw = False

    if stored_ctx is not None and not redraw:
        ctx_match = stored_ctx
    elif stored_ctx is not None:
        # The stored score is one draw of a measurement that does not repeat:
        # the same posting, persona and code scored nine times returned 0.40 to
        # 0.88. Skills, which reproduces exactly, says this job fits. One term
        # contradicting the other is not a verdict, it is a reason to measure
        # again — so draw once more and average, which halves the variance on
        # the term holding 40% of the composite.
        #
        # The correction is deliberately one-sided: only a LOW stored score
        # against HIGH skills is re-drawn, so an unlucky high draw keeps its
        # luck. Symmetry would cost a second call on every job (measured
        # trigger population: 420 of 3888). The asymmetry is the right one
        # here because the two errors are not equal — a false low is a job
        # that is never seen, a false high is a CV that the review then scores
        # and rejects for the price of generating it.
        persona = _load_persona_summary()
        new_ctx = _ollama_context_score(job_description, persona) if (persona and job_description) else None
        if new_ctx:
            # Keep the new draw's prose: it is the read that actually happened.
            # The score is the mean of both, so text and number describe the
            # same job from different draws — the number is the estimate, the
            # reasoning is one sample of the evidence behind it.
            ctx_match = dict(new_ctx)
            ctx_match["score"] = round((stored_ctx["score"] + new_ctx["score"]) / 2, 2)
            ctx_draws += 1
        else:
            # A failed call is not a draw. Keep what was measured and leave the
            # count alone, so the next run tries again instead of banking a
            # verdict on a call that never returned.
            ctx_match = stored_ctx
    elif isinstance(legacy_ctx, dict) and "score" in legacy_ctx:
        ctx_match = legacy_ctx
    else:
        # Use LLM for context scoring (or TF-IDF fallback)
        persona = _load_persona_summary()
        llm_ctx = None
        attempted_llm = bool(persona and job_description and not skip_llm_context)
        if attempted_llm:
            llm_ctx = _ollama_context_score(job_description, persona)
        if llm_ctx:
            ctx_match = llm_ctx
            ctx_draws = 1
        elif attempted_llm:
            # Tried and failed. TF-IDF is the right answer when the LLM was
            # never asked (skip_llm_context, below) and the wrong one here:
            # measured over the whole database it reads 0.11 median against
            # the LLM's 0.30, so substituting it does not record "we could not
            # tell", it records "this is a poor match" — a claim nothing
            # measured. At 40% of the composite that decides the job's tier,
            # and the score is then REUSED forever by the context_source ==
            # "llm" branch above, so one rate-limited call permanently marks a
            # good posting weak. Roughly one call in five fails.
            #
            # So: score on what was actually measured. The context term drops
            # out and the remaining weights are renormalised, which is why
            # "unscored" is a source in its own right rather than a zero.
            ctx_match = {"score": 0.0, "reasoning": "", "unscored": True}
            ctx_source = "unscored"
            ctx_draws = 0
        else:
            ctx_match = calculate_context_match(job_description)  # never asked
            ctx_source = "tfidf"
            ctx_draws = 0

    # Weighted composite — accept custom weights from config or parameter
    weights = composite_weights(config, override=weights)

    composite = (
        skill_match["score"] * weights["skills"]
        + exp_match["score"] * weights["experience"]
        + loc_match["score"] * weights["location"]
        + sal_match["score"] * weights["salary"]
        + ctx_match["score"] * weights["context"]
    )

    # Context could not be measured — renormalise over the terms that could.
    # Leaving its weight in place would multiply a 0.0 through 40% of the
    # composite and call that a result; dropping the term says the job was
    # scored on four axes instead of five, which is what happened.
    if ctx_source == "unscored":
        live = sum(v for k, v in weights.items() if k != "context")
        composite = (composite / live) if live else 0.0

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

    out = {
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
        # context_score is role_fit — could this candidate do the work. ethos —
        # would they want it — is recorded beside it rather than mixed in: every
        # blend of the two predicted the review outcome worse than role_fit
        # alone, but a job scoring low on fit and high on ethos is exactly the
        # one worth a human look before it is dropped.
        "context_ethos": ctx_match.get("ethos"),
        "context_role_requirement": ctx_match.get("role_requirement"),
        "context_source": ctx_source,
        # How many times this score has actually been drawn. Without it a
        # re-drawn job is indistinguishable from a first-draw one, and the
        # disagreement trigger would pay for the same job every single run.
        "context_draws": ctx_draws,
        # context_source only says "llm" vs "tfidf"; this says which model, so a
        # score produced by a fallback after the primary keys ran out can be told
        # apart from one produced by the intended model and refreshed on its own.
        "context_provider": ctx_match.get("provider"),
        "title_relevance": relevance,
        "weights": weights,
        "summary_en": summary_en,
        "summary_ja": summary_ja,
        "role_affinity": role_aff,
        "detected_role": max(role_aff, key=role_aff.get) if role_aff else "general",
        # Time, not eligibility. See _runway_fit.
        "runway_fit": _runway_fit(analysis.get("contract_months"), config),
    }

    # How far the arrangement travels, and how sure. `inferred` is the normal
    # case and nothing gates on it — see classify_remote_scope.
    scope, scope_confidence = classify_remote_scope(
        job_location, job_work_style, job_country, job.get("description") or ""
    )
    out["remote_scope"] = scope
    out["remote_scope_confidence"] = scope_confidence

    # The strategy layer, kept out of the composite on purpose. strategy.py
    # explains why a fifth weak term is not an improvement on four.
    from strategy import annotate  # local import: keeps matcher importable alone

    out.update(annotate(job, out, config))
    return out


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


_COMPANY_CASING_PATH = Path(
    _os.environ.get("JIS_COMPANY_CASING_PATH")
    or Path(__file__).resolve().parent / "10_output" / "_company_casing.json"
)
_company_casing: dict[str, str] | None = None

# Matching runs several jobs at once, and this registry is read-modify-write over
# one shared dict and one shared temp path. Two threads registering new companies
# together can publish a half-written file, and sorting the dict while another
# thread inserts into it raises outright.
_casing_lock = threading.Lock()


def _load_company_casing() -> dict[str, str]:
    """Registry of the canonical spelling to use for each company.

    Job boards disagree on case for the same employer — Adzuna returns
    "PONTOON", Reed returns "Pontoon" — and each spelling used to produce its
    own set of files. Linux keeps both; macOS cannot, so Syncthing stalls on the
    pair with a "different upper or lowercase characters" error. Pinning one
    spelling per company makes that collision impossible by construction.
    """
    global _company_casing
    if _company_casing is None:
        try:
            import json
            with open(_COMPANY_CASING_PATH, encoding="utf-8") as fh:
                _company_casing = {str(k): str(v) for k, v in json.load(fh).items()}
        except (OSError, ValueError):
            _company_casing = {}
    return _company_casing


def canonical_company(company: str) -> str:
    """Map a company name onto its registered spelling, registering it if new.

    Unknown companies claim their first-seen spelling, so the registry grows on
    its own and existing filenames never move.
    """
    name = (company or "").strip()
    if not name:
        return name
    with _casing_lock:
        registry = _load_company_casing()
        key = name.lower()
        known = registry.get(key)
        if known is not None:
            return known
        registry[key] = name
        try:
            import json
            _COMPANY_CASING_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _COMPANY_CASING_PATH.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(dict(sorted(registry.items())), fh,
                          ensure_ascii=False, indent=2)
            tmp.replace(_COMPANY_CASING_PATH)
        except OSError:
            pass  # in-memory registry still keeps this run consistent
        return name


def make_safe_name(company: str, title: str) -> str:
    """Create a unified safe base name for all generated files (match, CV, CL)."""
    safe_company = re.sub(r'[^\w\s-]', '', canonical_company(company)).strip().replace(' ', '_')[:30]
    safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:50]
    return f"{safe_company}_{safe_title}"


def _tier_short(tier: str) -> str:
    """Extract short tier name without emoji for frontmatter."""
    return tier.replace("🟢 ", "").replace("🟡 ", "").replace("🟠 ", "").replace("🔴 ", "").strip()


_ADZUNA_CODE_COUNTRY = {"gb": "UK", "de": "Germany", "nl": "Netherlands",
                        "fr": "France", "at": "Austria", "es": "Spain",
                        "it": "Italy", "pl": "Poland", "us": "US"}


def _is_summary_only(job: dict) -> bool:
    """True when this job's text is too thin to score or review honestly.

    Mirrored into match-report frontmatter as `scoreable`, because Dataview reads
    the reports and nothing in them said so: a query over 00_matches showed
    "Billing Specialist" and several "Talent Pool" registrations at 0.81-0.83, all
    of them Adzuna API summaries. Those scores are inflated by construction — a
    500-char excerpt is the opening pitch with the requirements cut off — so a
    hand-written query had no way to avoid ranking them above real postings.

    Delegates to selection.is_unscoreable rather than reimplementing part of it.
    It used to test description_truncated alone, which is the Adzuna case only —
    so a posting held out for being too SHORT still reported `scoreable: true`.
    "PODFather — Product Designer" showed match_score 0.79 and scoreable: true
    with a 313-character body reading "This vacancy has now been filled", and no
    CV was generated for it, correctly, with the report giving no hint why. 563
    postings above threshold were in that state.

    The import is local because selection imports filter which imports this
    module; at module scope it is a cycle.
    """
    from selection import is_unscoreable  # local import: avoids a cycle
    return is_unscoreable(job)


def _infer_country(job: dict) -> str:
    """Best-effort country label for match-report frontmatter. Prefers the
    Adzuna country code embedded in source_site ('Adzuna DE'), else infers from
    the location text using the same markers as the location matcher."""
    site = (job.get("source_site") or "").lower()
    m = re.match(r"adzuna\s+([a-z]{2})$", site)
    if m:
        return _ADZUNA_CODE_COUNTRY.get(m.group(1), m.group(1).upper())
    loc = (job.get("location") or "").lower()
    if not loc:
        return ""
    if _UK_RE.search(loc):
        return "UK"
    if _AMERICAS_RE.search(loc) or _US_STATE_ABBR_RE.search(loc):
        return "US"
    if _JAPAN_RE.search(loc):
        return "Japan"
    for country in _remote_target_countries():
        forms = [country] + _COUNTRY_ALIASES.get(country, [])
        if any(f in loc for f in forms):
            return country.title()
    if any(t in loc for t in ("europe", "european", "emea")) or loc.strip() in ("eu", "europe"):
        return "Europe"
    if any(t in loc for t in ("worldwide", "global", "anywhere")):
        return "Worldwide"
    return ""


# Postings in the stretch tier, by URL — never by (company, title), which is not
# unique here. None means "not told yet"; the first lookup then works it out from
# the stored DB. A run that has the jobs in memory should call set_stretch_urls
# instead, because what is on disk mid-run is the previous night's answer.
_STRETCH_URLS: set[str] | None = None


def set_stretch_urls(urls) -> None:
    """Declare which postings the current run promoted into the stretch tier."""
    global _STRETCH_URLS
    _STRETCH_URLS = {u for u in urls if u}


def _is_stretch_job(job: dict) -> bool:
    """Whether this posting got documents despite the level gate.

    Memoised: generate_match_report runs once per posting and the selection is a
    whole-DB scan, so working it out per report would dominate a four-thousand
    report run.
    """
    global _STRETCH_URLS
    if _STRETCH_URLS is None:
        try:
            from selection import stretch_jobs
            _STRETCH_URLS = {j.get("url") for j in stretch_jobs() if j.get("url")}
        except Exception:
            _STRETCH_URLS = set()
    url = job.get("url")
    return bool(url) and url in _STRETCH_URLS


def generate_match_report(job: dict, match: dict, cv_filename: str | None = None, cl_filename: str | None = None,
                          expired: bool = False, applied: bool = False,
                          screening_passed: bool = False, interview_passed: bool = False,
                          carried: list[str] | None = None) -> str:
    """
    Generate a Markdown match report with YAML frontmatter for Obsidian Dataview.
    Optionally include links to generated CV and cover letter files.

    `expired`, `applied`, `screening_passed`, and `interview_passed` are
    hand-maintained flags: a boolean renders as a checkbox in Obsidian's
    property editor, so a closed posting can be ticked off and filtered out of
    a Base, a submitted application can be marked as sent, and each selection
    stage (document screening, interview) can be recorded as it happens. All
    are ALWAYS emitted, false included — an absent key renders no checkbox.

    Nothing here ever sets any of these True; they are passed back in by the
    caller so a tick survives the report being rewritten. All callers must pass
    all flags — see read_flag.

    `carried` is frontmatter written by later steps (PDF and review links, and
    the `*_at` date stamps) that this function has no way to derive;
    save_match_report reads it off the previous report and hands it back for
    the same reason.
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
    # saved_at is when the POSTING was collected; it must not move when the job
    # is re-scored, or the age of the listing becomes unreadable. analyzed_at is
    # the other half of that question — when this report was last written.
    saved_at = scraped_at[:10] if scraped_at else datetime.now().strftime("%Y-%m-%d")
    analyzed_at = datetime.now().strftime("%Y-%m-%d")
    cv_link = f'\ncv: "[[{cv_filename.replace(".md", "")}]]"' if cv_filename else ""
    cl_link = f'\ncover_letter: "[[{cl_filename.replace(".md", "")}]]"' if cl_filename else ""
    carried_yaml = ("\n" + "\n".join(carried)) if carried else ""
    scores = read_review_scores(make_safe_name(company, title))
    review_yaml = "".join(
        f"\n{k}: {str(v).lower() if isinstance(v, bool) else v}" for k, v in scores.items()
    )
    categories = classify_job_categories(title)
    categories_yaml = "[" + ", ".join(categories) + "]" if categories else "[]"
    country = _infer_country(job)

    # Experience level and filtering metadata
    analysis = job.get("analysis", {})
    exp_level = (
        analysis.get("experience_level")
        or job.get("seniority")
        or match.get("experience", {}).get("job_level")
        or "unknown"
    )
    if isinstance(exp_level, str):
        exp_level = exp_level.lower().strip()
    filter_reason = job.get("_filter_reason", "")
    filter_status = "filtered" if filter_reason else "passed"
    filter_yaml = f'\nfilter_status: "{filter_status}"'
    if filter_reason:
        clean_reason = str(filter_reason).replace('"', '\\"')
        filter_yaml += f'\nfilter_reason: "{clean_reason}"'
    # The stretch tier: rejected by the level gate, given documents anyway so the
    # CV review can be read. The rejection is NOT hidden — filter_status stays
    # "filtered" and the reason stays on the report — because a stretch job must
    # never be mistaken for one that passed. This flag says only that the
    # documents exist and the review score is worth looking at.
    if filter_reason and _is_stretch_job(job):
        filter_yaml += "\nstretch: true"

    # The strategy layer, emitted as flat Dataview-sliceable fields. This is the
    # whole payoff of computing it: "show me every tier-2 job whose contract
    # finishes inside the visa and that is remote outside the UK" is a Dataview
    # query over these lines and nothing else.
    #
    # strategic_coverage rides along with strategic_value on purpose. The value
    # is renormalised over whichever terms had data, so 1.00 at coverage 0.30
    # and 1.00 at coverage 1.00 are different claims and the report must not
    # print them identically.
    def _y(value):
        """A YAML scalar, with None as an explicit null rather than an empty
        string — an absent number and a zero must not read the same."""
        if value is None:
            return "null"
        if isinstance(value, str):
            return f'"{value}"'
        return value

    strategy_yaml = "".join([
        f"\naction_tier: {_y(match.get('action_tier'))}",
        f"\nstrategic_value: {_y(match.get('strategic_value'))}",
        f"\nstrategic_coverage: {_y(match.get('strategic_coverage'))}",
        f"\nrole_family: {_y(match.get('role_family'))}",
        f"\nladder_step: {_y(match.get('ladder_step'))}",
        f"\nremote_scope: {_y(match.get('remote_scope'))}",
        f"\nremote_scope_confidence: {_y(match.get('remote_scope_confidence'))}",
        f"\nrunway_fit: {_y(match.get('runway_fit'))}",
        f"\ncontract_kind: {_y(analysis.get('contract_kind'))}",
        f"\ncontract_months: {_y(analysis.get('contract_months'))}",
        f"\nsponsorship: {_y(analysis.get('sponsorship'))}",
    ])

    frontmatter = f"""---
match_score: {score}
match_score_pct: {score_pct}
tier: "{_tier_short(match['tier'])}"
level: "{exp_level}"{filter_yaml}
expired: {"true" if expired else "false"}
applied: {"true" if applied else "false"}
screening_passed: {"true" if screening_passed else "false"}
interview_passed: {"true" if interview_passed else "false"}
company: "{company}"
title: "{title}"
categories: {categories_yaml}
location: "{location}"
country: "{country}"
source: "{source}"
type: "{jtype}"{route_yaml}
saved_at: {saved_at}
analyzed_at: {analyzed_at}
skills_score: {int(match['skills']['score'] * 100)}
experience_score: {int(match['experience']['score'] * 100)}
location_score: {int(match['location']['score'] * 100)}
salary_score: {int(match['salary']['score'] * 100)}
context_score: {int(match.get('context_score', 0) * 100)}{strategy_yaml}
scoreable: {"false" if _is_summary_only(job) else "true"}
url: "{url}"{cv_link}{cl_link}{carried_yaml}{review_yaml}
---"""

    # The sponsorship quote goes in the BODY, never the frontmatter: it is a
    # sentence, and it is the entire justification for the flag above. A reader
    # deciding anything on `sponsorship: refused` has to be able to see what the
    # posting actually said — the system records evidence and does not conclude.
    sponsorship_note = []
    if analysis.get("sponsorship") in ("offered", "refused"):
        _state = analysis["sponsorship"]
        _quote = (analysis.get("sponsorship_evidence") or "").replace("\n", " ")
        _label = "スポンサーシップ提供の記載" if _state == "offered" else "スポンサーシップ不可の記載"
        sponsorship_note = [
            "",
            f"> [!{'tip' if _state == 'offered' else 'warning'}] {_label} / Sponsorship: {_state}",
            f"> {_quote}",
            "> ",
            "> *求人票の記載をそのまま引用したもの。資格の判断ではない。*",
            "> *(Verbatim from the posting. Evidence, not an eligibility verdict — "
            "a YMS holder can take a role that refuses sponsorship.)*",
            "",
        ]

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

    # Why no CV/CL exists, said in the report rather than left to be worked out.
    # A held-out posting still shows a match score — "PODFather — Product
    # Designer" reads 0.79 on a 313-character body that says "This vacancy has
    # now been filled" — and until now the report gave no hint that nothing
    # downstream would ever act on it. The score is real arithmetic over thin
    # evidence, so the honest thing is to print it AND say it is not trusted.
    unscoreable_warning = []
    if not description_missing and _is_summary_only(job):
        desc_len = len((job.get("description") or "").strip())
        if job.get("description_truncated"):
            why = ("求人票がAPIの要約(500字)しか取れておらず、要件部分が切り落とされています。"
                   "/ Only a truncated API summary was captured; the requirements are cut off.")
        else:
            why = (f"求人票の本文が{desc_len}字しかなく、要件を照合できません。"
                   f"/ The body is only {desc_len} characters — too little to check requirements against.")
        unscoreable_warning = [
            f"",
            f"> [!WARNING]",
            f"> **⚠️ CV・カバーレターは生成されません / No CV or cover letter will be generated**",
            f"> {why}",
            f"> スコアは算出されていますが根拠が薄いため、ランキングからも除外されています。"
            f"求人票を取り直せば対象に戻ります。",
            f"> *(Scored, but held out of ranking and generation. Re-scrape the description to admit it.)*",
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
        *unscoreable_warning,
        *sponsorship_note,
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
        ("Role Fit", "context_score"),
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

    # Neither matched nor a gap: the posting named it, and which discipline it
    # meant could not be read. Shown so the term does not simply disappear from
    # a list of the job's own requirements.
    if match["skills"].get("unattributed"):
        lines.append("")
        lines.append("### ⚪ Not scored (ambiguous)")
        for s in match["skills"]["unattributed"][:10]:
            lines.append(f"- {s} — the posting does not say which discipline; "
                         f"counted neither for nor against")

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
    # The heading said "Context & Ethos" over a number that has been role_fit
    # — could this person do the work — since the two-axis prompt landed. Ethos
    # is scored separately and was stored but never shown, so the one case the
    # split exists to surface (low fit, high ethos: worth a human glance before
    # it is dropped) was invisible in the only document a human reads.
    ctx_ethos = match.get("context_ethos")
    ctx_requirement = match.get("context_role_requirement", "")
    lines.extend([
        f"",
        f"## 🧠 Role Fit ({ctx_score*100:.0f}%)",
        f"",
    ])
    if ctx_ethos is not None:
        lines.append(f"- **Could do it (role fit):** {ctx_score*100:.0f}%"
                     f"  |  **Would want it (ethos):** {ctx_ethos*100:.0f}%")
        if ctx_requirement:
            lines.append(f"- **Judged against:** {ctx_requirement}")
        if ctx_ethos - ctx_score >= 0.30:
            lines.append("- ⚠️ Wants it far more than the profile evidences doing it "
                         "— worth reading before dropping.")
        lines.append("")
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


def read_flag(path: Path, key: str) -> bool:
    """Read a hand-set checkbox out of an existing report's frontmatter.

    The report is rewritten wholesale on every rescrape, so without this a tick
    made in Obsidian would be silently reset the next time the job is scored.
    Both checkboxes MUST be read back on every write path — each one used to be
    preserved by only one of the two, so whichever path ran cleared the other's
    tick (run.py's generate_outputs reset `expired`, save_match_report dropped
    `applied`). Passing both through every call is what keeps that closed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    fm = re.match(r"\A---\n(.*?)\n---", text, re.DOTALL)
    if not fm:
        return False
    m = re.search(rf"^{key}:\s*(\S+)", fm.group(1), re.MULTILINE)
    return bool(m) and m.group(1).strip().strip('"').lower() in ("true", "yes", "on")


def read_expired_flag(path: Path) -> bool:
    """True when the report's `expired` checkbox is ticked."""
    return read_flag(path, "expired")


def read_applied_flag(path: Path) -> bool:
    """True when the report's `applied` checkbox is ticked."""
    return read_flag(path, "applied")


def read_screening_passed_flag(path: Path) -> bool:
    """True when the report's `screening_passed` checkbox is ticked."""
    return read_flag(path, "screening_passed")


def read_interview_passed_flag(path: Path) -> bool:
    """True when the report's `interview_passed` checkbox is ticked."""
    return read_flag(path, "interview_passed")


# Properties the report never generates but other steps attach to it later: the
# app links the rendered PDFs and the reviewer's verdicts back onto the report
# so they are reachable (and Dataview-queryable) from there. Rewriting the
# report wholesale used to drop every one of them, so a rescrape silently
# unlinked the reviews that had just been written.
_CARRIED_REPORT_KEYS = ("cv_pdf", "cl_pdf", "cv_review", "cl_review",
                        "applied_at", "screening_passed_at", "interview_passed_at",
                        "screening_failed_at", "interview_failed_at")


def read_review_scores(base: str) -> dict[str, object]:
    """The CV and CL review verdicts for a job, as report frontmatter values.

    Put on the match report so one Obsidian table can show the match score
    beside the review score — a Base queries one folder, and the reports and
    the reviews live in different ones, so the number has to be carried rather
    than joined. The pair is the point: the top of the match ranking is not the
    top of the review ranking (match rank 1 came 66th of 100 by CV review), and
    that only becomes visible when both are in the same row.

    Deliberately NOT in _CARRIED_REPORT_KEYS. A link stays true when the
    document changes; a score does not. These are re-read from the review files
    on every write, and `*_review_current` says whether the review still
    describes the document as it stands — the nightly run regenerates CVs, and
    a stale 86 presented as current is worse than no number at all.
    """
    # Imported here, not at module scope: reviewer imports cv_generator, which
    # imports this module.
    from reviewer import REVIEWS_DIR, review_is_current

    out_root = REVIEWS_DIR.parent
    out: dict[str, object] = {}
    for kind, doc_dir in (("cv", out_root / "10_cvs"), ("cl", out_root / "10_cover-letters")):
        doc = doc_dir / f"{base}_{kind.upper()}.md"
        review = REVIEWS_DIR / f"{base}_{kind.upper()}_review.md"
        if not review.exists():
            continue
        review_text = review.read_text(encoding="utf-8")
        m = re.search(r"^submission_score:\s*(\d+)", review_text, re.MULTILINE)
        if m:
            out[f"{kind}_review_score"] = int(m.group(1))
            out[f"{kind}_review_current"] = review_is_current(doc)[0] if doc.exists() else False
        if kind == "cl":
            out.update(_cl_review_flags(review_text, doc))
    return out


def _cl_review_flags(review_text: str, doc: "Path") -> dict[str, object]:
    """The two CL signals worth carrying onto the match report.

    A cover letter has no submission_score and is not going to get one: ba8fc9c
    narrowed CL review to the one paragraph written for the posting and dropped
    the rubric, because scoring identity paragraphs that are byte-identical in
    every letter measured nothing. So the CL column in the Base was permanently
    blank — not because the column was missing, but because there was no number
    to put in it. These two are what the CL review actually knows:

      cl_fact_block      the reviewer found a fabricated claim in the bridge.
                         The only signal here that can stop a submission.
      cl_opening_source  `assembled` means the bridge was written for this
                         posting; `assembled-static` means the bridge call ran
                         out of providers and the letter shipped with the
                         generic fallback. That failure is invisible — the run
                         exits 0 and the review still passes — and it is worth
                         seeing in the table rather than discovering by opening
                         28 letters one at a time.
    """
    flags: dict[str, object] = {}
    m = re.search(r"^fact_block:\s*(\w+)", review_text, re.MULTILINE)
    if m:
        flags["cl_fact_block"] = m.group(1).strip().lower() == "true"
    if doc.exists():
        m = re.search(r"^opening_source:\s*\"?([\w-]+)", doc.read_text(encoding="utf-8"), re.MULTILINE)
        if m:
            flags["cl_opening_source"] = m.group(1)
    return flags


def read_carried_properties(path: Path) -> list[str]:
    """Frontmatter lines from an existing report that regeneration must keep."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    fm = re.match(r"\A---\n(.*?)\n---", text, re.DOTALL)
    if not fm:
        return []
    kept = []
    for key in _CARRIED_REPORT_KEYS:
        m = re.search(rf"^{key}:.*$", fm.group(1), re.MULTILINE)
        if m:
            kept.append(m.group(0))
    return kept


def save_match_report(job: dict, match: dict, output_dir: str, cv_filename: str | None = None, cl_filename: str | None = None) -> str:
    """
    Save match report as Markdown file.
    Returns the file path.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    base = make_safe_name(job.get("company", "unknown"), job.get("title", "unknown"))
    filename = f"{base}.md"
    filepath = Path(output_dir) / filename

    report = generate_match_report(job, match, cv_filename=cv_filename, cl_filename=cl_filename,
                                   expired=read_expired_flag(filepath),
                                   applied=read_applied_flag(filepath),
                                   screening_passed=read_screening_passed_flag(filepath),
                                   interview_passed=read_interview_passed_flag(filepath),
                                   carried=read_carried_properties(filepath))
    filepath.write_text(report, encoding="utf-8")

    return str(filepath)
