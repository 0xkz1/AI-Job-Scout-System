# Master CV Template
# ===================
# Source: Merged from Rockstar North (Dev Support) + Paper Tiger (Data Input)
# Generated for automated CV customization per job

import re

DEFAULT_TECHNICAL_TOOLKIT = """Systems & Infrastructure
Linux (Ubuntu), tmux (process monitoring and session management), Docker, custom PC build, system configuration
Workflow & Troubleshooting
Process monitoring, system stability management, debugging under changing external conditions, root cause analysis
Automation & Data
Python, Excel VBA, web scraping, browser automation (Selenium), PostgreSQL, Pandas, NumPy, Heroku, n8n, SQL
Digital Content Tools
Blender (working knowledge), ComfyUI, Stable Diffusion (actively learning), Procreate, Krita, Affinity Suite
AI & Local Tools
Opencode + local LLM (daily use), NotebookLM, local VLM for image tagging
Documentation & Tracking
Obsidian (structured note-taking, workflow organisation, Zettelkasten-style decomposition)"""

# Evidence before claims: employment history right after the profile (the
# thin-employment weakness is countered by structure — a continuous
# 2017→present work timeline), independent work as a named studio practice,
# keyword lists (toolkit) after the evidence, no separate strengths list.
MASTER_CV = """# Kazuki Yunome
**{role_title}**
{role_tagline}
Edinburgh, Scotland, UK | CANDIDATE_EMAIL | CANDIDATE_PHONE
Portfolio Website: http://kazukiyunome.com/ | GitHub: https://github.com/0xkz1 | LinkedIn: https://www.linkedin.com/in/kazukiyunome/

## PROFILE
{profile}

## EXPERIENCE
{employment}

## SELECTED PROJECTS
{experience}

## TECHNICAL TOOLKIT
{technical_toolkit}

## EDUCATION & LANGUAGES
**Hokkai University, Sapporo, Hokkaido | 2013 – 2017** — Faculty of Humanities, Department of English and American Culture
**Escuela Falcon, Guanajuato, México | 2016 (3 months)** — Spanish Language School
**Languages:** Japanese (native) · English (professional working) · Spanish (daily conversation)"""

# Fallback header if a profile is missing role_title/role_tagline in its
# frontmatter — keeps generation working rather than rendering "{role_title}"
# literally into the CV.
_DEFAULT_ROLE_TITLE = "Full-stack Developer & Designer"
_DEFAULT_ROLE_TAGLINE = "Building automated systems for business and creative work with AI/LLM"


def get_header(role_type: str = "general") -> tuple[str, str]:
    """Get (role_title, role_tagline) from a profile's frontmatter, falling
    back to general.md, then to hardcoded defaults."""
    import yaml
    from pathlib import Path

    base_dir = Path(__file__).resolve().parent.parent
    candidates = [
        base_dir / "cv" / "profile" / f"{role_type}.md",
        Path(f"/media/kz003/atelier/00_Kazuki/career/cv/profile/{role_type}.md"),
        Path(f"/home/kz003/atelier/00_Kazuki/career/cv/profile/{role_type}.md"),
    ]
    profile_path = next((p for p in candidates if p.exists()), None)

    if profile_path is None:
        if role_type != "general":
            return get_header("general")
        return _DEFAULT_ROLE_TITLE, _DEFAULT_ROLE_TAGLINE

    try:
        content = profile_path.read_text(encoding="utf-8")
        parts = content.split("---")
        frontmatter = yaml.safe_load(parts[1]) or {} if len(parts) >= 3 else {}
        title = frontmatter.get("role_title")
        tagline = frontmatter.get("role_tagline")
        if title and tagline:
            return title, tagline
    except Exception as e:
        print(f"  ⚠ Error loading header for {role_type}: {e}")

    if role_type != "general":
        return get_header("general")
    return _DEFAULT_ROLE_TITLE, _DEFAULT_ROLE_TAGLINE


def load_profile_and_strengths(role_type: str = "general") -> tuple[str, str, str]:
    """
    Dynamically load profile text, core strengths, and technical toolkit from:
    00_Kazuki/career/cv/profile/{role_type}.md
    """
    from pathlib import Path
    
    # Resolve dynamic paths relative to workspace parent or system mounts
    base_dir = Path(__file__).resolve().parent.parent
    profile_path = base_dir / "cv" / "profile" / f"{role_type}.md"
    if not profile_path.exists():
        # Fallbacks
        for fallback in [
            f"/media/kz003/atelier/00_Kazuki/career/cv/profile/{role_type}.md",
            f"/home/kz003/atelier/00_Kazuki/career/cv/profile/{role_type}.md"
        ]:
            if Path(fallback).exists():
                profile_path = Path(fallback)
                break
                
    if not profile_path.exists():
        if role_type != "general":
            return load_profile_and_strengths("general")
        return "", "", ""

    try:
        content = profile_path.read_text(encoding="utf-8")
        parts = content.split("---")
        body = parts[-1].strip()
        
        profile_text = ""
        strengths_text = ""
        toolkit_text = ""
        
        current_section = None
        current_lines = []
        
        for line in body.split("\n"):
            line_stripped = line.strip()
            if line_stripped.startswith("## "):
                if current_section == "profile":
                    profile_text = "\n".join(current_lines).strip()
                elif current_section == "strengths":
                    strengths_text = "\n".join(current_lines).strip()
                elif current_section == "toolkit":
                    toolkit_text = "\n".join(current_lines).strip()
                
                sec_name = line_stripped[3:].lower()
                if "profile" in sec_name:
                    current_section = "profile"
                elif "strength" in sec_name:
                    current_section = "strengths"
                elif "toolkit" in sec_name or "technical" in sec_name:
                    current_section = "toolkit"
                else:
                    current_section = None
                current_lines = []
            else:
                if current_section:
                    current_lines.append(line)
                    
        if current_section == "profile":
            profile_text = "\n".join(current_lines).strip()
        elif current_section == "strengths":
            strengths_text = "\n".join(current_lines).strip()
        elif current_section == "toolkit":
            toolkit_text = "\n".join(current_lines).strip()
            
        # Convert markdown list markers (- or *) to bullet points (•) to maintain original formatting
        if strengths_text:
            formatted_strengths = []
            for line in strengths_text.split("\n"):
                stripped = line.strip()
                if stripped.startswith("- ") or stripped.startswith("* "):
                    formatted_strengths.append(f"• {stripped[2:]}")
                elif stripped.startswith("• "):
                    formatted_strengths.append(stripped)
                elif stripped:
                    formatted_strengths.append(f"• {stripped}")
            strengths_text = "\n".join(formatted_strengths)
            
        if not toolkit_text:
            toolkit_text = DEFAULT_TECHNICAL_TOOLKIT
            
        return profile_text, strengths_text, toolkit_text
    except Exception as e:
        print(f"  ⚠ Error loading profile/strengths/toolkit for {role_type}: {e}")
        if role_type != "general":
            return load_profile_and_strengths("general")
        return "", "", ""

def get_profile(role_type: str = "general") -> str:
    """Get profile text for a role type."""
    p, _, _ = load_profile_and_strengths(role_type)
    return p

def get_strengths(role_type: str = "general") -> str:
    """Get core strengths for a role type."""
    _, s, _ = load_profile_and_strengths(role_type)
    return s

# Category ordering per role for the unified master toolkit. Every CV shows
# ALL categories (full skill breadth — employers should see everything);
# only the order shifts so the most job-relevant block comes first.
# Categories not listed for a role keep master-file order after the listed ones.
_TOOLKIT_CATEGORY_ORDER = {
    "general":               [],  # master-file order as-is
    "web_developer":         ["Programming & Automation", "Frontend & Product Engineering", "Systems & Infrastructure", "AI Systems & Agents"],
    "product_designer":      ["Design & Visual Production", "Frontend & Product Engineering", "3D & Generative Media", "AI Systems & Agents"],
    "creative_technologist": ["3D & Generative Media", "AI Systems & Agents", "Design & Visual Production", "Programming & Automation"],
    "technical_artist":      ["3D & Generative Media", "Design & Visual Production", "Programming & Automation", "AI Systems & Agents"],
    "data_analysis":         ["Programming & Automation", "AI Systems & Agents", "Systems & Infrastructure"],
    "development_support":   ["Systems & Infrastructure", "Programming & Automation", "AI Systems & Agents"],
}


def _load_master_toolkit() -> list[tuple[str, str]]:
    """Parse skill-toolkit/master.md into [(category, skills_line), ...] preserving order."""
    from pathlib import Path
    base_dir = Path(__file__).resolve().parent.parent
    for cand in [base_dir / "cv" / "skill-toolkit" / "master.md",
                 Path("/media/kz003/atelier/00_Kazuki/career/cv/skill-toolkit/master.md")]:
        if cand.exists():
            body = cand.read_text(encoding="utf-8")
            if "## Technical Toolkit" in body:
                body = body.split("## Technical Toolkit", 1)[1]
            pairs, cat = [], None
            for line in body.split("\n"):
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if cat is None:
                    cat = s
                else:
                    pairs.append((cat, s))
                    cat = None
            if pairs:
                return pairs
    return []


def get_toolkit(role_type: str = "general") -> str:
    """Unified toolkit: ALL categories on every CV, reordered per role type
    (deterministic, no LLM). Falls back to the per-profile toolkit if the
    master file is missing."""
    pairs = _load_master_toolkit()
    if not pairs:
        _, _, t = load_profile_and_strengths(role_type)
        return t
    priority = _TOOLKIT_CATEGORY_ORDER.get(role_type, [])
    ordered = [p for name in priority for p in pairs if p[0] == name]
    ordered += [p for p in pairs if p not in ordered]
    return "\n".join(f"{cat}\n{skills}" for cat, skills in ordered)

# Role type detection from job title/description
ROLE_KEYWORDS = {
    "development_support": ["development support", "dev support", "tools engineer", "pipeline engineer", "build engineer", "internal tools", "production support", "platform engineer"],
    "data_analysis": ["data entry", "data analyst", "data input", "data quality", "data validation", "data cleaning", "data processing", "spreadsheet", "excel specialist"],
    "creative_technologist": ["creative technologist", "creative tech", "technical creative", "creative developer", "generative ai", "ai artist", "comfyui", "stable diffusion"],
    "technical_artist": ["technical artist", "tech artist", "graph technical artist", "pipeline artist", "vfx artist", "shader artist", "rendering artist"],
    "web_developer": ["web developer", "frontend developer", "backend developer", "full stack", "fullstack", "software engineer", "python developer", "django", "react"],
    "product_designer": ["product designer", "ux designer", "ui designer", "ui/ux", "ux/ui", "user experience designer", "interaction designer", "visual designer", "product design", "design systems", "figma", "digital designer", "graphic designer", "brand designer", "creative designer", "web designer", "motion designer"],
    "camera_assistant": ["camera assistant", "photography assistant", "photo assistant", "camera operator", "studio photographer", "photographer", "photography"],
}

def detect_role_type(job_title: str, job_description: str = "") -> str:
    """Detect best role type from job title and description.

    The title names the role; the description only supports it. Weighting them
    equally let a single incidental word in the body outvote the title — a
    "Digital Designer" posting that mentions "product photography" once was
    classified camera_assistant and got a photographer's CV. So a title match is
    worth far more than a body match, and a clear title winner is taken directly.
    """
    title = (job_title or "").lower()
    body = (job_description or "").lower()
    TITLE_WEIGHT = 10  # a title hit outweighs any number of body hits
    scores = {}
    for role, keywords in ROLE_KEYWORDS.items():
        title_hits = sum(1 for kw in keywords if kw in title)
        body_hits = sum(1 for kw in keywords if kw in body)
        scores[role] = TITLE_WEIGHT * title_hits + body_hits
    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best
    return "general"


def role_affinity(job_title: str, job_skills: list[str] | None = None,
                  job_description: str = "") -> dict[str, float]:
    """Keyword affinity of a job to EVERY role profile, aggregated across
    title, extracted skill list, and description. Title hits count double —
    the title is the employer's own one-line statement of the discipline.

    Unlike detect_role_type (winner-take-all, picks ONE CV template), this
    returns the full {role: score} map so callers can reason about
    mixed-signal jobs: one stray data_analysis keyword next to three
    product_designer keywords should read as a design job, not a data job,
    and matcher.py uses the aggregate to decide whether a bare "Design"
    skill is credible.

    Description hits count only 0.5: long postings mention role words in
    passing ("product design" in a tour-operator posting about designing
    travel products, "photographer" in an art-book publisher's boilerplate),
    so a description-only mention must appear as several distinct keywords
    before it outweighs the absence of any title/skill-list evidence."""
    title = (job_title or "").lower()
    skills_blob = " ".join(str(s).lower() for s in (job_skills or []))
    desc = (job_description or "").lower()[:5000]
    aff: dict[str, float] = {}
    for role, keywords in ROLE_KEYWORDS.items():
        score = 0.0
        for kw in keywords:
            if kw in title:
                score += 2.0
            if kw in skills_blob:
                score += 1.0
            if kw in desc:
                score += 0.5
        if score:
            aff[role] = score
    return aff

# ─────────────────────────────────────────────
# Project Registry
# ─────────────────────────────────────────────
# Each project is a structured unit that can be dynamically ordered by the LLM
# based on relevance to a specific job posting.

def load_projects_from_md() -> list[dict]:
    """
    Load CV projects dynamically from 00_Kazuki/career/cv/projects/*.md
    Filters out any projects with 'status: draft' or 'draft: true'.
    """
    import yaml
    from pathlib import Path
    
    projects = []
    for candidate in [
        Path("/home/kz003/atelier/00_Kazuki/career/cv/projects"),
        Path("/media/kz003/atelier/00_Kazuki/career/cv/projects"),
        Path(__file__).resolve().parent.parent / "cv" / "projects",
    ]:
        if candidate.exists():
            cv_projects_dir = candidate
            break
    else:
        return projects
        
    for fpath in sorted(cv_projects_dir.glob("*.md")):
        if fpath.name == "README.md":
            continue
        try:
            content = fpath.read_text(encoding="utf-8")
            parts = content.split("---")
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1]) or {}
                
                status = str(frontmatter.get("status", "")).lower().strip()
                is_draft = frontmatter.get("draft", False) or status == "draft"
                if is_draft:
                    continue  # Skip draft projects
                
                # The body IS the CV entry — but a trailing "## 和訳" section
                # (reference translation for the user) must never reach the CV.
                import re as _re
                description = _re.split(r"\n##\s*和訳", parts[2], maxsplit=1)[0].strip()
                
                project = {
                    "id": frontmatter.get("id", fpath.stem),
                    "title": frontmatter.get("title", ""),
                    "role": frontmatter.get("role", ""),
                    "period": str(frontmatter.get("period", "")),
                    "description": description,
                    "tags": frontmatter.get("tags", []),
                    "skills": frontmatter.get("skills", []),
                    # type: employment entries render in the fixed EXPERIENCE
                    # section; everything else is a selectable project.
                    "type": str(frontmatter.get("type", "project")).lower(),
                    # cover_letter: false keeps a project out of cover-letter
                    # openings while leaving it on the CV — for work that is
                    # real but not yet developed enough to lead a pitch with.
                    "cover_letter": frontmatter.get("cover_letter", True) is not False,
                }
                projects.append(project)
        except Exception as e:
            print(f"  ⚠ Error loading project file {fpath.name}: {e}")
            
    return projects

_MONTH_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _period_end_key(period: str) -> tuple[int, int]:
    """(year, month) of a period's END, for reverse-chronological sorting.
    Plain string sort broke on mixed formats ("Oct 2018 – Apr 2019" sorted
    before "2019 – 2022" because "O" > "2" in ASCII, regardless of actual
    dates) — this parses the last "[Mon] YYYY" occurrence instead.
    "Present"/ongoing sorts as latest. A year with no month (e.g. "2017 –
    2019") defaults to January, not December: treating an unspecified month
    as the LATEST possible reading would let a vague year silently outrank a
    same-year entry that has an explicit, later month — January is the
    conservative default that lets precise dates win same-year ties."""
    if not period:
        return (0, 0)
    if re.search(r"present", period, re.IGNORECASE):
        return (9999, 12)
    matches = list(re.finditer(
        r"(?:(?P<mon>[A-Za-z]{3,9})\s+)?(?P<year>\d{4})", period))
    if not matches:
        return (0, 0)
    m = matches[-1]
    year = int(m.group("year"))
    month = _MONTH_NUM.get((m.group("mon") or "")[:3].lower(), 1)
    return (year, month)


_ALL_ENTRIES = load_projects_from_md()
# Employment history (fixed, always shown, newest first) vs selectable projects
EMPLOYMENT = sorted(
    (p for p in _ALL_ENTRIES if p["type"] == "employment"),
    key=lambda p: _period_end_key(p.get("period", "")), reverse=True,
)
PROJECTS = [p for p in _ALL_ENTRIES if p["type"] != "employment"]


def get_employment_section(role_type: str = "") -> str:
    """Fixed employment/freelance history — never LLM-selected. For a
    portfolio-led CV this is the structural proof of work history; omitting
    the one real employer is the last thing this CV can afford.

    Filtered by tags: an entry with no tags (or an empty list) always shows —
    that's the explicit "relevant to every role" declaration. An entry WITH
    tags only shows when role_type is one of them (e.g. the Real Estate
    Photography internship is tagged [camera_assistant] only, so it must not
    surface in unrelated CVs like Property Underwriter or Family Solicitor)."""
    entries = [p for p in EMPLOYMENT if not p.get("tags") or role_type in p["tags"]]
    return "\n\n".join(_format_project_entry(p) for p in entries)

# ─────────────────────────────────────────────
# Fallback: Static experience per role type
# ─────────────────────────────────────────────
# Used when Ollama is unavailable. Projects filtered by role_tags, order fixed.

# ids must exist in career/cv/projects/*.md (employment entries render in the
# fixed EXPERIENCE section, so they never appear here). Top-5 per role to
# mirror the LLM path's selection size.
STATIC_EXPERIENCE = {
    "web_developer": [
        "taifunome-research-platform",
        "portfolio_website",
        "ai-job-scout-system",
        "hermes-ai-agent-orchestration-system",
    ],
    "development_support": [
        "taifunome-research-platform",
        "ai-job-scout-system",
        "hermes-ai-agent-orchestration-system",
        "ai-asset-tagger-system",
    ],
    "data_analysis": [
        "taifunome-research-platform",
        "ai-asset-tagger-system",
        "ai-job-scout-system",
        "personal-priority-orchestrator",
    ],
    # taifunome-research-platform (platform/engineering) and feral-bestiary-plate-001
    # (the artwork side) are the two halves of the same project — pair them where
    # the role wants both build and craft evidence.
    "creative_technologist": [
        "taifunome-research-platform",
        "feral-bestiary-plate-001",
        "ai-creative-workflow-automation",
        "hive-floral-pod-3d-conceptual-art",
    ],
    "technical_artist": [
        "feral-bestiary-plate-001",
        "hive-floral-pod-3d-conceptual-art",
        "ai-creative-workflow-automation",
        "taifunome-research-platform",
    ],
    # Product/UX roles judge design decisions, not illustration craft — the
    # Bestiary plate is an art series and drops to the "Other projects" line
    # here; it stays top-ranked for technical_artist / creative_technologist.
    # Four, not five: the CV has to land in two A4 pages, and a fifth full
    # write-up pushes it over. The dropped entries still appear on the
    # "Other projects" line, so breadth survives — only depth is rationed.
    "product_designer": [
        "portfolio_website",
        "logo-design-for-myself",
        "taifunome-research-platform",
        "hive-floral-pod-3d-conceptual-art",
    ],
    "general": [
        "ai-job-scout-system",
        "portfolio_website",
        "taifunome-research-platform",
        "feral-bestiary-plate-001",
    ],
}


def _bold_toolkit_headers(toolkit_text: str) -> str:
    """Bold category headers in the Technical Toolkit.

    Structure is "Category\\ncomma,separated,list" pairs. A header is a line
    with no comma immediately followed by a comma-bearing list line — bold it
    so it stands out from the tool list beneath it.
    """
    lines = toolkit_text.split("\n")
    out = []
    for i, line in enumerate(lines):
        s = line.strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        is_header = (
            s
            and not s.startswith("**")
            and "," not in s
            and "," in nxt
        )
        out.append(f"**{s}**" if is_header else line)
    return "\n".join(out)


def _bold_experience_titles(experience_text: str) -> str:
    """Normalise Experience formatting: title lines fully bold, body plain.

    Covers both the static path and the LLM path. Title lines (2+ " | "
    separators) get whole-line bold — the LLM often bolds only the project
    name. Description/bullet lines get their inline bold stripped: skill
    proper-noun bolding (**Python**, **ComfyUI**, …) was deemed noisy.
    """
    out = []
    for line in experience_text.split("\n"):
        s = line.strip()
        is_title = s.count(" | ") >= 2 and not s.startswith(("•", "-", "#"))
        if is_title:
            # drop partial bold + literal [ ] the LLM copies from the prompt's
            # "[Project Title] | [Role] | [Period]" template, then bold the line
            inner = s.replace("**", "").replace("[", "").replace("]", "").strip()
            # the studio name lives in the SELECTED PROJECTS section header —
            # repeating it on every entry line is noise
            inner = inner.replace(" | Taifunomé — Independent Studio", "")
            out.append(f"**{inner}**")
        else:
            out.append(line.replace("**", ""))
    return "\n".join(out)


def _format_project_entry(project: dict) -> str:
    """Format a single project dict into a CV Experience entry (bold header line)."""
    return f"**{project['title']} | {project['role']} | {project['period']}**\n{project['description']}"


def _get_static_experience(role_type: str) -> str:
    """Build Experience section from static ordering (no LLM)."""
    project_ids = STATIC_EXPERIENCE.get(role_type, STATIC_EXPERIENCE["general"])
    project_map = {p["id"]: p for p in PROJECTS}
    entries = []
    for pid in project_ids:
        if pid in project_map:
            entries.append(_format_project_entry(project_map[pid]))
    return "\n\n".join(entries)


# ─────────────────────────────────────────────
# LLM-based Dynamic Experience Generation
# ─────────────────────────────────────────────
# Sends job description + all project summaries to Ollama (gemma4:26b),
# asks it to rank projects by relevance and write the Experience section.

import os as _os
import json as _json
import requests as _requests
import time as _time

_OLLAMA_ENDPOINT = _os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/chat")
_OLLAMA_MODEL = _os.getenv("OLLAMA_MODEL_CV", "gemma-4-26b-a4b-it-gguf")
_OLLAMA_TIMEOUT = int(_os.getenv("OLLAMA_TIMEOUT_CV", "120"))
_OLLAMA_KEEP_ALIVE = _os.getenv("OLLAMA_KEEP_ALIVE", "10m")


def _build_project_summaries() -> str:
    """Build a concise list of all projects for the LLM prompt."""
    lines = []
    for i, p in enumerate(PROJECTS, 1):
        skills_str = ", ".join(p["skills"])
        lines.append(
            f"PROJECT {i}: {p['title']}\n"
            f"  Role: {p['role']} | Period: {p['period']}\n"
            f"  Skills: {skills_str}\n"
            f"  Description: {p['description']}\n"
        )
    return "\n".join(lines)


def _generate_experience_ollama(job_title: str, job_description: str, role_type: str) -> str | None:
    """Use LLM (Mistral→Ollama fallback) to generate a tailored Experience section.
    Returns formatted Experience text, or None on failure.
    """
    if not job_title and not job_description:
        return None

    project_summaries = _build_project_summaries()

    prompt = f"""You are a CV writer for a job applicant. Your task is to select and order the most relevant projects for a specific job posting, then write the SELECTED PROJECTS section of a CV (employment history is a separate, fixed section — do not include it).

JOB DETAILS:
Title: {job_title}
Description (excerpt): {job_description[:2000] if job_description else 'N/A'}
Detected role type: {role_type}

AVAILABLE PROJECTS:
{project_summaries}

INSTRUCTIONS:
1. Select the 4 projects MOST RELEVANT to this specific job — pick the 4 that
   deserve full write-ups (four, not five: the CV has to fit two A4 pages).
   Do NOT list, summarise, or mention the remaining projects in any form
   (no "Additional projects" line) — they are appended automatically by the
   caller.
2. Order them by relevance — most relevant first.
3. Format each entry exactly as:
   [Project Title] | [Role] | [Period]
   [Description verbatim from the data above]
4. DO NOT modify project descriptions. Use them exactly as provided.
5. DO NOT add any commentary, headers, or explanations.
6. Separate entries with a single blank line.
7. If the job involves front-end/web development, consider including the Portfolio Website project.
8. For product / UX / UI / visual-design roles, prioritise Portfolio Website,
   the Identity Mark, Hive Floral Pod, and design-tooling work (Asset Weaver,
   AI Creative Workflow). Rank the illustration series (Feral Bestiary) LOW
   unless the posting explicitly asks for illustration, concept art, or
   narrative art direction — it is an art series, not product design work.
9. For concept-art / illustration / game-art / 3D roles, prioritise Feral
   Bestiary, Arch Viz, and Hive Floral Pod.
10. If the job involves data/automation, prioritize Independent Development.

Write ONLY the Experience section content. No "EXPERIENCE" header.
NEVER open with the job title you are writing for ("{job_title}") or any other
role name on its own line — this section lists the candidate's OWN past
projects, and a bare role name there reads as a job they have held."""

    try:
        from llm_client import call_llm
        content = call_llm(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You are a professional CV writer. Output ONLY the requested content, no preface or commentary.",
            temperature=0.4,
            max_tokens=2048,
            retries=1,
        )
        if content and content.strip():
            return content.strip()
        return None
    except Exception as e:
        print(f"  ⚠ CV experience generation error: {e}")
        return None


def _strip_llm_other_lines(body: str) -> str:
    """Drop any 'Additional/Other projects' line the LLM wrote on its own —
    the canonical one-liner is appended deterministically by the caller, and
    a model-authored variant would make its titles look 'already included'."""
    import re
    kept = [
        l for l in body.split("\n")
        if not re.match(r"\s*[*_]{0,3}\s*(?:Additional|Other)\s+Projects?\b", l, flags=re.IGNORECASE)
    ]
    return "\n".join(kept).strip()


def _other_projects_line(included_text: str) -> str:
    """One-line list of every project NOT given a full write-up, so the CV
    always shows the complete project breadth (employers see everything;
    only the depth of description varies)."""
    rest = [p for p in PROJECTS if p["title"] not in included_text]
    if not rest:
        return ""
    items = " · ".join(f"{p['title']} ({p['period']})" for p in rest)
    return f"**Other projects:** {items}"


def _strip_echoed_job_title(body: str, job_title: str) -> str:
    """Drop a leading line that merely repeats the posting's job title.

    The experience prompt already says "no headers", but the model still liked
    to open the section with the target role in bold, which rendered as:

        EXPERIENCE
        **Performance Creative Designer**
        **AI Creative Workflow Automation** | Independent | 2026

    — i.e. the job being applied FOR read as a position the candidate had
    HELD. A reviewer flagged exactly that as a factual misrepresentation.
    Genuine entries always carry "Title | Role | Period", so a leading line
    with no pipe that normalises to the job title is never a real entry.
    """
    if not job_title:
        return body
    import re

    def _norm(s: str) -> str:
        s = re.sub(r"[*_#`]", "", s)
        return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

    target = _norm(job_title)
    if not target:
        return body
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if "|" in line:
            break  # first real entry reached — nothing was echoed
        if _norm(line) == target:
            return "\n".join(lines[i + 1:]).lstrip("\n")
        break  # only the very first content line can be the echo
    return body


# A fabricated employment block betrays itself two ways: unfilled placeholders
# ("[Company Name]", "[Dates]") the model left for a job it invented, and the
# posting's own duty list pasted in under a "Key Responsibilities" heading as
# though the candidate had performed it. One CV opened its EXPERIENCE section
# with "Artworker | [Company Name] | Stockport | [Dates]" followed by four
# duties lifted verbatim from the advert — sending that is CV fraud, so the
# block is cut rather than trusted.
_PLACEHOLDER_RE = re.compile(
    r"\[(?:company name|dates?|location|your [^\]]{0,20}|insert[^\]]{0,20}|"
    r"employer|job title|position|month|year)[^\]]{0,10}\]",
    re.IGNORECASE,
)
_DUTY_HEADING_RE = re.compile(
    r"^\s*\**\s*(?:key\s+)?(?:responsibilities|duties|requirements|"
    r"what you'?ll do|the role)\s*:?\s*\**\s*$",
    re.IGNORECASE,
)
# The model sometimes addresses ITSELF in the output — "(Note: If actual
# employment history exists, replace the above with …)" — and then helpfully
# supplies a worked example beneath it: an invented Junior Design Engineer post
# complete with SolidWorks, "90% on-time delivery" and "reduced installation
# time by 15%". Read cold, that example is indistinguishable from real history,
# which makes the note the most dangerous artefact of the three.
_META_NOTE_RE = re.compile(
    r"^\s*[*_(]*\s*(?:note|nb)\s*[:：]|"
    r"\b(?:replace the above|if actual (?:employment|work) history|"
    r"example format|placeholder|adjust as needed|fill in your)\b",
    re.IGNORECASE,
)
# Where the model resumes listing the candidate's real portfolio after the
# invented block — everything before this is discarded.
_REAL_WORK_HEADING_RE = re.compile(
    r"^\s*\**\s*(?:relevant experience|selected projects|projects|"
    r"experience)\s*:?\s*\**\s*$",
    re.IGNORECASE,
)


def _strip_fabricated_employment(body: str) -> str:
    """Remove an invented employment entry the model built from the posting.

    Genuine entries come from career/cv/projects and always render as
    "Title | Role | Period" with real values; anything carrying an unfilled
    placeholder, or a duty-list heading copied from the advert, is the model
    writing a job the candidate never held. Cuts from the offending line to
    the next real-work heading (or drops just that block when none follows).
    """
    lines = body.split("\n")
    bad_idx = next(
        (i for i, ln in enumerate(lines)
         if _PLACEHOLDER_RE.search(ln) or _DUTY_HEADING_RE.match(ln)
         or _META_NOTE_RE.search(ln)),
        None,
    )
    if bad_idx is None:
        return body
    # A meta-note is followed by its own invented example, so everything from
    # the note to the end of the section goes — there is no genuine entry after
    # it to preserve. (A stray horizontal rule above it goes too.)
    if _META_NOTE_RE.search(lines[bad_idx]):
        while bad_idx > 0 and (not lines[bad_idx - 1].strip()
                               or set(lines[bad_idx - 1].strip()) <= {"-", "*", "_"}):
            bad_idx -= 1
        return "\n".join(lines[:bad_idx]).strip("\n")

    resume_idx = next(
        (j for j in range(bad_idx + 1, len(lines))
         if _REAL_WORK_HEADING_RE.match(lines[j])),
        None,
    )
    if resume_idx is not None:
        kept = lines[:bad_idx] + lines[resume_idx + 1:]
    else:
        # No resume marker: drop the contiguous block up to the next blank-line
        # separated entry that looks genuine ("Title | Role | Period").
        j = bad_idx + 1
        while j < len(lines) and "|" not in lines[j]:
            j += 1
        kept = lines[:bad_idx] + lines[j:]
    return "\n".join(kept).strip("\n")


def generate_experience(job_title: str = "", job_description: str = "", role_type: str = "general") -> str:
    """
    Generate the Experience section for a CV: top-5 most relevant projects in
    full (LLM-ordered when a description is available, static otherwise) plus
    a compact one-line list of all remaining projects.
    """
    body = None
    if job_description and len(job_description) > 50:
        body = _generate_experience_ollama(job_title, job_description, role_type)
    if not body:
        body = _get_static_experience(role_type)

    body = _strip_llm_other_lines(body)
    body = _strip_echoed_job_title(body, job_title)
    body = _strip_fabricated_employment(body)
    section = _bold_experience_titles(body)
    other = _other_projects_line(body)
    return f"{section}\n\n{other}" if other else section


def generate_cv(role_type: str = "general", job_title: str = "", company: str = "", job_description: str = "", match_filename: str = "", cl_filename: str = "") -> str:
    """Generate a complete CV for a specific role type and job."""
    from pathlib import Path
    base_dir = Path(__file__).resolve().parent.parent
    profile_path = base_dir / "cv" / "profile" / f"{role_type}.md"
    resolved_role = role_type
    
    # Check if the specific role profile exists, otherwise fall back to general
    exists = profile_path.exists()
    if not exists:
        for fallback in [
            f"/media/kz003/atelier/00_Kazuki/career/cv/profile/{role_type}.md",
            f"/home/kz003/atelier/00_Kazuki/career/cv/profile/{role_type}.md"
        ]:
            if Path(fallback).exists():
                exists = True
                break
    if not exists:
        resolved_role = "general"

    profile = get_profile(role_type)
    strengths = get_strengths(role_type)
    toolkit = get_toolkit(role_type)
    experience = generate_experience(job_title, job_description, role_type)
    role_title, role_tagline = get_header(role_type)

    cv_body = MASTER_CV.format(
        role_title=role_title,
        role_tagline=role_tagline,
        profile=profile,
        employment=_bold_experience_titles(get_employment_section(resolved_role)),
        technical_toolkit=_bold_toolkit_headers(toolkit),
        experience=experience
    )
    
    # Scan experience text to determine which projects were used
    used_projects = []
    for p in PROJECTS:
        p_title = p.get("title", "")
        p_id = p.get("id", "")
        if p_title and p_id and p_title.lower().strip() in experience.lower():
            used_projects.append(f"[[career/cv/projects/{p_id}]]")
            
    import json
    source_projects_yaml = f"\nsource_projects: {json.dumps(used_projects, ensure_ascii=False)}" if used_projects else ""
    
    frontmatter = f"""---
title: "{company} - {job_title} (CV)"
type: "cv"
company: "{company}"
match_report: "[[{match_filename}]]"
cover_letter: "[[{cl_filename}]]"
source_profile: "[[career/cv/profile/{resolved_role}]]"{source_projects_yaml}
---
"""
    
    # The CV body now leads with "# Kazuki Yunome" as the H1 — the job/company
    # is kept in the frontmatter `title:` for Obsidian, not as a giant heading.
    return f"{frontmatter}\n{cv_body}"

if __name__ == "__main__":
    import sys
    role = sys.argv[1] if len(sys.argv) > 1 else "general"
    print(generate_cv(role))