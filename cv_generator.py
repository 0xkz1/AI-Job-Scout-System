# Master CV Template
# ===================
# Source: Merged from Rockstar North (Dev Support) + Paper Tiger (Data Input)
# Generated for automated CV customization per job

MASTER_CV = """Kazuki Yunome
Edinburgh, Scotland, UK (Local Resident) | kazukiyunome@gmail.com | 07787 702187
Portfolio Website: http://kazukiyunome.com/ | GitHub: https://github.com/0xkz1 | LinkedIn: https://www.linkedin.com/in/kazukiyunome/

PROFILE
{profile}

CORE STRENGTHS
{core_strengths}

TECHNICAL TOOLKIT
Systems & Infrastructure
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
Obsidian (structured note-taking, workflow organisation, Zettelkasten-style decomposition)

EXPERIENCE
{experience}

EDUCATION
Hokkai University, Sapporo, Hokkaido | 2013 – 2017
Faculty of Humanities, Department of English and American Culture
Escuela Falcon, Guanajuato, México | 2016 (3 months)
Spanish Language School

ADDITIONAL INFORMATION
• Strong motivation to support development teams by diagnosing technical issues and improving tool and workflow reliability in production environments.
• Actively learning industry-standard tools, including JIRA and production tracking systems.
• Interested in game development pipelines and large-scale creative production.

LANGUAGES
Japanese: Native | English: Professional working proficiency | Spanish: Daily conversation level"""

def load_profile_and_strengths(role_type: str = "general") -> tuple[str, str]:
    """
    Dynamically load profile text and core strengths from:
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
        return "", ""

    try:
        content = profile_path.read_text(encoding="utf-8")
        parts = content.split("---")
        body = parts[-1].strip()
        
        profile_text = ""
        strengths_text = ""
        
        current_section = None
        current_lines = []
        
        for line in body.split("\n"):
            line_stripped = line.strip()
            if line_stripped.startswith("## "):
                if current_section == "profile":
                    profile_text = "\n".join(current_lines).strip()
                elif current_section == "strengths":
                    strengths_text = "\n".join(current_lines).strip()
                
                sec_name = line_stripped[3:].lower()
                if "profile" in sec_name:
                    current_section = "profile"
                elif "strength" in sec_name:
                    current_section = "strengths"
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
            
        return profile_text, strengths_text
    except Exception as e:
        print(f"  ⚠ Error loading profile/strengths for {role_type}: {e}")
        if role_type != "general":
            return load_profile_and_strengths("general")
        return "", ""

def get_profile(role_type: str = "general") -> str:
    """Get profile text for a role type."""
    p, _ = load_profile_and_strengths(role_type)
    return p

def get_strengths(role_type: str = "general") -> str:
    """Get core strengths for a role type."""
    _, s = load_profile_and_strengths(role_type)
    return s

# Role type detection from job title/description
ROLE_KEYWORDS = {
    "development_support": ["development support", "dev support", "tools engineer", "pipeline engineer", "build engineer", "internal tools", "production support", "platform engineer"],
    "data_analysis": ["data entry", "data analyst", "data input", "data quality", "data validation", "data cleaning", "data processing", "spreadsheet", "excel specialist"],
    "creative_technologist": ["creative technologist", "creative tech", "technical creative", "creative developer", "generative ai", "ai artist", "comfyui", "stable diffusion"],
    "technical_artist": ["technical artist", "tech artist", "graph technical artist", "pipeline artist", "vfx artist", "shader artist", "rendering artist"],
    "web_developer": ["web developer", "frontend developer", "backend developer", "full stack", "fullstack", "software engineer", "python developer", "django", "react"],
    "product_designer": ["product designer", "ux designer", "ui designer", "ui/ux", "ux/ui", "user experience designer", "interaction designer", "visual designer", "product design", "design systems", "figma"],
}

def detect_role_type(job_title: str, job_description: str = "") -> str:
    """Detect best role type from job title and description."""
    text = f"{job_title} {job_description}".lower()
    scores = {}
    for role, keywords in ROLE_KEYWORDS.items():
        scores[role] = sum(1 for kw in keywords if kw in text)
    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best
    return "general"

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
                
                description = parts[2].strip()
                
                project = {
                    "id": frontmatter.get("id", fpath.stem),
                    "title": frontmatter.get("title", ""),
                    "role": frontmatter.get("role", ""),
                    "period": frontmatter.get("period", ""),
                    "description": description,
                    "tags": frontmatter.get("tags", []),
                    "skills": frontmatter.get("skills", []),
                }
                projects.append(project)
        except Exception as e:
            print(f"  ⚠ Error loading project file {fpath.name}: {e}")
            
    return projects

PROJECTS = load_projects_from_md()

# ─────────────────────────────────────────────
# Fallback: Static experience per role type
# ─────────────────────────────────────────────
# Used when Ollama is unavailable. Projects filtered by role_tags, order fixed.

STATIC_EXPERIENCE = {
    "web_developer": [
        "portfolio_website",
        "independent_development",
        "linux_systems",
    ],
    "development_support": [
        "independent_development",
        "linux_systems",
        "terra_drone",
    ],
    "data_analysis": [
        "independent_development",
        "terra_drone",
    ],
    "creative_technologist": [
        "feral",
        "arch_viz",
        "hive_floral_pod",
        "portfolio_website",
    ],
    "technical_artist": [
        "feral",
        "arch_viz",
        "hive_floral_pod",
    ],
    "product_designer": [
        "portfolio_website",
        "feral",
        "arch_viz",
        "hive_floral_pod",
    ],
    "general": [
        "portfolio_website",
        "independent_development",
        "linux_systems",
        "terra_drone",
        "feral",
        "arch_viz",
        "hive_floral_pod",
    ],
}


def _format_project_entry(project: dict) -> str:
    """Format a single project dict into a CV Experience entry."""
    return f"{project['title']} | {project['role']} | {project['period']}\n{project['description']}"


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
    """
    Use Ollama LLM to generate a tailored Experience section.
    Returns formatted Experience text, or None on failure.
    """
    if not job_title and not job_description:
        return None

    project_summaries = _build_project_summaries()

    prompt = f"""You are a CV writer for a job applicant. Your task is to select and order the most relevant projects for a specific job posting, then write the EXPERIENCE section of a CV.

JOB DETAILS:
Title: {job_title}
Description (excerpt): {job_description[:2000] if job_description else 'N/A'}
Detected role type: {role_type}

AVAILABLE PROJECTS:
{project_summaries}

INSTRUCTIONS:
1. Select the 3-5 projects MOST RELEVANT to this specific job.
2. Order them by relevance — most relevant first.
3. Format each entry exactly as:
   [Project Title] | [Role] | [Period]
   [Description verbatim from the data above]
4. DO NOT modify project descriptions. Use them exactly as provided.
5. DO NOT add any commentary, headers, or explanations.
6. Separate entries with a single blank line.
7. If the job involves front-end/web development, consider including the Portfolio Website project.
8. If the job involves creative/3D work, prioritize Feral, Arch Viz, and Hive Floral Pod.
9. If the job involves data/automation, prioritize Independent Development.

Write ONLY the Experience section content. No "EXPERIENCE" header."""

    payload = {
        "model": _OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": "You are a professional CV writer. Output ONLY the requested content, no preface or commentary."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "keep_alive": _OLLAMA_KEEP_ALIVE,
        "options": {"temperature": 0.4},
    }

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            resp = _requests.post(
                _OLLAMA_ENDPOINT,
                json=payload,
                timeout=_OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            if content.strip():
                return content.strip()
            return None
        except (_requests.RequestException, _json.JSONDecodeError, KeyError) as e:
            if attempt < max_retries:
                _time.sleep(5)
                continue
            print(f"  ⚠ Ollama CV error (after {max_retries + 1} attempts): {e}")
            return None


def generate_experience(job_title: str = "", job_description: str = "", role_type: str = "general") -> str:
    """
    Generate the Experience section for a CV.
    Tries LLM-based dynamic generation first, falls back to static ordering.
    """
    # Try LLM first (if job description is available)
    if job_description and len(job_description) > 50:
        llm_result = _generate_experience_ollama(job_title, job_description, role_type)
        if llm_result:
            return llm_result

    # Fallback: static experience
    return _get_static_experience(role_type)


def generate_cv(role_type: str = "general", job_title: str = "", company: str = "", job_description: str = "", match_filename: str = "", cl_filename: str = "") -> str:
    """Generate a complete CV for a specific role type and job."""
    profile = get_profile(role_type)
    strengths = get_strengths(role_type)
    experience = generate_experience(job_title, job_description, role_type)
    
    cv_body = MASTER_CV.format(profile=profile, core_strengths=strengths, experience=experience)
    
    frontmatter = f"""---
title: "{company} - {job_title} (CV)"
type: "cv"
company: "{company}"
match_report: "[[{match_filename}]]"
cover_letter: "[[{cl_filename}]]"
---
"""
    
    # Prepend frontmatter and H1
    display_title = f"{company} - {job_title} (CV)" if company and job_title else "Curriculum Vitae"
    return f"{frontmatter}\n# {display_title}\n\n{cv_body}"

if __name__ == "__main__":
    import sys
    role = sys.argv[1] if len(sys.argv) > 1 else "general"
    print(generate_cv(role))