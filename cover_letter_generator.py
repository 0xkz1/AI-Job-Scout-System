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

COVER_TEMPLATES = {
    "development_support": {
        "opening": "I had been aware of {company}\'s work prior to relocating to Edinburgh. While my initial interest was from a creative perspective, my hands-on experience over time has led me to focus on technical problem-solving and workflow support, which more accurately reflects where I am most effective. I am particularly drawn to diagnosing system failures, understanding where data flows break down, and restoring stability through iterative troubleshooting.",
        "experience": "Over the past several years, I have built and maintained automated systems independently, including data processing and workflow pipelines using Python, VBA, PostgreSQL, and browser automation tools. These systems required continuous debugging and adaptation in response to external changes such as API and platform constraints, with a focus on maintaining stability over time. A key part of this work has been diagnosing how issues occur and reproducing system failures in order to identify root causes through iterative troubleshooting, particularly under changing external conditions such as API and platform constraints.",
        "skills": "At Terra Drone, I worked between engineering and business teams, working with existing technical materials and applying them to real operational contexts. This experience involved understanding technical systems and translating them into usable outcomes across different teams. More recently, I have been working with structured workflows in Linux-based environments and creative tools such as Blender and ComfyUI, exploring how different tools interact within structured systems and how technical issues can be identified and resolved across them.",
        "closing": "I am particularly interested in roles where I can support internal development teams by diagnosing tool issues, resolving workflow failures, and helping maintain stable production pipelines used by artists and engineers.",
        "team_name": "Tools"
    },
    "data_analysis": {
        "opening": "I am writing to apply for the {job_title} role at {company} in {job_location}. I am a local resident with hands-on experience in automation, data cleaning, and AI-assisted image organisation. I am particularly interested in this role because it aligns closely with my experience in maintaining structured, accurate, and reliable data systems.",
        "experience": "I sit somewhere between art and technology, but the skill I am most confident in is bringing order to data. In previous independent work, I built an eBay and Yahoo Auctions arbitrage system that collected product data, structured it in Excel, and calculated profitability to identify resale opportunities. I later expanded this workflow using Python and SQL, and improved data quality by cleaning and standardising inconsistent listing information. More recently, I developed a local AI image-tagging workflow in Obsidian that processed 1,800 images, generating tags and summaries for efficient organisation. The system is designed for repeatable batch processing while keeping all data fully local and private.",
        "skills": "I am detail-oriented, comfortable working independently, and focused on accuracy and consistency in data handling. While my spoken English is still developing, I am confident in written communication and structured, task-based work environments.",
        "closing": "I would be genuinely pleased if the skills and experience I have built could support your work, and in turn help the artists and makers who shape this city\'s creative culture.",
        "team_name": ""
    },
    "creative_technologist": {
        "opening": "I am writing to express my interest in the {job_title} position at {company}. As a creative technologist who builds end-to-end pipelines combining Obsidian, ComfyUI, Blender, and local AI tools, I have been following {company}\'s work in creative technology with great interest.",
        "experience": "My background spans both visual production and technical systems engineering. I have built automated creative workflows that transform structured ideation (Obsidian Canvas + LLM-assisted decomposition) into AI-generated visual concepts (ComfyUI/Stable Diffusion), and further into 3D asset production (Blender). This includes managing Linux-based compute environments, debugging complex tool interactions, and maintaining pipeline stability across tool version changes and platform constraints.",
        "skills": "I combine technical troubleshooting skills (Linux, Python, process monitoring) with creative sensibility (composition, visual iteration, asset organisation). My experience with local AI workflows (Opencode, local LLMs, VLM tagging) means I can work with sensitive creative assets while maintaining full data privacy — a growing concern in creative production.",
        "closing": "I am excited about the opportunity to contribute to {company}\'s creative technology initiatives and help bridge the gap between artistic vision and technical execution.",
        "team_name": "Creative Technology"
    },
    "technical_artist": {
        "opening": "I am writing to apply for the {job_title} role at {company}. As a technical artist with dual expertise in creative production and systems engineering, I am drawn to {company}\'s reputation for technical excellence in game development pipelines.",
        "experience": "I have built automated workflows for asset processing, image tagging, and data validation using Python, local AI models, and creative tools (Blender, ComfyUI, Affinity Suite). This includes managing Linux environment stability for creative workloads, diagnosing pipeline failures under changing conditions, and adapting toolchains when external constraints (API changes, version updates) break existing workflows.",
        "skills": "My strength is bridging art and engineering — I understand both the creative intent behind asset production and the technical constraints of real-time pipelines. I am experienced in shader/material workflows, VFX pipelines, and asset organisation at scale. I am actively learning Unreal Engine and JIRA for production tracking to align with industry-standard game development workflows.",
        "closing": "I would welcome the opportunity to support your art and engineering teams by stabilizing toolchains, improving production reliability, and reducing friction in creative workflows.",
        "team_name": "Technical Art"
    },
    "web_developer": {
        "opening": "I am writing to apply for the {job_title} position at {company}. With a background in building automation-driven web applications and data pipelines, I am excited about the opportunity to contribute to your engineering team.",
        "experience": "I have built web scrapers, API integrations, and browser automation tools using Python, PostgreSQL, and modern web technologies. My systems experience includes Linux server management, Docker deployment, process monitoring with Prometheus/Grafana, and debugging distributed systems under changing external conditions. I prototyped core logic in Excel/VBA before migrating to Python and PostgreSQL as complexity increased — giving me a pragmatic approach to choosing the right tool for each stage.",
        "skills": "I combine full-stack development skills with a strong automation and data engineering foundation. My experience with n8n workflow orchestration, local LLM tooling, and structured documentation (Obsidian/Markdown) means I can build reliable, maintainable systems and communicate technical decisions clearly across teams.",
        "closing": "I am keen to apply my interdisciplinary background to help {company} build robust, scalable web applications and data-driven features.",
        "team_name": "Engineering"
    },
    "general": {
        "opening": "I am writing to apply for the {job_title} role at {company} in {job_location}. As a local Edinburgh resident with a versatile technical background spanning systems engineering, automation, data processing, and creative workflow design, I believe I could contribute effectively to your team.",
        "experience": "My experience includes building and maintaining automated systems independently for 4+ years — from data processing pipelines (Python, PostgreSQL, VBA) to Linux environment management and AI-assisted creative workflows (ComfyUI, local LLMs, VLM tagging). These systems required continuous debugging and adaptation under changing external conditions, with a focus on maintaining stability and reliability. At Terra Drone, I worked between engineering and business teams, translating technical information into actionable outcomes across functions.",
        "skills": "I combine technical troubleshooting (root cause analysis, process monitoring) with practical automation skills (web scraping, data cleaning, workflow orchestration). I am comfortable working independently, adapting quickly to new tools, and bridging technical and non-technical stakeholders through clear documentation and communication.",
        "closing": "I would welcome the opportunity to discuss how my interdisciplinary background could support {company}\'s goals.",
        "team_name": ""
    }
}

PERSONAL_INFO = {
    "name": "Kazuki Yunome",
    "location": "Edinburgh, Scotland, UK (Local Resident)",
    "email": "junoyuno55@gmail.com",
    "phone": "07787 702187",
    "github": "https://github.com/0xkz1",
    "linkedin": "https://www.linkedin.com/in/kazukiyunome/",
    "linktree": "https://linktr.ee/kazukiyunome"
}

from datetime import date

def generate_cover_letter(job_title: str, company: str, job_location: str = "Edinburgh", job_description: str = "") -> str:
    """Generate a tailored cover letter."""
    role_type = detect_role_type(job_title, job_description)
    template = COVER_TEMPLATES.get(role_type, COVER_TEMPLATES["general"])
    
    today = date.today().strftime("%d %B %Y")
    team_name = template["team_name"]
    
    # For general template, use empty team_name
    closing_para = template["closing"].format(company=company, job_title=job_title, job_location=job_location)
    
    return MASTER_COVER_LETTER.format(
        name=PERSONAL_INFO["name"],
        location=PERSONAL_INFO["location"],
        email=PERSONAL_INFO["email"],
        phone=PERSONAL_INFO["phone"],
        date=today,
        company=company,
        job_location=job_location,
        job_title=job_title,
        opening_paragraph=template["opening"].format(company=company, job_title=job_title, job_location=job_location),
        experience_paragraph=template["experience"],
        skills_paragraph=template["skills"],
        closing_paragraph=closing_para,
        team_name=team_name
    )

def save_cover_letter(job_title: str, company: str, job_location: str, job_description: str, output_dir: str) -> str:
    """Generate and save cover letter as Markdown."""
    import os
    import re
    from pathlib import Path
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    letter = generate_cover_letter(job_title, company, job_location, job_description)
    
    safe_company = re.sub(r"[^\w\s-]", "", company).strip().replace(" ", "_")[:30]
    safe_title = re.sub(r"[^\w\s-]", "", job_title).strip().replace(" ", "_")[:50]
    filename = f"{safe_company}_{safe_title}_CL.md"
    filepath = Path(output_dir) / filename
    
    filepath.write_text(letter, encoding="utf-8")
    return str(filepath)

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        jt = sys.argv[1]
        co = sys.argv[2]
        loc = sys.argv[3] if len(sys.argv) > 3 else "Edinburgh"
        desc = sys.argv[4] if len(sys.argv) > 4 else ""
        print(generate_cover_letter(jt, co, loc, desc))
    else:
        # Demo
        print(generate_cover_letter("Development Support", "Rockstar North", "Edinburgh"))