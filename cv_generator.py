# Master CV Template
# ===================
# Source: Merged from Rockstar North (Dev Support) + Paper Tiger (Data Input)
# Generated for automated CV customization per job

import re

from contact_details import CONTACT, header_line, links_line

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
MASTER_CV = """# {candidate_name}
**{role_title}**
{contact_line}
{links_line}

## PROFILE
{profile}

## EXPERIENCE
{employment}

## SELECTED PROJECTS
{experience}

## TECHNICAL TOOLKIT
{technical_toolkit}

## EDUCATION & LANGUAGES
**Hokkai Gakuen University, Sapporo, Hokkaido | 2013 – 2017** — Faculty of Humanities, Department of English and American Culture
**Escuela Falcon, Guanajuato, México | 2016 (3 months)** — Spanish Language School
**Languages:** Japanese (native) · English (professional working) · Spanish (daily conversation)"""

# The Japanese CV. A twin of MASTER_CV, not a translation of one: every
# {placeholder} is filled from the same records, reading their "## 和訳" half
# instead of their English half (see _split_translation). Nothing here is
# model-written.
#
# What deliberately stays in English, because a Japanese technical CV writes it
# that way too: the role title (it is the posting's own words), project and
# employer names, the toolkit category headings, and the toolkit itself — a
# list of proper nouns. Translating "TypeScript, Blender, Sanity headless CMS"
# would make the CV harder to scan, not easier.
#
# The phone number is the international form: this CV answers a Japanese
# posting, so a reader dialling it is not in the UK.
MASTER_CV_JA = """# {candidate_name_ja}
**{role_title}**
{contact_line_ja}
{links_line}

## プロフィール
{profile}

## 職務経験
{employment}

## プロジェクト
{experience}

## 技術スタック
{technical_toolkit}

## 学歴・語学
**北海学園大学（北海道札幌市） | 2013 – 2017** — 人文学部 英米文化学科
**Escuela Falcon（メキシコ・グアナファト） | 2016（3ヶ月）** — スペイン語語学学校
**言語:** 日本語（母語） · 英語（ビジネスレベル） · スペイン語（日常会話レベル）"""

# Fallback header if a profile is missing role_title in its frontmatter — keeps
# generation working rather than rendering "{role_title}" literally into the CV.
#
# The header used to carry a second line, role_tagline, under the job title. It
# restated what the PROFILE paragraph said two lines later ("end-to-end AI
# creative pipelines" above "building end-to-end creative pipelines"), which
# read as padding. The header is a signboard: one line, one claim. Whatever the
# tagline said that the profile did not now lives in the profile text.
_DEFAULT_ROLE_TITLE = "Full-stack Developer & Designer"


def get_header(role_type: str = "general") -> str:
    """Get the role_title from a profile's frontmatter, falling back to
    general.md, then to the hardcoded default."""
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
        return _DEFAULT_ROLE_TITLE

    try:
        content = profile_path.read_text(encoding="utf-8")
        parts = content.split("---")
        frontmatter = yaml.safe_load(parts[1]) or {} if len(parts) >= 3 else {}
        title = frontmatter.get("role_title")
        if title:
            return title
    except Exception as e:
        print(f"  ⚠ Error loading header for {role_type}: {e}")

    if role_type != "general":
        return get_header("general")
    return _DEFAULT_ROLE_TITLE


def load_profile_and_strengths(role_type: str = "general", lang: str = "en") -> tuple[str, str, str]:
    """
    Dynamically load profile text, core strengths, and technical toolkit from:
    00_Kazuki/career/cv/profile/{role_type}.md

    lang="ja" swaps the profile paragraph for the file's "## 和訳" rendering.
    Only the profile: strengths are unused by the current template, and the
    toolkit is a list of proper nouns (TypeScript, Blender, Sanity) that reads
    the same either way — its category headings are the only English left on a
    Japanese CV, which is how a Japanese technical CV is normally written.
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
            return load_profile_and_strengths("general", lang)
        return "", "", ""

    try:
        content = profile_path.read_text(encoding="utf-8")
        parts = content.split("---")
        body = parts[-1].strip()
        # The section walker below reads "## Profile"; "## 和訳" falls through it
        # as an unrecognised heading, which is what kept the translation off an
        # English CV. Take that half here, before the walker ever sees it.
        body, profile_ja = _split_translation("\n" + body)
        
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

        if lang == "ja":
            profile_text = profile_ja

        return profile_text, strengths_text, toolkit_text
    except Exception as e:
        print(f"  ⚠ Error loading profile/strengths/toolkit for {role_type}: {e}")
        if role_type != "general":
            return load_profile_and_strengths("general", lang)
        return "", "", ""

def get_profile(role_type: str = "general", lang: str = "en") -> str:
    """Get profile text for a role type."""
    p, _, _ = load_profile_and_strengths(role_type, lang)
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
    # The reverse of web_developer's opening pair, which is the whole point of
    # the split: a front-end reader scans for the interface stack first and the
    # language second. Design sits above Programming because these postings ask
    # for someone who works with UX, and the Figma/design-token block is the
    # evidence for that.
    "frontend_developer":    ["Frontend & Product Engineering", "Design & Visual Production", "Programming & Automation", "Systems & Infrastructure"],
    "product_designer":      ["Design & Visual Production", "Frontend & Product Engineering", "3D & Generative Media", "AI Systems & Agents"],
    # Brand/print roles read the image-making tools as craft evidence, so 3D &
    # Generative Media sits above the front-end block — the reverse of
    # product_designer, where the shipped interface matters more.
    "graphic_designer":      ["Design & Visual Production", "3D & Generative Media", "Frontend & Product Engineering", "AI Systems & Agents"],
    "creative_technologist": ["3D & Generative Media", "AI Systems & Agents", "Design & Visual Production", "Programming & Automation"],
    "technical_artist":      ["3D & Generative Media", "Design & Visual Production", "Programming & Automation", "AI Systems & Agents"],
    "data_analysis":         ["Programming & Automation", "AI Systems & Agents", "Systems & Infrastructure"],
    "development_support":   ["Systems & Infrastructure", "Programming & Automation", "AI Systems & Agents"],
    # Split out of development_support: a platform/infra reader scans for the
    # stack they operate before the language they write in, and reads the AI
    # block as tooling used across the SDLC rather than as a novelty — so the
    # documentation block trails the three that matter and the design work sits
    # last by master-file order.
    "platform_engineer":     ["Systems & Infrastructure", "Programming & Automation", "AI Systems & Agents", "Documentation & Knowledge"],
    # Bridge roles: API/integration and systems work leads, design trails. A
    # support or implementation reader is scanning for the stack they run, and
    # product_ops is the one of the four where the front end and the visual work
    # are part of the job rather than a footnote.
    "implementation_specialist": ["Programming & Automation", "Systems & Infrastructure", "Frontend & Product Engineering", "AI Systems & Agents"],
    "product_ops":           ["Frontend & Product Engineering", "Programming & Automation", "Design & Visual Production", "Systems & Infrastructure"],
    "qa_engineer":           ["Programming & Automation", "Systems & Infrastructure", "Frontend & Product Engineering", "AI Systems & Agents"],
    "technical_support":     ["Systems & Infrastructure", "Programming & Automation", "AI Systems & Agents"],
    "research_engineer":     ["Programming & Automation", "AI Systems & Agents", "Systems & Infrastructure", "Documentation & Knowledge"],
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
    # "development support" as a bare phrase is an HR-boilerplate magnet, not a
    # role signal: "Career development support", "Learning & Development support
    # available", "continuous development support" appear in 181 postings in the
    # corpus, and one of those body hits routed a "Junior Back End Engineer" post
    # to this profile. Only the forms that name the job survive.
    "development_support": ["development support engineer", "software development support", "dev support", "tools engineer", "pipeline engineer", "build engineer", "internal tools", "production support"],
    # "platform engineer" used to route here, which answered an infrastructure
    # posting with a "Development Support Engineer" headline — a support title
    # for a build-and-own-it job. Infra/SRE/DevOps postings ask for the stack
    # you run, so they get their own profile and their own project ordering.
    # "platform engineer" covers "Platform Engineering" by substring; the two
    # devops spellings do not cover each other. Bare "sre" is deliberately
    # absent — it matches inside unrelated words.
    "platform_engineer": [
        "platform engineer", "infrastructure engineer", "devops", "dev ops",
        "site reliability", "cloud engineer", "cloud infrastructure",
        "internal developer platform",
        # Body-signal tool names: specific enough that a posting naming them is
        # an infra posting, and a body hit is worth a tenth of a title hit, so
        # they cannot outvote a title that names a different discipline.
        "kubernetes", "terraform", "observability",
    ],
    "data_analysis": ["data entry", "data analyst", "data input", "data quality", "data validation", "data cleaning", "data processing", "spreadsheet", "excel specialist"],
    # Job-title forms only. A bare "content" or "editorial" is boilerplate in
    # postings of every discipline ("editorial calendar", "content management
    # system"), and the one-word forms would outvote a title naming a different
    # job. "content designer" is deliberately absent: it reads as a product
    # design title as often as an editorial one, and product_designer owns it.
    "content_analyst": [
        "content analyst", "content strategist", "content operations",
        "content editor", "content producer", "content marketing",
        "copywriter", "editorial assistant",
    ],
    "creative_technologist": ["creative technologist", "creative tech", "technical creative", "creative developer", "generative ai", "ai artist", "comfyui", "stable diffusion"],
    "technical_artist": ["technical artist", "tech artist", "graph technical artist", "pipeline artist", "vfx artist", "shader artist", "rendering artist"],
    # Split out of web_developer 2026-09-03. web_developer owns one profile file,
    # and that file's headline is "Full-stack Developer" — so every front-end
    # title in the corpus (27 CVs on disk) introduced the applicant as a
    # full-stack developer whose PROFILE paragraph opens on web scrapers and data
    # pipelines. The route was correct; the bucket was too wide to carry a
    # headline. Front-end titles and React now have their own profile, and the
    # back-end/full-stack/software-engineer vocabulary stays with web_developer.
    #
    # Listed BEFORE web_developer because a title tie is settled by dict order,
    # and the ties are real: "Front End Software Engineer" scores one title hit
    # here and one on web_developer's "software engineer". The front-end reading
    # is the right one — the title names the discipline, "software engineer" only
    # names the profession.
    #
    # The three spellings are listed BARE rather than as "front end developer"/
    # "front end engineer" compounds, and the compounds are deliberately absent.
    # Measured over the 5406-posting corpus: 83 titles name front-end work, and
    # the compound list caught only 46 of them. The misses were the titles that
    # put a word between the discipline and the noun — "Front End Web Developer"
    # (24 of them went to web_developer on "web developer"), "Frontend Software
    # Engineer", "Software Engineer, Front End" — plus 10 that matched nothing at
    # all ("Frontend JavaScript Developer", "Front End Game Developer"). Bare
    # forms catch all of those, and listing ONLY the bare form keeps a front-end
    # title at exactly one hit: adding both would score "Front End Engineer"
    # twice and let it outvote a genuine hybrid like "UI/UX Designer and Front
    # End Engineer", which product_designer should keep.
    "frontend_developer": ["front end", "front-end", "frontend", "react", "reactjs"],
    # "Engineer" and spaced/hyphenated spellings are listed explicitly: matching is
    # anchored, so "backend developer" does not cover "Back End Engineer" — that
    # gap left the canonical title with zero title evidence and let a body hit
    # decide. "reactjs" is its own entry because the anchor stops "react" from
    # firing inside it.
    # "full-stack" joins "full stack"/"fullstack" for the same reason the back-end
    # spellings are all listed: the hyphenated form matched nothing, so a posting
    # titled "Full-stack Engineer" had zero title evidence and was decided by its
    # body — which named React, and routed a full-stack post to the front-end CV.
    "web_developer": ["web developer", "backend developer", "back end developer", "back-end developer", "backend engineer", "back end engineer", "back-end engineer", "full stack", "full-stack", "fullstack", "software engineer", "software developer", "python developer", "django"],
    "product_engineer": [
        "product engineer", "product engineering", "product-led", "product ownership",
        "full-stack product", "fullstack product", "product builder",
        # AI-applications / agent-infrastructure roles: title says "AI" not
        # "product" but the role IS product engineering with an AI toolset —
        # building real multi-agent systems in production, not demos.
        #
        # Title-signal keywords: these read as role NAMES in a title, so they
        # can fire on a title hit (×10) without polluting body-only matches
        # the way a bare "ai applications" would — "ai applications" appeared
        # once in a print-designer JD's prose ("experience using AI
        # applications") and tied the graphic_designer score, stealing the
        # route. Keep these title-only-ish; use title-specific variants below
        # for body-signal ones.
        "ai applications specialist", "ai application specialist",
        "ai engineer", "ai specialist",
        "agentic developer", "agent developer",
        # Tool names that signal this is an agent-automation post, not a
        # prompt-engineer post — Claude Code and Codex are explicitly named
        # in the Digital Waffle/AI Applications Specialist JD. These are
        # specific enough to also be safe as body-hits.
        "claude code", "openai codex",
        # Body-signal phrases: distinctive enough not to appear in unrelated
        # postings. "multi-agent" in prose is almost always the real thing.
        "multi-agent", "agent-driven", "autonomous research agent",
    ],
    # "ux &" / "ux and" / "ux design" rather than a bare "ux": the graphic_designer
    # split gave "digital designer" away, so a hybrid title like "UX & Digital
    # Designer" scored zero here and routed to the brand CV. A bare "ux" would
    # match inside unrelated words, so the co-occurrence forms are the safe ones.
    "product_designer": ["product designer", "ux designer", "ui designer", "ui/ux", "ux/ui", "ux &", "ux and", "ux design", "user experience designer", "interaction designer", "visual designer", "product design", "design systems", "figma", "web designer"],
    # Split out of product_designer: a print/brand/artwork post and a UX post
    # both said "designer", so both got the product_designer CV — which leads
    # on interface and information architecture and buries the identity and
    # illustration work an agency or in-house brand team is actually reading
    # for. Keywords here are the brand/print/artwork vocabulary; the UX/UI
    # vocabulary stays with product_designer.
    "graphic_designer": ["graphic designer", "graphic design", "digital designer", "brand designer", "brand design", "brand visuals", "visual identity", "brand identity", "creative designer", "artworker", "print design", "packaging designer", "motion designer", "motion graphics", "marketing designer", "studio designer", "midweight designer", "adobe creative suite", "indesign", "illustrator"],
    "camera_assistant": ["camera assistant", "photography assistant", "photo assistant", "camera operator", "studio photographer", "photographer", "photography"],
    # ── Bridge roles (2026-08-07) ────────────────────────────────────────────
    # Added because the creative-technologist search alone was not producing
    # first-round interviews: these are the adjacent jobs where the Terra Drone
    # client-facing years and the integration/operations work count as the main
    # qualification rather than as background. Each has its own profile, cover
    # letter and outreach template, so a match routes to documents written for it.
    #
    # Phrases, not single words. "support", "implementation", "integration" and
    # "quality" each appear in ordinary prose in most postings, and a body hit is
    # worth 1 against a title hit's 10 — but enough stray body hits still outvote
    # a role with no title evidence at all, which is exactly how camera_assistant
    # once captured a Digital Designer posting.
    "implementation_specialist": ["implementation consultant", "implementation specialist", "implementation engineer", "implementation analyst", "integration specialist", "integration consultant", "solutions engineer", "solution engineer", "solutions consultant", "onboarding specialist", "technical consultant", "professional services", "customer solutions"],
    "product_ops": ["product operations", "product ops", "web operations", "website coordinator", "website manager", "web content", "content operations", "digital operations", "data operations", "digital coordinator", "digital producer", "web coordinator", "content executive", "cms administrator"],
    "qa_engineer": ["qa engineer", "qa analyst", "qa tester", "quality assurance", "quality engineer", "test analyst", "test engineer", "software tester", "test automation", "sdet"],
    "technical_support": ["technical support", "support engineer", "support analyst", "support specialist", "application support", "it support", "service desk", "helpdesk", "help desk", "1st line support", "2nd line support", "first line support", "second line support"],
    # Research Software Engineer — Edinburgh-specific path (Bayes Centre, CodeBase,
    # university-adjacent orgs). Irregular postings; matched on title phrases rather
    # than bare "research" which appears in every description. The abbreviation
    # "rse" is deliberately NOT listed: matching is substring, not word-boundary,
    # so it fires inside "nurse", "course" and "parser" — and a title hit is
    # worth 10, enough to route a nursing post to a research CV on its own.
    # "research software" is listed as well as "research software engineer" so the
    # exact title "Research Software Engineer" scores TWO title hits. It also
    # contains web_developer's "software engineer", and scoring is by hit count with
    # ties broken by dict order — one hit each sent the canonical RSE title to the
    # web-developer CV.
    "research_engineer": ["research software engineer", "research software", "research engineer", "research developer", "research computing", "scientific software", "research infrastructure", "computational researcher", "creative informatics", "data science engineer"],
}

# Keyword matching is anchored so a keyword cannot fire from inside a longer
# word — "rse" used to match "nurse"/"course"/"parser", and "react" matched
# "reactive maintenance". Two things keep the anchor from being a plain \b:
#
#   * the right edge tolerates an English suffix, because "graphic design" must
#     still hit "Graphic Designer";
#   * the right edge bans only a LOWERCASE continuation, and matching runs on
#     the original casing. Scraped descriptions lose the whitespace at HTML
#     block joins ("Azure DevOpsKnowledge of Power Apps", "interaction
#     designersContribute to service"), so a capital-letter continuation is a
#     word boundary in practice. Case-folding the text first would throw that
#     signal away and drop the real hit.
_KW_SUFFIX = r"(?i:s|es|er|ers|ing|ed)?(?![a-z])"


def _kw_pattern(keyword: str) -> "re.Pattern[str]":
    """Anchored, case-insensitive matcher for one keyword. Scoped (?i:...)
    rather than re.IGNORECASE: a global flag would make the [a-z] lookahead
    match capitals too and undo the run-together handling above."""
    return re.compile(r"(?<![A-Za-z0-9])(?i:" + re.escape(keyword) + r")" + _KW_SUFFIX)


_ROLE_PATTERNS = {role: [(kw, _kw_pattern(kw)) for kw in keywords]
                  for role, keywords in ROLE_KEYWORDS.items()}

TITLE_WEIGHT = 10  # a title hit outweighs any number of body hits
# A route with NO title evidence at all is the dangerous one: 38% of generated
# CVs were picked that way, and the deciding keyword was often boilerplate
# ("Career development support" sent a Back End Engineer post to the support
# CV; "Mechanical Design Engineer" got the web-developer CV). Body evidence now
# has to be corroborated — several distinct keywords AND a clear win over the
# runner-up — or the route falls back to `general`, which is a real CV that is
# merely unspecialised rather than a CV written for the wrong discipline.
MIN_BODY_KEYWORDS = 2
MIN_BODY_MARGIN = 2


def _score_roles(job_title: str, job_description: str) -> dict[str, tuple[int, list[str], list[str]]]:
    """Score every role, keeping the keywords that fired so the decision can be
    explained after the fact (see detect_role_type_with_evidence)."""
    title = job_title or ""
    body = job_description or ""
    scored = {}
    for role, pairs in _ROLE_PATTERNS.items():
        title_hits = [kw for kw, pat in pairs if pat.search(title)]
        body_hits = [kw for kw, pat in pairs if pat.search(body)]
        scored[role] = (TITLE_WEIGHT * len(title_hits) + len(body_hits),
                        title_hits, body_hits)
    return scored


def detect_role_type_with_evidence(job_title: str, job_description: str = "") -> tuple[str, str]:
    """Detect the role type and return why, as a short string for the CV
    frontmatter: "title:back end engineer", "body:figma,ux design",
    "weak-body:technical_support:it support", "tie:qa_engineer,web_developer"
    or "none". The evidence is what makes a misroute greppable instead of
    something you notice by reading a headline.

    The title names the role; the description only supports it. Weighting them
    equally let a single incidental word in the body outvote the title — a
    "Digital Designer" posting that mentions "product photography" once was
    classified camera_assistant and got a photographer's CV. So a title match is
    worth far more than a body match, and a clear title winner is taken directly.
    """
    scored = _score_roles(job_title, job_description)
    ranked = sorted(scored.items(), key=lambda item: -item[1][0])
    best, (score, title_hits, body_hits) = ranked[0]
    runner_up = ranked[1][1][0] if len(ranked) > 1 else 0

    if score == 0:
        return "general", "none"
    if title_hits:
        # A title tie is left to ROLE_KEYWORDS order: a title naming two
        # disciplines ("UX & Digital Designer") is a real hybrid, and the dict
        # order is the declared preference between them.
        return best, "title:" + ",".join(title_hits)
    if len(body_hits) < MIN_BODY_KEYWORDS:
        return "general", f"weak-body:{best}:" + ",".join(body_hits)
    if score - runner_up < MIN_BODY_MARGIN:
        # Includes the outright tie that dict order used to settle silently, and
        # the one-hit-apart case that is no more decided than a tie.
        contenders = sorted(role for role, value in scored.items()
                            if value[0] >= runner_up and value[0] > 0)
        return "general", "thin-margin:" + ",".join(contenders)
    return best, "body:" + ",".join(body_hits)


def detect_role_type(job_title: str, job_description: str = "") -> str:
    """Detect best role type from job title and description.

    Thin wrapper over detect_role_type_with_evidence — every caller that only
    needs the route keeps its one-value signature.
    """
    return detect_role_type_with_evidence(job_title, job_description)[0]


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

def _cv_root() -> "Path | None":
    """The career/cv directory, wherever this checkout is mounted."""
    from pathlib import Path
    for candidate in [
        Path("/home/kz003/atelier/00_Kazuki/career/cv"),
        Path("/media/kz003/atelier/00_Kazuki/career/cv"),
        Path(__file__).resolve().parent.parent / "cv",
    ]:
        if candidate.exists():
            return candidate
    return None


# Which directory a record lives in decides what it is. The two kinds render in
# different CV sections and were only told apart by a `type: employment` line in
# the frontmatter, so telling them apart meant opening the file — and nothing
# stopped an employment id being listed in STATIC_EXPERIENCE, where it would
# never resolve. The folder name matches the CV section it feeds (EXPERIENCE).
_ENTRY_DIRS = (("projects", "project"), ("experience", "employment"))


# The reference translation trailing a CV entry. Every source file under
# career/cv/** carries the same shape — a "## 和訳" heading, a parenthetical
# note addressed to whoever edits the file, then the translated body — so one
# splitter serves projects, experience and profiles alike.
_TRANSLATION_HEADING = re.compile(r"\n##\s*和訳\s*\n")
# "（参照用。CVには含まれない — …）". Written to the author, never to a reader.
_TRANSLATION_NOTE = re.compile(r"\A\s*（[^）]*）\s*")


def _split_translation(body: str) -> tuple[str, str]:
    """Split a CV entry body into (English, Japanese).

    The Japanese half was discarded outright until now: it exists so the author
    can check a translation against the English, and letting it through printed
    both languages onto one CV. But it is a real second rendering of the same
    entry — written by hand, and the only one anybody has verified — so the
    Japanese CV reads it rather than paying a model to translate at generation
    time. That is the whole reason a ja CV can be assembled and not written.

    Returns "" for Japanese when a file has no 和訳 section. Callers must treat
    that as "this entry has no Japanese", never as a reason to fall back to the
    English text: a Japanese CV with one English paragraph in it reads as a
    mistake, and silently mixing them is how it would happen.
    """
    halves = _TRANSLATION_HEADING.split(body, maxsplit=1)
    english = halves[0].strip()
    if len(halves) == 1:
        return english, ""
    return english, _TRANSLATION_NOTE.sub("", halves[1].lstrip(), count=1).strip()


def load_projects_from_md() -> list[dict]:
    """
    Load CV entries from 00_Kazuki/career/cv/{projects,experience}/*.md
    Filters out any entries with 'status: draft' or 'draft: true'.
    """
    import yaml
    from pathlib import Path

    projects = []
    cv_root = _cv_root()
    if cv_root is None:
        return projects

    files = []
    for dirname, kind in _ENTRY_DIRS:
        d = cv_root / dirname
        if d.exists():
            files += [(f, kind) for f in sorted(d.glob("*.md"))]

    for fpath, dir_kind in files:
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
                
                # The body IS the CV entry, in both languages: the English half
                # and the "## 和訳" half are two renderings of one record, and
                # neither may leak into a CV written in the other language.
                description, description_ja = _split_translation(parts[2])

                project = {
                    "id": frontmatter.get("id", fpath.stem),
                    "title": frontmatter.get("title", ""),
                    "role": frontmatter.get("role", ""),
                    "period": str(frontmatter.get("period", "")),
                    "description": description,
                    # "" when the file carries no 和訳 — _entry_description keeps
                    # such an entry off the Japanese CV rather than printing the
                    # English paragraph in its place.
                    "description_ja": description_ja,
                    "tags": frontmatter.get("tags", []),
                    "skills": frontmatter.get("skills", []),
                    # A live URL is the one claim on a CV a reader can check
                    # themselves. Stored canonical, rendered compact.
                    "url": str(frontmatter.get("url", "") or "").strip(),
                    # employment entries render in the fixed EXPERIENCE section;
                    # everything else is a selectable project. The directory
                    # decides; a `type:` line is honoured only as a leftover.
                    "type": str(frontmatter.get("type", dir_kind)).lower(),
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


def get_employment_section(role_type: str = "", lang: str = "en") -> str:
    """Fixed employment/freelance history — never LLM-selected. For a
    portfolio-led CV this is the structural proof of work history; omitting
    the one real employer is the last thing this CV can afford.

    Filtered by tags: an entry with no tags (or an empty list) always shows —
    that's the explicit "relevant to every role" declaration. An entry WITH
    tags only shows when role_type is one of them (e.g. the Real Estate
    Photography internship is tagged [camera_assistant] only, so it must not
    surface in unrelated CVs like Property Underwriter or Family Solicitor)."""
    entries = [p for p in EMPLOYMENT if not p.get("tags") or role_type in p["tags"]]
    return "\n\n".join(_format_project_entry(p, lang) for p in entries
                       if _entry_description(p, lang))

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
    # web_developer's list with the agent-orchestration entry swapped for Asset
    # Weaver: Hermes is backend evidence, and Asset Weaver is the one record that
    # is TypeScript and Node.js AND names interface work — onboarding, progress
    # feedback, error recovery — which is what a front-end post is reading for.
    "frontend_developer": [
        "taifunome-research-platform",
        "portfolio_website",
        "asset-weaver-obsidian-plugin",
        "ai-job-scout-system",
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
        "portfolio_website",
        "hive-floral-pod-3d-conceptual-art",
    ],
    "technical_artist": [
        "feral-bestiary-plate-001",
        "hive-floral-pod-3d-conceptual-art",
        "ai-asset-tagger-system",
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
    # Brand-first order, the reverse of product_designer's build-first one:
    # TAIFUNOME as the studio identity (story, logo, tokens, TAIFU mode),
    # the personal identity mark as the pure mark-making evidence, then the
    # Bestiary plate for illustration and art direction. The Portfolio Website
    # closes it as proof the design reaches a live page.
    "graphic_designer": [
        "taifunome-research-platform",
        "logo-design-for-myself",
        "feral-bestiary-plate-001",
        "portfolio_website",
    ],
    # Bridge roles: the evidence these readers want is a system that had to keep
    # working for someone else — integrations, monitoring, repair — so the
    # shipped platforms lead and the visual work stays on the "Other projects"
    # line. product_ops is the exception: the site itself is the job there, so
    # the Portfolio Website sits second.
    "implementation_specialist": [
        "taifunome-research-platform",
        "ai-job-scout-system",
        "hermes-ai-agent-orchestration-system",
        "portfolio_website",
    ],
    "product_ops": [
        "taifunome-research-platform",
        "portfolio_website",
        "ai-job-scout-system",
        "ai-asset-tagger-system",
    ],
    "qa_engineer": [
        "ai-job-scout-system",
        "taifunome-research-platform",
        "hermes-ai-agent-orchestration-system",
        "portfolio_website",
    ],
    "research_engineer": [
        "taifunome-research-platform",
        "ai-job-scout-system",
        "ai-asset-tagger-system",
        "hermes-ai-agent-orchestration-system",
    ],
    "technical_support": [
        "ai-job-scout-system",
        "hermes-ai-agent-orchestration-system",
        "taifunome-research-platform",
        "web3-node-ops",
    ],
    # web3-node-ops sits SECOND, higher than anywhere else: it is the only entry
    # that is operations rather than construction — nodes someone else's money
    # depended on, kept up over SSH and watched with Prometheus — and an infra
    # reader weighs that above another Python pipeline. It is also the shortest
    # write-up in the bank, so it is the one the page-fill pass can afford to
    # promote when the model leaves the CV short.
    "platform_engineer": [
        "taifunome-research-platform",
        "web3-node-ops",
        "ai-job-scout-system",
        "hermes-ai-agent-orchestration-system",
    ],
    # The general profile also carries the longest PROFILE text, so its four
    # write-ups have to be the short ones or the CV spills onto a third page.
    "general": [
        "ai-asset-tagger-system",
        "portfolio_website",
        "taifunome-research-platform",
        "hive-floral-pod-3d-conceptual-art",
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


def _with_project_url(title_line: str, inner: str) -> str:
    """Append an entry's live URL to its title line, as a clickable link.

    Searches _ALL_ENTRIES rather than PROJECTS: the URL a title line carries
    can belong to either an employment record (EXPERIENCE section) or a
    project record (SELECTED PROJECTS) — TAIFUNOME's own site is on the
    employment line, since that is the one place on the CV that is always
    shown regardless of role type, while the project entry naming the site is
    LLM-selected and not guaranteed to appear at all.

    Applied here rather than in _format_project_entry because the LLM path
    never calls that function — it writes its own entry text — and a URL that
    only appeared on statically-ordered CVs would be missing from most of them.
    Both paths pass through this function, so this is the one place that sees
    every title line, project and employment alike.

    The full address is shown, not a shortened host — a reader opening the
    PDF on a computer can click it, and the text should say what it points
    to rather than make them trust a bare domain.
    """
    head = inner.split(" | ")[0].strip()
    for p in _ALL_ENTRIES:
        if not p.get("url") or _title_key(p["title"]) != _title_key(head):
            continue
        shown = f"[{p['url']}]({p['url']})"
        # Idempotent: this runs over lines that may already carry the address —
        # a CV patched in place, or a body re-finished after padding — and an
        # entry titled "… · [url](url) · [url](url)" is the whole cost of
        # forgetting that.
        if shown in title_line:
            return title_line
        return f"{title_line} · {shown}"
    return title_line


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
            # A URL suffix already appended (" · [url](url)") must not reach
            # the bracket-stripping below — that strips LLM template-placeholder
            # brackets like "[Project Title]" and would eat the link's brackets
            # just as happily, corrupting it into bare unlinked text on every
            # second pass. Nothing else in a title line uses " · ", so split it
            # off first; _with_project_url recomputes it fresh below.
            core = s.split(" · ", 1)[0]
            # drop partial bold + literal [ ] the LLM copies from the prompt's
            # "[Project Title] | [Role] | [Period]" template, then bold the line
            inner = core.replace("**", "").replace("[", "").replace("]", "").strip()
            # the studio name lives in the SELECTED PROJECTS section header —
            # repeating it on every entry line is noise
            inner = inner.replace(" | Taifunomé — Independent Studio", "")
            out.append(_with_project_url(f"**{inner}**", inner))
        else:
            out.append(line.replace("**", ""))
    return "\n".join(out)


def _entry_description(project: dict, lang: str = "en") -> str:
    """The entry's body in the requested language, or "" if it has none.

    Empty is a real answer, not a failure to be papered over. Falling back to
    English here would put one English paragraph in the middle of a Japanese
    CV — the reader cannot tell that from a mistake, and the caller can drop
    the entry instead, which is always the better-looking outcome.
    """
    return (project.get("description_ja") or "") if lang == "ja" else project["description"]


def _format_project_entry(project: dict, lang: str = "en") -> str:
    """Format a single project dict into a CV Experience entry (bold header line).

    The title/role/period header stays as authored in the frontmatter for both
    languages: they are proper nouns and dates ("TAIFUNOME — Research & Creative
    Technology Platform | Independent Studio | 2026 – Present"), and a Japanese
    CV names a project by its own name.
    """
    return f"**{project['title']} | {project['role']} | {project['period']}**\n{_entry_description(project, lang)}"


def _render_entries(project_ids: list, lang: str = "en") -> str:
    """Render entries for the given ids, in order, skipping any that have no
    text in this language."""
    project_map = {p["id"]: p for p in PROJECTS}
    entries = []
    for pid in project_ids:
        p = project_map.get(pid)
        if p and _entry_description(p, lang):
            entries.append(_format_project_entry(p, lang))
    return "\n\n".join(entries)


def _get_static_experience(role_type: str, lang: str = "en") -> str:
    """Build Experience section from static ordering (no LLM)."""
    return _render_entries(
        STATIC_EXPERIENCE.get(role_type, STATIC_EXPERIENCE["general"]), lang)


def _ids_from_experience_body(body: str) -> list[str]:
    """The project ids the model chose, read back off its own output.

    The experience prompt asks for two things and forbids a third: select four
    projects, order them, and do not modify their descriptions. So the only
    part of that answer the model actually authored is the ranking — every
    paragraph under a title is a copy of text this module already holds.

    Reading the ranking back means the Japanese CV can keep the per-posting
    relevance ordering while rendering each paragraph from its source file. No
    model is ever asked to reproduce Japanese verbatim, which is the failure
    this route exists to avoid: an LLM handed a Japanese paragraph and told to
    echo it will quietly smooth it, and a hand-verified translation is exactly
    the thing that must not be smoothed.

    Title lines are identified the same way _bold_experience_titles finds them
    (2+ " | " separators), and matched back by title because that is all the
    output carries — an id the model never saw cannot be echoed.
    """
    by_title = {p["title"].strip().lower(): p["id"] for p in PROJECTS}
    ids: list[str] = []
    for line in (body or "").split("\n"):
        s = line.strip()
        if s.count(" | ") < 2 or s.startswith(("•", "-", "#")):
            continue
        title = s.split(" | ", 1)[0]
        title = title.split(" · ", 1)[0].replace("**", "").replace("[", "").replace("]", "").strip()
        pid = by_title.get(title.lower())
        if pid and pid not in ids:
            ids.append(pid)
    return ids


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
7. TAIFUNOME is the candidate's own platform and the largest body of current
   work — brand, design system, live site, dashboard and data engine, all built
   by them. Rank it FIRST unless the posting is squarely about something it does
   not cover. Every other project is a component next to it; do not drop it to
   the "other projects" line because a smaller piece of tooling matches a
   keyword in the posting more literally.
8. If the job involves front-end/web development, consider including the Portfolio Website project.
9. For product / UX / UI roles (role type product_designer), prioritise
   Portfolio Website, the Identity Mark, Hive Floral Pod, and design-tooling
   work (Asset Weaver). Rank the illustration series (Feral Bestiary) LOW
   unless the posting explicitly asks for illustration, concept art, or
   narrative art direction — it is an art series, not product design work.
9b. For graphic / brand / print / artwork roles (role type graphic_designer)
   the reading is the opposite: these teams judge identity and image-making,
   not interface architecture. Rank TAIFUNOME first (story, logo mark, brand
   architecture, design tokens, the live site and its "TAIFU mode" sequence),
   then the Identity Mark, then Feral Bestiary — the illustration series IS
   the relevant craft evidence here, so it must be written up, not dropped to
   the "other projects" line. Portfolio Website follows as proof the design
   reaches a live page. Do not promote an AI pipeline (Asset Tagger, Asset
   Weaver) over any of those unless the posting is explicitly about automation.
10. For concept-art / illustration / game-art / 3D roles, prioritise Feral
   Bestiary, Arch Viz, and Hive Floral Pod.
11. If the job involves data/automation, prioritize Independent Development.
12. For platform / infrastructure / DevOps / SRE roles (role type
   platform_engineer), Web3 Node Ops MUST be one of the four write-ups and must
   be ranked SECOND, directly after TAIFUNOME. It is the only entry that is
   operating someone else's live services rather than building one's own, which
   is the evidence these readers want; it is short, so it costs little. Do not
   drop it to the "other projects" line because a larger Python project matches
   more keywords.

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


def _other_projects_line(included_text: str, lang: str = "en") -> str:
    """One-line list of every project NOT given a full write-up, so the CV
    always shows the complete project breadth (employers see everything;
    only the depth of description varies).

    Project titles stay in English in both languages — they are names. Only the
    label in front of them is translated; app._md_to_pdf_bytes matches on both
    spellings to give the line its own paragraph in the PDF."""
    rest = [p for p in PROJECTS if p["title"] not in included_text]
    if not rest:
        return ""
    items = " · ".join(f"{p['title']} ({p['period']})" for p in rest)
    label = "その他のプロジェクト" if lang == "ja" else "Other projects"
    return f"**{label}:** {items}"


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


def _bullet_is_unfinished(line: str) -> bool:
    """True when a write-up bullet stops mid-sentence.

    Every bullet in career/cv/projects/*.md ends in terminal punctuation — all
    31 of them, in both languages — so a bullet that does not is not a style
    choice, it is a sentence that was cut off.
    """
    s = line.strip()
    return s.startswith("•") and not re.search(r'[.!?)\]”"。]\s*$', s)


def _project_for_title(title: str) -> dict | None:
    """The project an entry heading names, or None.

    Matched through _title_key rather than by equality because the model
    rewrites headings as it orders them — "My Personal Identity Mark" comes back
    as "Personal Identity Mark" — and the same near-match rule _already_written_up
    uses is the one that has been shown to survive that.
    """
    key = _title_key(title)
    if not key:
        return None
    for p in PROJECTS:
        if _title_key(p["title"]) == key:
            return p
    # A heading the model shortened to the project's leading words: "TAIFUNOME"
    # for "TAIFUNOME — Research & Creative Technology Platform". The word-overlap
    # rule below cannot see it — one word overlapping one word fails its
    # two-word floor — so 40 CVs kept a write-up that every other pass thought
    # it had already rewritten. Only when the prefix names exactly one project,
    # because a shared first word decides nothing.
    starts = [p for p in PROJECTS if _title_key(p["title"]).startswith(key + " ")]
    if len(starts) == 1:
        return starts[0]
    words = {w for w in key.split() if len(w) > 3}
    if not words:
        return None
    for p in PROJECTS:
        p_words = set(_title_key(p["title"]).split())
        if len(words & p_words) >= max(2, len(words) - 1):
            return p
    return None


def _repair_truncated_entries(body: str, lang: str = "en") -> str:
    """Replace any write-up containing a cut-off sentence with its source text.

    A truncated model reply does not look truncated by the time the CV is
    written. The reply stops mid-bullet, the body comes out short, and
    _pad_experience_body then appends whole entries rendered from source to fill
    the page — so the CV arrives full-length and correct-looking, with one
    sentence in the middle that stops after two words. Observed on
    Wondrous_Creations_Web_Artist: "...designed it end to end — positioning,
    logo", and on 40-odd others where the fragment happened to be a prefix of
    the source text.

    Repairing rather than dropping, because the prose was never the model's to
    write: the experience prompt asks it to select and order projects and
    forbids modifying their descriptions, so the source file already holds what
    the bullet was trying to say. An entry whose heading names no project this
    module knows is dropped instead — there is nothing to restore it from, and
    _other_projects_line puts the project back on the breadth line either way.
    """
    entries = []
    for entry in _split_entries(body):
        if not any(_bullet_is_unfinished(l) for l in entry.split("\n")):
            entries.append(entry)
            continue
        heading = entry.split("\n", 1)[0]
        title = heading.split(" | ", 1)[0].split(" · ", 1)[0]
        title = title.replace("**", "").replace("[", "").replace("]", "").strip()
        project = _project_for_title(title)
        if project and _entry_description(project, lang):
            entries.append(_format_project_entry(project, lang))
    return "\n\n".join(entries)


def _experience_body(job_title: str = "", job_description: str = "",
                     role_type: str = "general", lang: str = "en") -> str:
    """The write-up entries alone — LLM-ordered when a description is available,
    static otherwise, with the known bad shapes stripped out."""
    body = None
    if job_description and len(job_description) > 50:
        body = _generate_experience_ollama(job_title, job_description, role_type)

    if lang == "ja":
        # Keep the model's ranking, discard its prose: every paragraph is
        # re-read from the entry's own 和訳 (see _ids_from_experience_body). The
        # three strippers below are not needed on this path and are not run —
        # they exist to catch things a model wrote into the output, and on this
        # path nothing in the output was written by one.
        selected = _ids_from_experience_body(body)[:4] if body else []
        return _render_entries(selected, "ja") or _get_static_experience(role_type, "ja")

    if not body:
        body = _get_static_experience(role_type)

    body = _strip_llm_other_lines(body)
    body = _strip_echoed_job_title(body, job_title)
    body = _strip_fabricated_employment(body)
    return _repair_truncated_entries(body)


def _finish_experience(body: str, lang: str = "en") -> str:
    """Bold the entry titles and append the canonical "Other projects" line."""
    section = _bold_experience_titles(body)
    other = _other_projects_line(body, lang)
    return f"{section}\n\n{other}" if other else section


# A CV is written to fill two A4 pages: four write-ups is the usual count, but
# the entries differ in length, so four SHORT ones leave the bottom third of
# page two blank. Measured at the 10mm page margin, static path, all roles:
# 1145 words still lands on two pages, 1159 spills onto a third. Words are only
# a proxy — what actually fills the page is line count, and a heading plus a
# short entry costs lines a long paragraph does not — so leave headroom rather
# than aiming at the observed edge.
_CV_TARGET_WORDS = 1080
_CV_MAX_WORDS = 1120

# Every promoted entry costs a title line and a blank line on top of its words.
# At roughly ten words to a rendered line that is ~20 words of page space the
# word count never sees, which is how a CV of 1143 words spilled one line onto
# a third page while a 1167-word one fitted: it had more entries, not more text.
_ENTRY_LINE_COST = 20

# The same budget for the Japanese CV, counted in characters because Japanese
# writes no spaces between words: str.split() reports a full ja CV as ~200
# "words" no matter how long it is, so the word budget above cannot see it at
# all and would pad every ja CV to the maximum.
#
# Measured the same way, web_developer/ja through the live renderer: 5562
# characters still lands on two pages, 5607 spills onto a third. Characters are
# the same kind of proxy words are — a four-entry CV of 5522 spilled while a
# three-entry one of 5562 did not, because the extra title line costs page
# space no character count sees — so the ceiling sits below the observed edge
# and the entry cost is charged separately, exactly as _ENTRY_LINE_COST is.
_CV_JA_MAX_CHARS = 5450
# ~45 characters to a rendered line, and a promoted entry costs its title line
# plus the blank line above it.
_ENTRY_LINE_COST_JA = 90


def _fit_japanese(exp_body: str, cv_body: str) -> str:
    """Drop write-ups from the end until the ja CV is back inside two pages.

    Only the write-ups are elastic — profile, employment and toolkit are fixed —
    and the entries are in relevance order, so the last is the cheapest to lose.
    It is not lost: _other_projects_line rebuilds itself from whatever is no
    longer written up, so the project still appears, just without its paragraph.

    Trimming only, never padding. The ja route has no measured target to pad
    towards, and a short CV reads as a short CV, where a third page reads as a
    CV that was not edited.
    """
    entries = _split_entries(exp_body)
    excess = len(cv_body) - _CV_JA_MAX_CHARS
    while excess > 0 and len(entries) > _CV_MIN_ENTRIES:
        excess -= len(entries.pop()) + _ENTRY_LINE_COST_JA
    return "\n\n".join(entries)


def _title_key(title: str) -> str:
    """A project title reduced to what identifies it, for match-anything checks.

    The LLM rewrites entry titles as it orders them, and a leading possessive is
    the first thing it drops: the project titled "My Personal Identity Mark"
    comes back as "Personal Identity Mark". A plain substring test misses that,
    so the padding pass read the project as missing and appended it a second
    time — three of the last hundred CVs shipped the same project twice.
    """
    key = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    key = re.sub(r"^(my|the|a|an) ", "", key.strip())
    return re.sub(r"\s+", " ", key).strip()


def _already_written_up(title: str, body: str) -> bool:
    """Whether an entry for this project is already in the experience body."""
    key = _title_key(title)
    if not key:
        return False
    if key in _title_key(body):
        return True
    # A heavier paraphrase still keeps the distinctive words. Compare against
    # each entry heading rather than the prose, so an incidental mention in
    # someone else's write-up does not suppress a real entry.
    words = {w for w in key.split() if len(w) > 3}
    if not words:
        return False
    for head in re.findall(r"^\*\*(.+?)\*\*", body, re.MULTILINE):
        head_words = set(_title_key(head).split())
        if len(words & head_words) >= max(2, len(words) - 1):
            return True
    return False


def _pad_experience_body(body: str, needed_words: int, role_type: str) -> str:
    """Promote further projects into full write-ups until the CV fills the page.

    Candidates come from the role's static ordering first (its ranking is the
    considered one) and then the remaining projects, so padding stays relevant
    rather than arbitrary. Adds nothing that would overshoot the two-page band.
    """
    if needed_words <= 0:
        return body

    project_map = {p["id"]: p for p in PROJECTS}
    ordered_ids = list(STATIC_EXPERIENCE.get(role_type, STATIC_EXPERIENCE["general"]))
    ordered_ids += [p["id"] for p in PROJECTS if p["id"] not in ordered_ids]

    budget = needed_words + (_CV_MAX_WORDS - _CV_TARGET_WORDS)
    for pid in ordered_ids:
        if needed_words <= 0:
            break
        p = project_map.get(pid)
        if not p or _already_written_up(p["title"], body):
            continue  # already written up
        entry = _format_project_entry(p)
        cost = len(entry.split()) + _ENTRY_LINE_COST
        if cost > budget:
            continue  # would push past the two-page ceiling — try a shorter one
        body = f"{body}\n\n{entry}"
        needed_words -= cost
        budget -= cost
    return body


# Never cut below this many write-ups. A CV showing one project reads as a thin
# candidate rather than a tight one, whatever the page count says.
_CV_MIN_ENTRIES = 3


def _split_entries(body: str) -> list[str]:
    """The experience body as a list of whole entries (title line + its text)."""
    entries: list[str] = []
    for block in re.split(r"\n\s*\n", body.strip()):
        s = block.strip()
        if not s:
            continue
        first = s.split("\n", 1)[0].strip()
        is_title = first.count(" | ") >= 2 and not first.startswith(("•", "-", "#"))
        if is_title or not entries:
            entries.append(s)
        else:
            entries[-1] = f"{entries[-1]}\n\n{s}"  # continuation of the entry above
    return entries


def _shorten_entry(entry: str, excess_words: int) -> tuple[str, int]:
    """Drop trailing bullets from one entry, keeping its title and first bullet.

    Returns the shortened entry and the words still to find.
    """
    lines = entry.split("\n")
    bullet_idx = [i for i, l in enumerate(lines) if l.strip().startswith("•")]
    # Keep the first bullet: an entry reduced to a bare title line reads as a
    # project someone forgot to describe, which is worse than not writing it up.
    while excess_words > 0 and len(bullet_idx) > 1:
        cut = bullet_idx.pop()
        excess_words -= len(lines[cut].split())
        del lines[cut]
    return "\n".join(lines), excess_words


def _trim_experience_body(body: str, excess_words: int, min_entries: int = _CV_MIN_ENTRIES) -> str:
    """Drop write-ups from the end until the CV is back inside the page budget.

    The entries are in relevance order, so the last one is the cheapest to lose,
    and it is not lost — _other_projects_line rebuilds itself from whatever is
    no longer written up, so the project still appears, just without its
    paragraph.

    Below min_entries the unit of removal changes from the entry to the bullet.
    Dropping whole write-ups is the right first move and the wrong last one:
    once three are left there is nothing further to give up, so the CV simply
    shipped long — 1188 and 1152 words on 2026-08-18, against a 1120 ceiling
    and a measured spill at 1145. Bullets are the finer instrument. They come
    off the back of the least relevant entry first, and never off the first
    entry, which gen_version pins as TAIFUNOME on every CV.
    """
    entries = _split_entries(body)
    while excess_words > 0 and len(entries) > min_entries:
        dropped = entries.pop()
        excess_words -= len(dropped.split()) + _ENTRY_LINE_COST
    for i in range(len(entries) - 1, 0, -1):
        if excess_words <= 0:
            break
        entries[i], excess_words = _shorten_entry(entries[i], excess_words)
    return "\n\n".join(entries)


def generate_experience(job_title: str = "", job_description: str = "", role_type: str = "general") -> str:
    """
    Generate the Experience section for a CV: the most relevant projects in
    full (LLM-ordered when a description is available, static otherwise) plus
    a compact one-line list of all remaining projects.
    """
    return _finish_experience(_experience_body(job_title, job_description, role_type))


def generate_cv(role_type: str = "general", job_title: str = "", company: str = "", job_description: str = "", match_filename: str = "", cl_filename: str = "", lang: str = "en") -> str:
    """Generate a complete CV for a specific role type and job.

    lang="ja" assembles the CV from the "## 和訳" half of every source record
    instead of the English half. Nothing is translated at generation time: the
    Japanese is read from files a human wrote and checked, and the only thing a
    model contributes is which four projects to lead with (see
    _ids_from_experience_body). A record with no 和訳 is omitted rather than
    printed in English.
    """
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

    profile = get_profile(role_type, lang)
    strengths = get_strengths(role_type)
    toolkit = get_toolkit(role_type)
    exp_body = _experience_body(job_title, job_description, role_type, lang)
    role_title = get_header(role_type)
    template = MASTER_CV_JA if lang == "ja" else MASTER_CV

    def _assemble(experience_section: str) -> str:
        return template.format(
            candidate_name=CONTACT["name"],
            candidate_name_ja=CONTACT["name_ja"],
            contact_line=header_line("en"),
            contact_line_ja=header_line("ja"),
            links_line=links_line(),
            role_title=role_title,
            profile=profile,
            employment=_bold_experience_titles(get_employment_section(resolved_role, lang)),
            technical_toolkit=_bold_toolkit_headers(toolkit),
            experience=experience_section
        )

    experience = _finish_experience(exp_body, lang)
    cv_body = _assemble(experience)
    if lang == "ja":
        # Characters, not words — see _CV_JA_MAX_CHARS.
        trimmed = _fit_japanese(exp_body, cv_body)
        if trimmed != exp_body:
            exp_body = trimmed
            experience = _finish_experience(exp_body, lang)
            cv_body = _assemble(experience)
    else:
        # Only the write-ups are elastic; everything else (profile, employment,
        # toolkit) is fixed, so the shortfall is measured on the whole CV and paid
        # for by promoting another project. Re-uses the LLM's own ordering — no
        # second model call.
        shortfall = _CV_TARGET_WORDS - len(cv_body.split())
        if shortfall > 0:
            padded = _pad_experience_body(exp_body, shortfall, role_type)
            if padded != exp_body:
                exp_body = padded
                experience = _finish_experience(exp_body, lang)
                cv_body = _assemble(experience)
        # And the other direction. Padding could only ever add, so when the model
        # wrote long the CV simply shipped at three pages — six of the last hundred
        # did. Dropping the least relevant write-up is not a loss of breadth: the
        # project moves to the "Other projects" line, which is computed from
        # whatever is not written up.
        elif len(cv_body.split()) > _CV_MAX_WORDS:
            trimmed = _trim_experience_body(exp_body, len(cv_body.split()) - _CV_MAX_WORDS)
            if trimmed != exp_body:
                exp_body = trimmed
                experience = _finish_experience(exp_body, lang)
                cv_body = _assemble(experience)

    # Scan experience text to determine which projects were used
    used_projects = []
    for p in PROJECTS:
        p_title = p.get("title", "")
        p_id = p.get("id", "")
        if p_title and p_id and p_title.lower().strip() in experience.lower():
            used_projects.append(f"[[career/cv/projects/{p_id}]]")
            
    import json
    source_projects_yaml = f"\nsource_projects: {json.dumps(used_projects, ensure_ascii=False)}" if used_projects else ""

    # Which keywords picked this profile, recorded per CV. A misroute used to be
    # invisible unless someone read the headline and thought "that is the wrong
    # job" — with this line, `grep '^role_evidence: "body:' 10_output/10_cvs/*.md`
    # lists every CV whose discipline was decided without title evidence.
    _, role_evidence = detect_role_type_with_evidence(job_title, job_description)

    frontmatter = f"""---
title: "{company} - {job_title} (CV)"
type: "cv"
company: "{company}"
match_report: "[[{match_filename}]]"
cover_letter: "[[{cl_filename}]]"
source_profile: "[[career/cv/profile/{resolved_role}]]"
role_evidence: "{role_evidence}"{source_projects_yaml}
---
"""
    
    # The CV body now leads with "# Kazuki Yunome" as the H1 — the job/company
    # is kept in the frontmatter `title:` for Obsidian, not as a giant heading.
    return f"{frontmatter}\n{cv_body}"

if __name__ == "__main__":
    import sys
    role = sys.argv[1] if len(sys.argv) > 1 else "general"
    print(generate_cv(role))