"""
Job Analyzer
============
Analyzes scraped job descriptions to extract:
  - Salary range (min/max/currency)
  - Experience level (entry, mid, senior, director)
  - Employment type (full-time, part-time, contract)
  - Required skills
  - Remote/hybrid/onsite classification
"""

import re
from typing import Optional
import json
import requests
import os
import time
from llm_client import call_llm


# --- Salary parsing ---

SALARY_PATTERNS = [
    # "£40,000 - £55,000 per year"
    re.compile(
        r"[£€\$]?\s*([\d,]+)\s*(?:–|-|to)\s*[£€\$]?\s*([\d,]+)\s*(?:per\s*)?(?:year|annum|pa|yr|annual|per\s*annum)",
        re.IGNORECASE,
    ),
    # "£40,000/yr - £55,000/yr"
    re.compile(
        r"[£€\$]?\s*([\d,]+)\s*(?:/|per)\s*(?:yr|year|annum)\s*(?:–|-|to)\s*[£€\$]?\s*([\d,]+)",
        re.IGNORECASE,
    ),
    # "£25 - £35 per hour"
    re.compile(
        r"[£€\$]\s*([\d,.]+)\s*(?:–|-|to)\s*[£€\$]\s*([\d,.]+)\s*per\s*hour",
        re.IGNORECASE,
    ),
    # "Up to £60,000"
    re.compile(r"[Uu]p\s*to\s*[£€\$]\s*([\d,]+)"),
    # "£50,000+"
    re.compile(r"[£€\$]\s*([\d,]+)\s*\+"),
]


def parse_salary(text: str) -> dict:
    """
    Extract salary info from text.
    Returns: {min, max, currency, period, raw}
    """
    result = {"min": None, "max": None, "currency": None, "period": None, "raw": text}

    if not text:
        return result

    for pattern in SALARY_PATTERNS:
        match = pattern.search(text)
        if match:
            groups = match.groups()
            # Determine currency
            currency = "GBP"
            if "€" in text or "EUR" in text:
                currency = "EUR"
            elif "$" in text:
                currency = "USD"

            if "hour" in text.lower():
                period = "hourly"
            else:
                period = "annual"

            if len(groups) >= 2:
                # Range: £40,000 - £55,000
                result["min"] = _clean_number(groups[0])
                result["max"] = _clean_number(groups[1])
            elif "up to" in text.lower():
                result["max"] = _clean_number(groups[0])
            elif "+" in text or "plus" in text.lower():
                result["min"] = _clean_number(groups[0])
            else:
                result["min"] = result["max"] = _clean_number(groups[0])

            result["currency"] = currency
            result["period"] = period
            break

    return result


def _clean_number(s: str) -> float:
    """Convert '40,000' or '40.000' to float."""
    s = s.strip().replace(",", "").replace(" ", "")
    return float(s) if s else None


# --- Experience level ---

# Keywords indicating internship / placement
INTERNSHIP_KEYWORDS = [
    "internship", "intern", "placement", "graduate scheme",
    "industrial year", "year in industry", "work experience year",
]

# Keywords indicating entry-level
ENTRY_KEYWORDS = [
    "entry level", "graduate", "junior", "trainee", "apprentice",
    "no experience", "0-", "1 year", "fresh", "associate",
]

# Keywords indicating mid-level (manager belongs here, NOT exec)
MID_KEYWORDS = [
    "mid", "mid-level", "intermediate", "2 years", "3 years",
    "4 years", "5 years", "experienced", "manager",
]

# Keywords indicating senior
SENIOR_KEYWORDS = [
    "senior", "sr", "lead", "staff", "6 years", "7 years",
    "8 years", "10 years", "principal",
]

# Keywords indicating director/exec (manager excluded — it's mid)
EXEC_KEYWORDS = [
    "director", "head of", "vp", "vice president", "chief", "cto",
    "cfo", "ceo",
]


def _kw_search(kw: str, text: str) -> bool:
    """Keyword match with word boundaries, so 'lead' won't match 'leading',
    'intern' won't match 'international', 'sr' won't match 'srg'.
    Keywords ending in non-alphanumerics (e.g. '0-') keep an open right edge."""
    pattern = re.escape(kw)
    if kw[0].isalnum():
        pattern = r"(?<![a-z0-9])" + pattern
    if kw[-1].isalnum():
        pattern = pattern + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


# A years-of-experience requirement, and the phrases that make one mean
# something else. The title-only rule was right that LEVEL WORDS in prose are
# traps ("work with senior stakeholders"); a number attached to "years" is a
# different kind of signal, but it has its own traps and they are all about
# whose years are being counted.
# Every optional part carries its own leading whitespace. Written with the
# \s* outside them instead — `\d\s*(?:\+)?\s*(?:-)?\s*(\d)?\s*\+?\s*year` —
# four consecutive \s* around optional groups gave the engine many ways to
# split the same run of spaces, and it backtracked through all of them: 116ms
# per posting, ~6 minutes over the corpus, for a regex that should be free.
_YEARS_RX = re.compile(
    r"\b(?P<lo>\d{1,2})(?:\s*\+|\s*plus)?"
    r"(?:\s*(?:[-–—]|to)\s*(?P<hi>\d{1,2})(?:\s*\+)?)?"
    r"\s*years?\b",
    re.IGNORECASE,
)
# The years belong to the company, the manager, the contract, or the visa — not
# to the person being hired. Measured on 400 sampled postings, these are what
# a bare \d+ years regex actually picks up most often.
_YEARS_NOT_A_REQUIREMENT = re.compile(
    r"for (?:over|more than|nearly)\s*\d|\bfounded\b|\byears young\b|\byear foundation\b"
    r"|\bcombined experience\b|\bmentored by\b|\banniversar|\bhistory\b"
    r"|\bfixed[-\s]?term\b|\bftc\b|\bcontract\b|\bresided\b|\bresidency\b|\bvisa\b"
    r"|\bwe have been\b|\bour \d+\b|\btrading\b|\bestablished\b"
    # The years belong to the employer bragging about itself. "manager with 20+
    # years" was caught by name; "backed by a recruitment group with 20 years
    # experience" was not, and read as a 20-year requirement.
    r"|\bbacked by\b|\b(?:group|team|company|business|firm|agency|studio|practice|partner)s?"
    r"\s+with\b|\bmanager with\b"
    # A recency window, not a floor: "must have shipped meaningful design work
    # in the last 2 years" is not asking for two years of experience.
    r"|\b(?:in|over|during|within) the (?:last|past)\b",
    re.IGNORECASE,
)
# What marks the number as a demand on the candidate.
_YEARS_IS_A_REQUIREMENT = re.compile(
    r"\b(?:minimum|min\.?|at least|require|required|requirements|essential|you'?ll need"
    r"|you bring|looking for|ideally bring|must have|proven|demonstrable|track record"
    r"|qualification|experience)\b",
    re.IGNORECASE,
)
# "no more than 2 years" is a ceiling, not a floor — a junior posting saying so
# plainly. Includes the bare comparators because postings write them as markup
# ("Those still early in their careers (&lt;4 years)").
_YEARS_IS_A_CEILING = re.compile(
    r"\bno more than\b|\bup to\b|\bless than\b|\bfewer than\b|\bmaximum\b|\bat most\b"
    r"|\bearly in (?:their|your) career|&lt;\s*\d|<\s*\d|\bunder \d+\s*years?\b",
    re.IGNORECASE,
)


def required_years(description: str) -> tuple[int, bool] | None:
    """Years of experience the posting demands of the candidate, if it says.

    Returns (years, is_ceiling) or None. is_ceiling means the posting caps
    experience ("no more than 2 years of industry experience") rather than
    setting a floor, which is a junior posting stating itself plainly.

    Each candidate match is judged on the window around it, not on the document:
    one posting routinely contains both "6+ years of experience as a graphic
    designer" and "founded ... 40 years of combined experience".
    """
    if not description:
        return None
    text = description[:8000]
    floors, ceilings = [], []
    for m in _YEARS_RX.finditer(text):
        window = text[max(0, m.start() - 90):m.end() + 90]
        if _YEARS_NOT_A_REQUIREMENT.search(window):
            continue
        if not _YEARS_IS_A_REQUIREMENT.search(window):
            continue
        lo = int(m.group("lo"))
        hi = int(m.group("hi")) if m.group("hi") else None
        if lo > 20 or (hi is not None and hi > 25):
            continue
        # The floor is what gates an application: "3-5 years" excludes someone
        # with two, so the range's low end is the number that matters.
        (ceilings if _YEARS_IS_A_CEILING.search(window) else floors).append(lo)
    # A ceiling wins outright. A posting that turns experience away — "Junior
    # Design Engineer: you should have no more than 2 years" — has told you its
    # level, and it will usually also carry ordinary floor phrasing elsewhere
    # that would otherwise outvote it.
    if ceilings:
        return (min(ceilings), True)
    if floors:
        return (max(floors), False)
    return None


def level_from_years(years: int, is_ceiling: bool = False) -> str:
    """Map a stated years requirement to a level band.

    Bands follow the ones matcher.py already scores against ("Job asks for ~mid
    (2+ years)"): under 2 is entry, 2-4 mid, 5 and over senior. A ceiling means
    the posting is turning away experience, which no mid or senior posting does.
    """
    if is_ceiling:
        return "entry_level"
    if years <= 1:
        return "entry_level"
    if years <= 4:
        return "mid"
    return "senior"


def classify_experience_level(title: str, description: str) -> str:
    """
    Classify job as one of: internship, entry_level, mid, senior, director, unknown.

    The title is tried first and still wins when it names a level: an employer
    writing "Senior" in the title is making an explicit claim, and description
    prose is full of trap phrases ("work with senior stakeholders", "leading
    company") that misclassify.

    But the title is not enough on its own, which is what "TITLE ONLY by design"
    missed. Most titles name no level at all — "UX/UI designer" at Bending
    Spoons — and those fell through to an LLM guess that called it mid while the
    posting demanded production ownership and customer testing. Measured across
    the corpus: 17% of postings the title called "mid" pay above the median
    senior salary, and 18% of the 582 postings stating a years figure state one
    outside the band their title-derived level implies.

    So a title with no level word now reads the years the posting asks for
    before falling through to the model — cheaper than the LLM call it replaces,
    and grounded in what the employer wrote rather than what a model inferred.
    """
    title_lower = title.lower()

    # Priority order matters: internship first (keep intern out of entry-level),
    # director before senior (e.g. "Senior Director" = director).
    ordered = [
        ("internship", INTERNSHIP_KEYWORDS),
        ("director", EXEC_KEYWORDS),
        ("senior", SENIOR_KEYWORDS),
        ("mid", MID_KEYWORDS),
        ("entry_level", ENTRY_KEYWORDS),
    ]

    for level, keywords in ordered:
        for kw in keywords:
            if _kw_search(kw, title_lower):
                return level

    # required_years() is NOT consulted here, deliberately. It is as accurate as
    # the LLM classifier it would replace and free — head to head on 60 postings
    # whose title states the level, with the level word stripped out of the
    # title so both estimators see the same thing: years 82%, LLM 77%, 95% CI on
    # the difference [-0.067, +0.183]. Not separable. Against a
    # majority-class baseline it is separable ([+0.023, +0.181] over 171
    # postings), so the extractor works; it just does not beat the model.
    #
    # Equal accuracy would still be worth taking for free, except for what the
    # disagreements cost. Wiring it in reclassifies 85 postings, 39 of them
    # mid -> senior, and include_levels is [entry_level, mid, internship] — so
    # 45 of the 85 stop passing the filter, among them "Creative Technologist
    # (12 Month FTC)", which has already been applied to, and "UI Designer
    # (Design Systems)". Paying 45 postings for a coin-flip accuracy change is
    # the wrong trade, and "5+ years" is boilerplate in UK postings, not a gate
    # the employer enforces.
    #
    # So the years are recorded by analyze_job as evidence and nothing gates on
    # them yet. What that evidence is for is a Level Fit dimension — job level
    # against candidate level, scored as match/stretch/reach — rather than a
    # binary include_levels that deletes a posting for asking for more.
    return "unknown"


# --- Employment type ---

# Word boundaries required: without them "intern" matches "international",
# "contract" matches "contractual obligations" is fine but "ftc" matches inside words.
EMPLOYMENT_PATTERNS = {
    "full_time": re.compile(r"\bfull[-\s]?time\b|\bpermanent\b", re.IGNORECASE),
    "part_time": re.compile(r"\bpart[-\s]?time\b", re.IGNORECASE),
    "contract": re.compile(r"\bcontract\b|\bfixed[-\s]?term\b|\btemporary\b|\bftc\b|\bfreelance\b", re.IGNORECASE),
    "internship": re.compile(r"\binternship\b|\bintern\b|\bplacement\b|\bgraduate scheme\b", re.IGNORECASE),
    "freelance": re.compile(r"\bfreelance\b|\bself[-\s]?employed\b|\bcontractor\b", re.IGNORECASE),
    "apprenticeship": re.compile(r"\bapprentice(ship)?\b", re.IGNORECASE),
}


def classify_employment_type(text: str) -> list[str]:
    """Return list of employment types found in text (title + description)."""
    found = []
    for etype, pattern in EMPLOYMENT_PATTERNS.items():
        if pattern.search(text):
            found.append(etype)
    return found if found else ["unknown"]


# --- Work style ---

WORK_STYLE_PATTERNS = {
    "remote": re.compile(
        r"remote|work from home|wfh|fully remote|100%\s*remote|home[-\s]?based|distributed",
        re.IGNORECASE,
    ),
    "hybrid": re.compile(
        r"hybrid|mix of home|office.*home|home.*office|flexible working|partial remote",
        re.IGNORECASE,
    ),
    "onsite": re.compile(
        r"on[-\s]?site|in[-\s]?office|office[-\s]?based|on location|office only",
        re.IGNORECASE,
    ),
}


def classify_work_style(title: str, description: str) -> str:
    """Classify as remote, hybrid, onsite, or unknown."""
    text = f"{title} {description}".lower()

    for style, pattern in WORK_STYLE_PATTERNS.items():
        if pattern.search(text):
            return style

    return "unknown"


# --- Skill extraction ---

# Comprehensive skill keyword list
SKILL_KEYWORDS = [
    # Programming Languages
    "python", "javascript", "typescript", "java", "c#", "c++", "rust", "go",
    "golang", "ruby", "php", "swift", "kotlin", "scala", "r", "matlab",
    "html", "css", "scss", "sass", "less",
    # Frameworks & Libraries
    "react", "node", "node.js", "vue", "angular", "svelte", "next.js", "nuxt",
    "django", "flask", "fastapi", "spring", "express", "nestjs", "laravel",
    "rails", ".net", "asp.net", "blazor",
    # Databases
    "sql", "postgresql", "postgres", "mysql", "mongodb", "redis", "sqlite",
    "cassandra", "dynamodb", "elasticsearch", "neo4j", "snowflake", "bigquery",
    # Cloud & DevOps
    "docker", "kubernetes", "k8s", "aws", "azure", "gcp", "google cloud",
    "git", "github", "gitlab", "bitbucket", "ci/cd", "jenkins", "terraform",
    "ansible", "circleci", "travis", "github actions", "gitlab ci",
    "argocd", "flux", "helm", "prometheus", "grafana", "datadog",
    # APIs & Architecture
    "rest api", "graphql", "grpc", "api integration", "microservices",
    "serverless", "event-driven", "message queue", "kafka", "rabbitmq",
    # AI & Data
    "machine learning", "ml", "deep learning", "llm", "generative ai",
    "stable diffusion", "comfyui", "langchain", "llamaindex",
    "pandas", "numpy", "jupyter", "tensorflow", "pytorch", "keras",
    "scikit-learn", "sklearn", "huggingface", "transformers", "openai",
    "data analysis", "data pipeline", "etl", "airflow", "dbt", "spark",
    "hadoop", "kafka", "databricks", "mlops", "feature store",
    # Creative & Design
    "blender", "unity", "unreal engine", "unreal", "3d modeling", "3d",
    "photoshop", "illustrator", "figma", "adobe creative suite",
    "affinity", "affinity suite", "affinity photo", "affinity designer",
    "procreate", "krita", "sketch", "adobe xd", "framer",
    "photography", "video editing", "motion graphics", "after effects",
    "premiere", "davinci resolve",
    "ui/ux", "ui design", "ux design", "user research", "usability testing",
    "wireframing", "prototyping", "design systems", "accessibility",
    # Game Dev
    "game development", "game design", "level design",
    "technical artist", "shader", "material", "vfx", "particle",
    "environment art", "character art", "rigging", "animation",
    "gameplay programming", "engine programming", "tools programming",
    # Systems & IT
    "linux", "ubuntu", "unix", "bash", "shell", "zsh", "powershell",
    "devops", "sysadmin", "it support", "technical support",
    "monitoring", "grafana", "tmux", "vim", "vscode", "intellij",
    "jira", "confluence", "notion", "agile", "scrum", "kanban",
    "jira workflow", "confluence documentation",
    # Automation & Workflow
    "n8n", "workflow", "automation", "obsidian", "zapier", "make",
    "web scraping", "browser automation", "selenium", "playwright",
    "puppeteer", "beautifulsoup", "scrapy", "requests",
    "excel", "vba", "spreadsheet", "google sheets", "power bi",
    "tableau", "looker", "metabase",
    # AI Local Tools
    "local llm", "opencode", "notebooklm", "vlm", "image tagging",
    "ollama", "llama.cpp", "vllm", "text-generation-webui",
    # Soft Skills
    "communication", "teamwork", "problem solving", "problem-solving",
    "documentation", "troubleshooting", "leadership", "mentoring",
    "code review", "agile methodologies", "project management",
    # Testing
    "unit testing", "integration testing", "e2e testing", "tdd", "bdd",
    "jest", "pytest", "cypress", "playwright test", "selenium test",
    # Security
    "cybersecurity", "application security", "penetration testing",
    "owasp", "authentication", "authorization", "oauth", "jwt",
    # Mobile
    "ios", "android", "flutter", "react native", "swift", "kotlin",
    "xcode", "android studio",
    # Embedded/IoT
    "embedded", "firmware", "rtos", "arduino", "raspberry pi",
    "esp32", "stm32", "c++", "c#", "c embedded",
    # NOTE: bare "c" removed — matches any word containing 'c'
    # Education & Research
    "teaching", "training", "curriculum", "pedagogy",
    "assessment", "marking", "grading",
    "lecturer", "tutor", "instructor", "researcher",
    "phd", "postdoc",
    # NOTE: "lab" removed — matches "collaborative", "elaborate" etc.
    # NOTE: "hr" removed — matches "their", "here" etc.
    # Creative & Media — specific and broad terms (design/creative are valid)
    "creative", "design", "designer", "artist", "visual",
    # NOTE: "art" kept but borderline — matches "part", "start"; fine as long as
    # synonym mapping routes it to a skill users actually have in skills.md
    "photography", "videography", "video editing", "motion graphics",
    "illustration", "graphic design", "branding",
    "typography", "web design",
    "ui design", "ux design", "ui/ux design", "user research", "usability testing",
    "wireframing", "prototyping", "design systems", "figma", "sketch", "adobe xd",
    "photoshop", "illustrator", "indesign", "after effects",
    "premiere", "davinci resolve", "blender", "maya", "cinema 4d",
    "3d modeling", "3d animation", "vfx", "compositing",
    "game art", "concept art", "character design", "environment art",
    "technical artist", "rigging", "shader", "material",
    # Marketing & Content
    "marketing", "copywriting", "seo", "sem",
    "social media", "email marketing", "paid social", "ppc",
    "google analytics", "ga4", "tag manager",
    "crm", "hubspot", "salesforce",
    # Business & Management
    "project management", "program management", "product management",
    "agile", "scrum", "kanban", "jira", "confluence",
    "stakeholder management", "roadmap",
    "risk management", "change management",
    # Science & Engineering
    "mechanical engineering", "electrical engineering", "civil engineering",
    "cad", "solidworks", "autocad", "catia", "ansys",
    "fea", "cfd", "pcb",
    # Healthcare & Life Sciences
    "clinical research", "pharmaceutical", "biotech", "genomics",
    "gmp", "glp",
    # Finance & Legal
    "financial modeling", "excel", "vba", "power bi", "tableau", "sql",
    "compliance", "gdpr",
    # NOTE: bare "legal", "hr", "lab" removed — too generic, match domain context
    # Other Professional
    "operations management", "logistics", "supply chain", "procurement",
    "human resources", "recruitment", "talent acquisition",
]


# Skill synonyms for normalization (e.g., "ML" -> "Machine Learning")
SKILL_SYNONYMS = {
    "ml": "Machine Learning",
    "ai": "Artificial Intelligence",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "postgres": "PostgreSQL",
    "react.js": "React",
    "vue.js": "Vue",
    "nodejs": "Node.js",
    "golang": "Go",
    "js": "JavaScript",
    "ts": "TypeScript",
    "ci cd": "CI/CD",
    "cicd": "CI/CD",
    "ci/cd": "CI/CD",
    "rest": "REST API",
    "graphql": "GraphQL",
    "llm": "Large Language Models",
    "gen ai": "Generative AI",
    "genai": "Generative AI",
    "mlops": "MLOps",
    "etl": "ETL",
    "ui ux": "UI/UX",
    "ui/ux": "UI/UX",
    "devops": "DevOps",
    "sre": "Site Reliability Engineering",
    "oss": "Open Source",
    "api": "API Integration",
    "sql": "SQL",
    "nosql": "NoSQL",
    "faq": "FAQ",
    "ci": "Continuous Integration",
    "cd": "Continuous Deployment",
    # Creative & Design synonyms
    "3d": "3D Modeling",
    "vfx": "VFX",
    "ui": "UI Design",
    "ux": "UX Design",
    "motion": "Motion Graphics",
    "ae": "After Effects",
    "pr": "Premiere Pro",
    "ps": "Photoshop",
    "ai": "Illustrator",
    "id": "InDesign",
    "figma": "Figma",
    "sketch": "Sketch",
    "xd": "Adobe XD",
    "blender": "Blender",
    "unity": "Unity",
    "unreal": "Unreal Engine",
    # Game Dev synonyms
    "tech art": "Technical Artist",
    "gameplay": "Gameplay Programming",
    "engine": "Engine Programming",
    "rigging": "Rigging",
    "animation": "Animation",
    "environment": "Environment Art",
    "character": "Character Art",
    "shader": "Shader Programming",
    # Education/Creative synonyms
    "teaching": "Teaching",
    "training": "Training",
    "examiner": "Examination",
    "moderator": "Moderation",
    "assessment": "Assessment",
    "curriculum": "Curriculum Design",
    "pedagogy": "Pedagogy",
    "technician": "Technical Support",
    "specialist": "Specialist",
    "cosmetic": "Cosmetic Science",
}


# Common job-extracted "skills" that are too generic / ambiguous to be meaningful.
NON_SKILL_FILTER: set[str] = {
    # Short ambiguous words — match non-skill usage
    "make", "less",
    # Soft skills / generic attributes
    "problem solving", "creative", "innovation", "innovative",
    "interpersonal", "communication", "teamwork", "leadership",
    "time management", "critical thinking", "analytical",
    "analytical skills", "attention to detail", "problem solver",
    "proactive", "self motivated", "self-starter", "fast learner",
    "adaptability", "flexible", "multitasking", "multitask",
    "organizational", "organized", "planning", "prioritization",
    "customer service", "presentation", "presentation skills",
    "negotiation", "mentoring",
    # Broad industry terms
    "marketing", "sales", "administration", "management",
    "operations", "strategy", "business development",
    # Generic nouns an LLM sometimes hallucinates as "skills" from a job
    # title or misextracted description (e.g. a scraper bug that captured
    # a university's "About Us" boilerplate instead of the actual posting)
    "college", "coordinator", "experiment", "university", "department",
}


def _is_non_skill(skill_name: str) -> bool:
    """Check if a skill name is in the non-skill filter (case-insensitive)."""
    return skill_name.lower().strip() in NON_SKILL_FILTER


def _appears_capitalized(text: str, term: str) -> bool:
    """Check if a term appears with uppercase first letter in original text.
    
    Concrete skills (Python, React, Agile) are typically capitalized in job 
    descriptions, while generic words (make, less) usually stay lowercase.
    """
    import re
    if not term or not term[0].isalpha():
        return True  # Non-alpha starts can't be checked this way
    capitalized = term[0].upper() + term[1:]
    pattern = re.escape(capitalized)
    if capitalized[0].isalnum():
        pattern = r'(?<![a-zA-Z0-9_])' + pattern
    if capitalized[-1].isalnum() or capitalized[-1] == '_':
        pattern = pattern + r'(?![a-zA-Z0-9_])'
    return bool(re.search(pattern, text))


def normalize_skill(skill: str) -> str:
    """Normalize skill name using synonyms map."""
    skill_lower = skill.lower().strip()
    return SKILL_SYNONYMS.get(skill_lower, skill.title())


_SKILL_REGEX_CACHE = {}

def extract_skills(text: str) -> list[str]:
    """Find mentioned skills in text (title, snippet, description, etc.) using boundary checks."""
    if not text:
        return []
    import re
    text_lower = text.lower()
    found = set()
    for skill in SKILL_KEYWORDS:
        if skill not in _SKILL_REGEX_CACHE:
            pattern = re.escape(skill)
            if skill[0].isalnum() or skill[0] == '_':
                pattern = r'(?<![a-zA-Z0-9_])' + pattern
            if skill[-1].isalnum() or skill[-1] == '_':
                pattern = pattern + r'(?![a-zA-Z0-9_])'
            _SKILL_REGEX_CACHE[skill] = re.compile(pattern)
        
        if _SKILL_REGEX_CACHE[skill].search(text_lower):
            if not _is_non_skill(skill) and _appears_capitalized(text, skill):
                found.add(normalize_skill(skill))
    return sorted(found)


def extract_skills_from_title(title: str) -> list[str]:
    """Extract skills specifically from job title (e.g., 'Python Developer', 'AWS Engineer')."""
    return extract_skills(title)


# --- Ollama Integration ---
# Local LLM for skill extraction and classification (gemma4:12b / qwen35-9b-tools)
OLLAMA_ENDPOINT = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma-4-26b-a4b-it-gguf")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))  # seconds - model loading can take 10-15s
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "10m")  # keep model loaded for batch processing


def _extract_json_array(text: str) -> list | None:
    """Extract the last valid JSON array from text (handles thinking tokens)."""
    import re
    # Find all JSON array patterns [...]
    matches = list(re.finditer(r'\[.*?\]', text, re.DOTALL))
    for match in reversed(matches):
        try:
            return json.loads(match.group(), strict=False)
        except json.JSONDecodeError:
            continue
    return None


def _extract_json_object(text: str) -> dict | None:
    """Extract the last valid JSON object from text (handles thinking tokens)."""
    import re
    # Find all JSON object patterns {...}
    matches = list(re.finditer(r'\{.*?\}', text, re.DOTALL))
    for match in reversed(matches):
        try:
            return json.loads(match.group(), strict=False)
        except json.JSONDecodeError:
            continue
    return None


def _ollama_chat(messages: list[dict], expect: str = "array") -> list | dict | None:
    """
    Call LLM for extraction/classification.
    Uses provider from env ANALYSIS_PROVIDER (ollama/mistral/openrouter).
    expect: "array" for skill extraction (returns list), "object" for classification (returns dict)
    """
    # Extract system prompt if present
    system_prompt = ""
    chat_messages = []
    for m in messages:
        if m.get("role") == "system":
            system_prompt = m.get("content", "")
        else:
            chat_messages.append(m)

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            content = call_llm(
                messages=chat_messages,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=2048,
                retries=0,  # we handle retries in this wrapper
            )

            if expect == "array":
                return _extract_json_array(content)
            else:
                return _extract_json_object(content)
        except Exception as e:
            if attempt < max_retries:
                time.sleep(5)
                continue
            print(f"  ⚠ LLM error (after {max_retries + 1} attempts): {e}")
            return None


def extract_skills_ollama(title: str, description: str) -> list[str]:
    """
    Extract skills from job title + description using local Ollama LLM.
    Fallback for when keyword extraction yields < 3 skills.
    """
    if not title and not description:
        return []

    # Use title + snippet (description), or just title if snippet empty
    text = f"Job title: {title}\nJob description: {description}" if description.strip() else f"Job title: {title}"

    prompt = f"""Extract ONLY concrete, specific skills from the following job posting.
Skills must be: programming languages, frameworks, tools, software, platforms, or specific methodologies.
DO NOT include: job titles, company names, industry domains (e.g. 'legal', 'finance'), generic adjectives (e.g. 'fast', 'self-sufficient'), or single letters.
Return ONLY a JSON array of skill names, nothing else.
Example: ["Python", "Docker", "AWS", "TypeScript", "React", "Figma", "Design Systems"]

{text}"""

    result = _ollama_chat([
        {"role": "system", "content": "You are a skill extraction engine. Output ONLY a JSON array."},
        {"role": "user", "content": prompt}
    ], expect="array")

    if isinstance(result, list):
        # Normalize using SKILL_SYNONYMS and filter non-skills
        normalized = []
        for skill in result:
            if isinstance(skill, str):
                skill_norm = normalize_skill(skill)
                if not _is_non_skill(skill_norm):
                    normalized.append(skill_norm)
        return sorted(set(normalized))

    return []


def classify_experience_work_style_ollama(title: str, description: str) -> dict:
    """
    Classify experience_level and work_style using local Ollama LLM.
    Returns: {"experience_level": "...", "work_style": "..."}
    Falls back to keyword-based classification on error.
    """
    if not title and not description:
        return {"experience_level": "unknown", "work_style": "unknown"}

    text = f"Job title: {title}\nJob description: {description}" if description.strip() else f"Job title: {title}"

    prompt = f"""Classify this job's experience level and work style.
Return JSON: {{"experience_level": "internship|entry_level|mid|senior|director", "work_style": "remote|hybrid|onsite"}}

{text}"""

    result = _ollama_chat([
        {"role": "system", "content": "You are a job classification engine. Output ONLY the specified JSON."},
        {"role": "user", "content": prompt}
    ], expect="object")

    if isinstance(result, dict):
        exp_level = result.get("experience_level", "unknown")
        work_style = result.get("work_style", "unknown")
        # The model occasionally answers with a list instead of a string (e.g.
        # ["mid"] or ["mid", "senior"]) — a plausible formatting slip, not junk,
        # so the first element is worth keeping rather than discarding the
        # whole answer. `x in a_set` raises TypeError for any other unhashable
        # value (a nested dict, for instance), which crashed this job's
        # enrichment outright rather than falling back to "unknown".
        if isinstance(exp_level, list) and exp_level:
            exp_level = exp_level[0]
        if isinstance(work_style, list) and work_style:
            work_style = work_style[0]
        # Validate values
        valid_exp = {"internship", "entry_level", "mid", "senior", "director", "unknown"}
        valid_style = {"remote", "hybrid", "onsite", "unknown"}
        return {
            "experience_level": exp_level if isinstance(exp_level, str) and exp_level in valid_exp else "unknown",
            "work_style": work_style if isinstance(work_style, str) and work_style in valid_style else "unknown",
        }

    return {"experience_level": "unknown", "work_style": "unknown"}


# --- Main analysis ---

def analyze_job(job: dict, skip_llm: bool = False) -> dict:
    """
    Run all analyzers on a job and return enriched data.

    skip_llm=True stops before the two LLM top-ups (skill extraction when the
    keyword pass finds <3, and experience/work-style when the rules return
    "unknown"). Everything the filter reads — salary, experience_level,
    employment_types, work_style — still gets computed, because all of it comes
    from regex and rules; only the *quality* of those fields degrades.

    That split exists so filtering can run BEFORE the expensive calls. The
    pipeline used to analyse every scraped job, then filter, so 35% of the LLM
    spend went to postings dropped moments later on a title keyword. Run the cheap
    pass, filter, then re-run without skip_llm on what survived: analyze_job is
    idempotent, and re-analysing a filtered-in job costs only the LLM top-ups it
    actually needs.
    """
    title = job.get("title", "")
    description = job.get("description", "") or job.get("snippet", "")
    salary_text = job.get("salary", "")

    # Combine all available text for analysis
    # When description/snippet is empty, title is the only source
    combined_text = f"{title} {description} {salary_text}".strip()

    salary_info = parse_salary(salary_text)

    # Also try to find salary in description
    if not salary_info.get("min") and not salary_info.get("max"):
        desc_salary = parse_salary(description)
        if desc_salary.get("min") or desc_salary.get("max"):
            salary_info = desc_salary

    # Extract skills from all available text (title + description + salary)
    # If description is empty, extract from title specifically
    if description.strip():
        skills = extract_skills(combined_text)
    else:
        skills = extract_skills_from_title(title)

    # P0: Ollama fallback for skill extraction
    # If keyword extraction yields < 3 skills, try Ollama
    if len(skills) < 3 and not skip_llm:
        ollama_skills = extract_skills_ollama(title, description)
        if ollama_skills:
            # Merge and deduplicate
            skills = sorted(set(skills + ollama_skills))

    # Classify experience level and work style
    experience_level = classify_experience_level(title, description)
    work_style = classify_work_style(title, description)

    # P1: Ollama fallback for experience_level and work_style
    # If keyword classification returns "unknown", try Ollama
    if (experience_level == "unknown" or work_style == "unknown") and not skip_llm:
        ollama_class = classify_experience_work_style_ollama(title, description)
        if experience_level == "unknown":
            experience_level = ollama_class.get("experience_level", "unknown")
        if work_style == "unknown":
            work_style = ollama_class.get("work_style", "unknown")

    # Recorded, not acted on — see the note in classify_experience_level.
    # (years, is_ceiling) or None; is_ceiling means the posting caps experience
    # rather than requiring it, which only a junior posting does.
    stated_years = required_years(description)

    return {
        **job,
        "analysis": {
            "experience_level": experience_level,
            "required_years": stated_years[0] if stated_years else None,
            "required_years_is_ceiling": bool(stated_years[1]) if stated_years else None,
            "employment_types": classify_employment_type(combined_text),
            "work_style": work_style,
            "salary": salary_info,
            "skills": skills,
        },
    }
