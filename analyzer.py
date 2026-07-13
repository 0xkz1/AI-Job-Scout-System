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
    "no experience", "0-", "1 year", "fresh",
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


def classify_experience_level(title: str, description: str) -> str:
    """
    Classify job as one of: internship, entry_level, mid, senior, director, unknown.
    Checks title first (stronger signal), then falls back to description.
    Returns the level string.
    """
    text = f"{title} {description}".lower()

    # Check title first (stronger signal) — priority order matters
    title_lower = title.lower()

    # 1. Internship (check first — keep intern out of entry-level)
    for kw in INTERNSHIP_KEYWORDS:
        if kw in title_lower:
            return "internship"

    # 2. Director+ (check before senior — e.g. "Senior Director" = director)
    for kw in EXEC_KEYWORDS:
        if kw in title_lower:
            return "director"

    # 3. Senior
    for kw in SENIOR_KEYWORDS:
        if kw in title_lower:
            return "senior"

    # 4. Mid (manager, mid, intermediate)
    for kw in MID_KEYWORDS:
        if kw in title_lower:
            return "mid"

    # 5. Entry
    for kw in ENTRY_KEYWORDS:
        if kw in title_lower:
            return "entry_level"

    # Fallback: check full text (title + description)
    for kw in INTERNSHIP_KEYWORDS:
        if kw in text:
            return "internship"

    for kw in EXEC_KEYWORDS:
        if kw in text:
            return "director"

    for kw in SENIOR_KEYWORDS:
        if kw in text:
            return "senior"

    for kw in MID_KEYWORDS:
        if kw in text:
            return "mid"

    for kw in ENTRY_KEYWORDS:
        if kw in text:
            return "entry_level"

    return "unknown"


# --- Employment type ---

EMPLOYMENT_PATTERNS = {
    "full_time": re.compile(r"full[-\s]?time|permanent", re.IGNORECASE),
    "part_time": re.compile(r"part[-\s]?time", re.IGNORECASE),
    "contract": re.compile(r"contract|fixed[-\s]?term|temporary|ftc|freelance", re.IGNORECASE),
    "internship": re.compile(r"internship|intern|placement|graduate scheme", re.IGNORECASE),
    "freelance": re.compile(r"freelance|self[-\s]?employed|contractor", re.IGNORECASE),
    "apprenticeship": re.compile(r"apprentice|apprenticeship", re.IGNORECASE),
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
            return json.loads(match.group())
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
            return json.loads(match.group())
        except json.JSONDecodeError:
            continue
    return None


def _ollama_chat(messages: list[dict], expect: str = "array") -> list | dict | None:
    """
    Call Ollama /api/chat endpoint.
    expect: "array" for skill extraction (returns list), "object" for classification (returns dict)
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,  # keep model loaded for batch processing
    }

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                OLLAMA_ENDPOINT,
                json=payload,
                timeout=OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            
            if expect == "array":
                return _extract_json_array(content)
            else:
                return _extract_json_object(content)
        except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
            if attempt < max_retries:
                time.sleep(5)  # wait before retry
                continue
            print(f"  ⚠ Ollama error (after {max_retries + 1} attempts): {e}")
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
        # Normalize using SKILL_SYNONYMS
        normalized = []
        for skill in result:
            if isinstance(skill, str):
                normalized.append(normalize_skill(skill))
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
        # Validate values
        valid_exp = {"internship", "entry_level", "mid", "senior", "director", "unknown"}
        valid_style = {"remote", "hybrid", "onsite", "unknown"}
        return {
            "experience_level": exp_level if exp_level in valid_exp else "unknown",
            "work_style": work_style if work_style in valid_style else "unknown",
        }

    return {"experience_level": "unknown", "work_style": "unknown"}


# --- Main analysis ---

def analyze_job(job: dict) -> dict:
    """
    Run all analyzers on a job and return enriched data.
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
    if len(skills) < 3:
        ollama_skills = extract_skills_ollama(title, description)
        if ollama_skills:
            # Merge and deduplicate
            skills = sorted(set(skills + ollama_skills))

    # Classify experience level and work style
    experience_level = classify_experience_level(title, description)
    work_style = classify_work_style(title, description)

    # P1: Ollama fallback for experience_level and work_style
    # If keyword classification returns "unknown", try Ollama
    if experience_level == "unknown" or work_style == "unknown":
        ollama_class = classify_experience_work_style_ollama(title, description)
        if experience_level == "unknown":
            experience_level = ollama_class.get("experience_level", "unknown")
        if work_style == "unknown":
            work_style = ollama_class.get("work_style", "unknown")

    return {
        **job,
        "analysis": {
            "experience_level": experience_level,
            "employment_types": classify_employment_type(combined_text),
            "work_style": work_style,
            "salary": salary_info,
            "skills": skills,
        },
    }
