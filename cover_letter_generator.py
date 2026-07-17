# Cover Letter Generator
# ======================
# Generates tailored cover letters based on job description and detected role type

from cv_generator import detect_role_type

MASTER_COVER_LETTER = """{name}
{location} | {email} | {phone}
{date}

Hiring Team
{company}
{job_location}

Dear Hiring Team at {company},

{opening_paragraph}

{experience_paragraph}

{skills_paragraph}

{closing_paragraph}

I would welcome the opportunity to discuss how my background could contribute to your {team_name} team.

Yours sincerely,
{name}"""

def load_cover_template(role_type: str = "general") -> dict:
    """
    Dynamically load cover letter templates from:
    00_Kazuki/career/cover-letter/{role_type}.md
    """
    from pathlib import Path
    import yaml
    
    base_dir = Path(__file__).resolve().parent.parent
    cl_path = base_dir / "cover-letter" / f"{role_type}.md"
    if not cl_path.exists():
        # Fallbacks
        for fallback in [
            f"/media/kz003/atelier/00_Kazuki/career/cover-letter/{role_type}.md",
            f"/home/kz003/atelier/00_Kazuki/career/cover-letter/{role_type}.md"
        ]:
            if Path(fallback).exists():
                cl_path = Path(fallback)
                break
                
    if not cl_path.exists():
        if role_type != "general":
            return load_cover_template("general")
        return {"opening": "", "experience": "", "skills": "", "closing": "", "team_name": ""}

    try:
        content = cl_path.read_text(encoding="utf-8")
        parts = content.split("---")
        
        frontmatter = {}
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
        else:
            body = parts[-1].strip()
            
        team_name = frontmatter.get("team_name", "")
        
        sections = {"opening": "", "experience": "", "skills": "", "closing": "", "team_name": team_name}
        current_section = None
        current_lines = []
        
        for line in body.split("\n"):
            line_stripped = line.strip()
            if line_stripped.startswith("## "):
                if current_section:
                    sections[current_section] = "\n".join(current_lines).strip()
                sec_name = line_stripped[3:].lower()
                if "opening" in sec_name:
                    current_section = "opening"
                elif "experience" in sec_name:
                    current_section = "experience"
                elif "skill" in sec_name:
                    current_section = "skills"
                elif "closing" in sec_name:
                    current_section = "closing"
                else:
                    current_section = None
                current_lines = []
            else:
                if current_section:
                    current_lines.append(line)
                    
        if current_section:
            sections[current_section] = "\n".join(current_lines).strip()
            
        # Clean team_name string if it gets parsed as None
        if sections["team_name"] is None:
            sections["team_name"] = ""
            
        return sections
    except Exception as e:
        print(f"  ⚠ Error loading cover letter template for {role_type}: {e}")
        if role_type != "general":
            return load_cover_template("general")
        return {"opening": "", "experience": "", "skills": "", "closing": "", "team_name": ""}

PERSONAL_INFO = {
    "name": "Kazuki Yunome",
    "location": "Edinburgh, Scotland, UK (Local Resident)",
    "email": "kazukiyunome@gmail.com",
    "phone": "07787 702187",
    "portfolio": "http://kazukiyunome.com/",
    "github": "https://github.com/0xkz1",
    "linkedin": "https://www.linkedin.com/in/kazukiyunome/"
}

from datetime import date


def _generate_opening_hook(job_title: str, company: str, job_description: str) -> str | None:
    """LLM-write a company-specific opening paragraph ("why this company").

    Template cover letters are recognisable at a glance; the one paragraph
    that must feel written-for-this-application is the opening hook. Uses the
    same persona summary as the matcher; returns None on any failure so the
    caller falls back to the template opening. Output must be reviewed by the
    user before sending (opening_source: llm is recorded in the frontmatter).
    """
    if not job_description or len(job_description.strip()) < 200:
        return None
    try:
        from llm_client import call_llm
        from matcher import _load_persona_summary
        persona = _load_persona_summary()
        if not persona:
            return None
        prompt = f"""Write the OPENING paragraph of a cover letter (3-4 sentences, at most 80 words).

THE JOB:
Company: {company}
Title: {job_title}
Posting (excerpt): {job_description[:2000]}

THE CANDIDATE:
{persona[:2500]}

RULES:
- First person, UK English, plain prose. No markdown, no bullet points, no heading.
- Reference something CONCRETE and specific from this posting (their product, mission, tech stack, or the role's actual focus) and connect it to the candidate's real background.
- Do NOT fabricate experience or qualifications not in the candidate profile.
- No clichés ("I was excited to see", "I am writing to apply", "passionate about"), no flattery filler.
- Do not include the greeting line; the letter template already has "Dear Hiring Team".

Output ONLY the paragraph."""
        text = call_llm(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You write concise, specific, honest cover-letter openings. Output only the requested paragraph.",
            temperature=0.5,
            max_tokens=300,
        )
        text = (text or "").strip().strip('"')
        # Sanity gate: single plain paragraph that actually names the company.
        # Use the first word of the company name — models naturally write
        # "Wordsmith's" rather than the full registered name "Wordsmith AI".
        if not (120 <= len(text) <= 1000):
            return None
        if any(m in text for m in ("\n\n", "- ", "• ", "#", "Dear ")):
            return None
        company_word = (company.split()[0].lower() if company and company.split() else "")
        if len(company_word) >= 3 and company_word not in text.lower():
            return None
        return text
    except Exception as e:
        print(f"  ⚠ CL opening hook generation failed ({e}); using template opening")
        return None


def generate_cover_letter(job_title: str, company: str, job_location: str = "Edinburgh", job_description: str = "") -> tuple[str, str]:
    """Generate a tailored cover letter.

    Returns (letter_text, opening_source) where opening_source is "llm" when
    the opening paragraph was written for this specific posting, else
    "template".
    """
    role_type = detect_role_type(job_title, job_description)
    template = load_cover_template(role_type)

    today = date.today().strftime("%d %B %Y")
    team_name = template["team_name"]

    # For general template, use empty team_name
    closing_para = template["closing"].format(company=company, job_title=job_title, job_location=job_location)

    opening = _generate_opening_hook(job_title, company, job_description)
    opening_source = "llm" if opening else "template"
    if not opening:
        opening = template["opening"].format(company=company, job_title=job_title, job_location=job_location)

    letter = MASTER_COVER_LETTER.format(
        name=PERSONAL_INFO["name"],
        location=PERSONAL_INFO["location"],
        email=PERSONAL_INFO["email"],
        phone=PERSONAL_INFO["phone"],
        date=today,
        company=company,
        job_location=job_location,
        job_title=job_title,
        opening_paragraph=opening,
        experience_paragraph=template["experience"],
        skills_paragraph=template["skills"],
        closing_paragraph=closing_para,
        team_name=team_name
    )
    return letter, opening_source

def save_cover_letter(job_title: str, company: str, job_location: str, job_description: str, output_dir: str, match_filename: str = "", cv_filename: str = "") -> str:
    """Generate and save cover letter as Markdown."""
    import os
    import re
    from pathlib import Path
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    role_type = detect_role_type(job_title, job_description)
    
    # Check if template file exists, otherwise it falls back to general
    base_dir = Path(__file__).resolve().parent.parent
    cl_path = base_dir / "cover-letter" / f"{role_type}.md"
    resolved_role = role_type
    exists = cl_path.exists()
    if not exists:
        for fallback in [
            f"/media/kz003/atelier/00_Kazuki/career/cover-letter/{role_type}.md",
            f"/home/kz003/atelier/00_Kazuki/career/cover-letter/{role_type}.md"
        ]:
            if Path(fallback).exists():
                exists = True
                break
    if not exists:
        resolved_role = "general"
        
    letter, opening_source = generate_cover_letter(job_title, company, job_location, job_description)
    
    safe_company = re.sub(r"[^\w\s-]", "", company).strip().replace(" ", "_")[:30]
    safe_title = re.sub(r"[^\w\s-]", "", job_title).strip().replace(" ", "_")[:50]
    filename = f"{safe_company}_{safe_title}_CL.md"
    filepath = Path(output_dir) / filename
    
    frontmatter = f"""---
title: "{company} - {job_title} (Cover Letter)"
type: "cover-letter"
company: "{company}"
match_report: "[[{match_filename}]]"
cv: "[[{cv_filename}]]"
source_template: "[[career/cover-letter/{resolved_role}]]"
opening_source: "{opening_source}"
---
"""
    
    # No big H1 title — it's a letter; it opens with the sender block.
    # The company/role stays in the frontmatter `title:` for Obsidian.
    content = f"{frontmatter}\n{letter}"
    
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        jt = sys.argv[1]
        co = sys.argv[2]
        loc = sys.argv[3] if len(sys.argv) > 3 else "Edinburgh"
        desc = sys.argv[4] if len(sys.argv) > 4 else ""
        print(generate_cover_letter(jt, co, loc, desc)[0])
    else:
        # Demo
        print(generate_cover_letter("Development Support", "Rockstar North", "Edinburgh")[0])