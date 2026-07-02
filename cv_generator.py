# Master CV Template
# ===================
# Source: Merged from Rockstar North (Dev Support) + Paper Tiger (Data Input)
# Generated for automated CV customization per job

MASTER_CV = """Kazuki Yunome
Edinburgh, Scotland, UK (Local Resident) | junoyuno55@gmail.com | 07787 702187
GitHub: https://github.com/0xkz1 | LinkedIn: https://www.linkedin.com/in/kazukiyunome/
Linktree: https://linktr.ee/kazukiyunome

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
Independent Development & Workflow Support | Independent | 2019 – 2022
Maintained and supported automated data processing workflows, monitoring system behaviour, and diagnosing failures under changing external conditions.
Built an automated arbitrage system scraping product listings from Yahoo Auctions and Mercari, comparing prices against eBay data, and listing qualifying items — deployed on Heroku for real-time data processing and automated listing execution.
Attempted eBay API integration, encountered platform constraints, and pivoted to browser automation (Selenium) as a practical workaround — gaining hands-on experience diagnosing integration limitations and adapting strategies under technical constraints. Prototyped core logic in Excel/VBA before migrating to Python and PostgreSQL as complexity increased.

Linux Systems & Process Management | Independent | 2025 – Present
Monitored and managed multiple concurrent processes using tmux and monitoring tools in a Linux environment. Diagnosed process failures, identified root causes, and maintained operational stability under changing conditions.

Sales & Cross-functional Support | Terra Drone Inc. (Tokyo) | 2017 – 2019
Supported communication between engineering and business teams in a drone surveying company, working with technical product information in a sales and client-facing context. Worked on product explanation and client-facing communication for drone systems and 3D mapping software, supporting sales activities and coordination of deliverables across teams, including brochures, technical documents, and email campaigns.

Creative Workflow Development — "Feral" | Taifunomé | 2023 – Present
Built an end-to-end creative production pipeline: transforming Obsidian Canvas idea boards into structured markdown, applying LLM-assisted Zettelkasten-style decomposition to generate modular conceptual units, and converting them into prompts for AI image generation workflows using ComfyUI.

Architectural Visualization Project | Taifunomé | 2025 – Present
Developed structured visual production workflows using Obsidian Canvas, ComfyUI, and Blender to explore composition, asset structure, and iteration processes within digital content pipelines.

Design Competition Entry — "Hive Floral Pod" | Taifunomé | 2024
Developed a conceptual product from ideation to a structured 3D visual proposal using Procreate and Blender, delivering a complete submission within competition deadline constraints.

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

# Profile variants per role type
PROFILE_VARIANTS = {
    "development_support": "Technical specialist focused on development support and production workflows, with hands-on experience maintaining, diagnosing, and improving automated workflows and data processing systems. Experienced in breaking down complex technical issues, identifying root causes, and adapting approaches iteratively until systems are stable and reliable. Comfortable supporting both technical and non-technical stakeholders by translating problems into clear, actionable steps. My background spans independent systems development, Linux environment management, and creative workflow design — providing a practical understanding of how technical systems support creative production workflows. I am particularly motivated to support creative teams and contribute to tool pipelines within game development.",
    
    "data_analysis": "Detail-oriented and self-directed professional with hands-on experience building automation tools, data-cleaning workflows, and AI-assisted image tagging systems. Strong background in Excel, VBA, Python, SQL, and local AI workflows, with a practical focus on improving data quality, reducing manual work, and handling large batches of structured and unstructured information. Comfortable working independently, adapting to new tools quickly, and turning messy workflows into reliable systems.",
    
    "creative_technologist": "Creative technologist bridging visual production and technical systems. Experienced in building end-to-end creative pipelines combining Obsidian, ComfyUI, Blender, and local AI tools for concept development and asset generation. Strong foundation in Linux systems management, Python automation, and workflow orchestration. Passionate about reducing friction between creative intent and technical execution in game development, architectural visualization, and digital content production.",
    
    "technical_artist": "Technical artist with dual expertise in creative production and systems engineering. Proven track record building automated workflows for asset processing, image tagging, and data validation using Python, local AI models, and creative tools (Blender, ComfyUI, Affinity Suite). Experienced in Linux environment management, process monitoring, and troubleshooting technical pipelines under changing conditions. Motivated to support art and engineering teams by stabilizing toolchains and improving production reliability.",
    
    "web_developer": "Full-stack developer with a focus on automation and data-driven applications. Experienced building web scrapers, data processing pipelines, and browser automation tools using Python, PostgreSQL, and modern web technologies. Strong Linux systems background with hands-on experience in Docker, process monitoring, and deployment workflows. Comfortable translating business requirements into reliable, maintainable technical solutions.",
    
    "general": "Versatile technical professional with hands-on experience spanning systems engineering, automation, data processing, and creative workflow design. Experienced in Linux environment management, Python automation (web scraping, data cleaning, SQL), and AI-assisted pipelines (ComfyUI, local LLMs, VLM tagging). Proven ability to diagnose complex technical issues, adapt workflows under constraints, and bridge technical and non-technical stakeholders. Seeking to apply this interdisciplinary skillset in development support, creative technology, or technical operations roles."
}

# Core strengths variants
STRENGTHS_VARIANTS = {
    "development_support": "• Technical troubleshooting and root cause analysis\n• Workflow support and process improvement\n• Task and issue tracking (structured documentation, reproducibility)\n• Cross-functional communication (technical ↔ non-technical)\n• Team collaboration (in-person and remote)\n• Working within evolving schedules and delivery constraints\n• Technical curiosity and self-directed learning",
    
    "data_analysis": "• Data entry, validation, formatting, and quality control\n• Data cleaning and standardisation\n• Excel workflow design and spreadsheet automation with VBA, Python, SQL, Pandas, NumPy\n• E-commerce and product data processing\n• Image organisation, tagging, and asset handling\n• Root cause analysis and troubleshooting\n• Independent work and self-management\n• Clear communication with technical and non-technical stakeholders\n• Adapting quickly to new tools, systems, and workflows",
    
    "creative_technologist": "• End-to-end creative pipeline design (Obsidian → LLM → ComfyUI → Blender)\n• Technical troubleshooting and root cause analysis in creative workflows\n• Workflow automation and process improvement\n• Cross-functional communication (artists ↔ engineers)\n• Asset organisation, tagging, and visual data management\n• Rapid prototyping and iteration under deadline constraints\n• Self-directed learning of emerging creative tech (Stable Diffusion, local LLMs)",
    
    "technical_artist": "• Technical art pipeline design and troubleshooting\n• Asset processing automation (Python, local AI, Blender)\n• Shader, material, and VFX workflow support\n• Cross-team communication (art ↔ engineering ↔ production)\n• Process monitoring and stability management in creative tools\n• Problem-solving under evolving technical constraints\n• Rapid learning of new DCC tools and game engine workflows",
    
    "web_developer": "• Full-stack web development with automation focus\n• Web scraping, API integration, and data pipeline construction\n• Database design and SQL optimization (PostgreSQL)\n• Linux systems management and Docker deployment\n• Debugging and root cause analysis in distributed systems\n• Clean code practices and technical documentation\n• Agile workflows and cross-functional collaboration",
    
    "general": "• Technical troubleshooting and root cause analysis\n• Workflow automation and process improvement (Python, VBA, n8n, SQL)\n• Data cleaning, validation, and standardisation\n• Cross-functional communication (technical ↔ non-technical)\n• Independent work and self-management\n• Rapid learning of new tools, systems, and workflows\n• Structured documentation and reproducibility (Obsidian, Markdown)"
}

def get_profile(role_type: str = "general") -> str:
    """Get profile text for a role type."""
    return PROFILE_VARIANTS.get(role_type, PROFILE_VARIANTS["general"])

def get_strengths(role_type: str = "general") -> str:
    """Get core strengths for a role type."""
    return STRENGTHS_VARIANTS.get(role_type, STRENGTHS_VARIANTS["general"])

def generate_cv(role_type: str = "general") -> str:
    """Generate a complete CV for a specific role type."""
    profile = get_profile(role_type)
    strengths = get_strengths(role_type)
    return MASTER_CV.format(profile=profile, core_strengths=strengths)

# Role type detection from job title/description
ROLE_KEYWORDS = {
    "development_support": ["development support", "dev support", "tools engineer", "pipeline engineer", "build engineer", "internal tools", "production support", "platform engineer"],
    "data_analysis": ["data entry", "data analyst", "data input", "data quality", "data validation", "data cleaning", "data processing", "spreadsheet", "excel specialist"],
    "creative_technologist": ["creative technologist", "creative tech", "technical creative", "creative developer", "generative ai", "ai artist", "comfyui", "stable diffusion"],
    "technical_artist": ["technical artist", "tech artist", "graph technical artist", "pipeline artist", "vfx artist", "shader artist", "rendering artist"],
    "web_developer": ["web developer", "frontend developer", "backend developer", "full stack", "fullstack", "software engineer", "python developer", "django", "react"],
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

if __name__ == "__main__":
    import sys
    role = sys.argv[1] if len(sys.argv) > 1 else "general"
    print(generate_cv(role))