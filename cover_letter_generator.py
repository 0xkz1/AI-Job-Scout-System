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
    "name": "Kazuki Yunomé",
    "location": "Edinburgh, Scotland, UK",
    "email": "CANDIDATE_EMAIL",
    "phone": "CANDIDATE_PHONE",
    "portfolio": "http://kazukiyunome.com/",
    "github": "https://github.com/0xkz1",
    "linkedin": "https://www.linkedin.com/in/kazukiyunome/"
}

from datetime import date
import re


# Industry/sector words that turn a neutral sentence into a claim of domain
# experience. The persona summary names no client sector at all, so pairing one
# of these with a first-person experience verb asserts work the candidate has
# not done — exactly how "I've built similar systems for financial platforms"
# ended up in an AJ Bell letter (AJ Bell is a financial services firm; the
# reviewer correctly flagged it as fabrication). Describing what the EMPLOYER
# does is legitimate, so the check below is scoped to first-person claim
# sentences rather than the paragraph as a whole.
_SECTOR_TERMS = (
    "financial", "finance", "fintech", "banking", "insurance", "healthcare",
    "health care", "medical", "clinical", "pharmaceutical", "pharma", "legal",
    "law firm", "government", "public sector", "retail", "e-commerce",
    "ecommerce", "logistics", "automotive", "aerospace", "defence", "defense",
    "telecom", "telecommunications", "energy", "oil and gas", "utilities",
    "education", "edtech", "gaming", "gambling", "casino", "travel",
    "hospitality", "real estate", "manufacturing", "construction",
    "agriculture", "biotech", "charity", "nonprofit", "non-profit",
)

# First-person assertions of past work. Deliberately narrow: it must read as
# "I did this", not merely "I can" or "I am interested in".
_FIRST_PERSON_CLAIM = re.compile(
    r"\b(?:I(?:'ve|’ve| have)?\s+"
    r"(?:built|worked|designed|developed|delivered|led|created|shipped|managed|supported)"
    r"|my\s+(?:experience|background|work|practice)\s+(?:in|with|across|for))\b",
    re.IGNORECASE,
)


def _claims_unsupported_sector(text: str, persona: str) -> str | None:
    """Return the offending sector term if `text` asserts first-person
    experience in an industry the persona never mentions, else None.

    Fail-safe by design: a rejected opening falls back to the role template's
    static opening, which contains no invented claims. A false positive costs
    one generic paragraph; a false negative ships a factual misrepresentation
    to an employer, so the check errs toward rejection.
    """
    persona_l = persona.lower()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if not _FIRST_PERSON_CLAIM.search(sentence):
            continue
        sentence_l = sentence.lower()
        for term in _SECTOR_TERMS:
            if term in sentence_l and term not in persona_l:
                return term
    return None


# Nouns that, in a cover-letter opening, describe the WRITER's own practice —
# never the employer's. "your team"/"your platform"/"your mission" are normal
# ways to address the reader, but "your approach to design"/"your background"
# is the letter talking to the applicant instead of from them.
_CANDIDATE_ATTRIBUTES = (
    "approach", "background", "practice", "experience", "skill", "skills",
    "expertise", "portfolio", "focus on blending", "workflow of", "process of",
)
_INVERTED_PERSON = re.compile(
    r"\b[Yy]our\s+(?:own\s+)?(?:" + "|".join(_CANDIDATE_ATTRIBUTES) + r")\b"
)
# "You've built …", "You have designed …" — a past-work verb aimed at the reader
# is describing the candidate, since the employer's history is not the subject.
_INVERTED_PERSON_VERB = re.compile(
    r"\b[Yy]ou(?:['’]ve| have)?\s+"
    r"(?:built|designed|developed|created|delivered|shipped|engineered)\b"
)


def _has_inverted_person(text: str) -> str | None:
    """Return the offending phrase when the opening addresses the CANDIDATE as
    "you", else None.

    Kept as a rule rather than folded into the LLM check: asking one model call
    to judge both fabrication and person made it unreliable at both — it began
    flagging ordinary employer address ("your team needs…") while letting a
    fabricated project through. Person inversion has a narrow, decidable
    surface form, so it is matched directly and the model is left to do only
    the semantic job it is actually needed for.
    """
    for pat in (_INVERTED_PERSON, _INVERTED_PERSON_VERB):
        m = pat.search(text)
        if m:
            return m.group(0)
    return None


def _verify_opening_claims(text: str) -> str | None:
    """Second-pass fact check of an LLM-written opening. Returns a short reason
    when a claim is unsupported, else None.

    _claims_unsupported_sector catches invented INDUSTRY experience by keyword,
    but not invented projects: "I designed the visual pipeline for a remote
    compute platform handling high-resolution AI-generated assets" survives
    every keyword test — the persona genuinely mentions a "Remote Compute
    Desktop (Japan)" — while describing delivered client work that never
    happened. Telling a personal machine apart from a shipped project is
    semantic, so it needs a model; running it only on openings that actually
    assert something keeps it to one extra call on a minority of letters.

    Fails OPEN on API/parse errors: an outage should degrade to the previous
    behaviour (opening kept; the reviewer still fact-checks downstream) rather
    than silently strip the tailored paragraph out of every letter.
    """
    if not _FIRST_PERSON_CLAIM.search(text):
        return None  # asserts nothing about past work — nothing to verify
    try:
        from llm_client import call_llm
        facts = _load_verification_record()
        if not facts:
            return None
        prompt = f"""Check the opening paragraph of a cover letter. The candidate WROTE this letter; the reader is the employer.

VERIFIED RECORD (the ONLY things this candidate has actually done):
{facts}

PARAGRAPH:
{text}

Report a problem ONLY for FABRICATION: a claim about the candidate's own past work that
is absent from the verified record.

The candidate's record is made of SELF-DIRECTED projects plus a short employment history.
So the test is not "was this self-directed?" — it is "does the record show this work, and
does the paragraph describe WHO it was done for correctly?"

REPORT these:
- A named project/system that is not in the record, or that the record shows doing
  something different from what the paragraph claims.
- Work attributed to a CLIENT, EMPLOYER, or PLATFORM the record does not show. Both
  "I designed brand identities for <employer>" and "during my work at <employer>" are
  fabrication unless the record lists that employer. Reframing the candidate's own
  machine, vault, or plugin as something delivered for someone else is fabrication too.
- Named clients, employers, industries, or scale figures absent from the record.
- An asserted FIELD, DISCIPLINE, or DOMAIN of past work the record does not show —
  "my work in packaging design", "my background in motion graphics", "years spent in
  editorial design". Vague phrasing is not a licence.
- A real project bent to a BENEFICIARY or PURPOSE the record does not show. The record's
  knowledge system is the candidate's own; "I built a knowledge infrastructure for pupils"
  is fabrication because the record shows no pupils. Same for "pipelines for hospital
  staff", "a workflow for retail teams". Check who the record says the work served, and
  report any paragraph that hands it to someone else — the resemblance of the underlying
  system does not license the new audience.

Do NOT report these:
- Naming one of the candidate's OWN documented projects and describing what it does, as
  the record describes it, with no client attached. "In developing the AI Job Scout
  System, I designed a multi-agent workflow" is honest and correct.
- Describing what the EMPLOYER does, or addressing the employer as "you"/"your".
- Describing HOW the candidate works — their approach, principles, or interests.

The decisive question for any piece of past work: does the record contain it, and does
the paragraph claim it was done for someone the record does not name?

Reply with exactly one line:
OK
or
PROBLEM: <the specific fabricated claim, under 15 words>"""
        verdict = (call_llm(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You verify cover-letter openings strictly. Reply in the requested one-line format only.",
            temperature=0.0,
            max_tokens=80,
        ) or "").strip()
        if verdict.upper().startswith("PROBLEM"):
            return verdict.split(":", 1)[-1].strip()[:120] or "unsupported claim"
        return None
    except Exception as e:
        print(f"  ⚠ CL opening verification skipped ({e})")
        return None


_verify_record_cache: str | None = None


def _load_verification_record() -> str:
    """The candidate's concrete work record, for checking an opening's claims.

    reviewer._load_review_facts() leads with ~13k characters of ethos and design
    philosophy before reaching any project — so truncating it (as this check did)
    dropped the project records entirely and the verifier rejected honest
    mentions of real projects as unrecorded. Feeding it untruncated then buried
    the instructions and the verifier passed everything.

    Verification only needs what can be checked: which projects exist, what each
    one did, and who it was for. The philosophy is not evidence, so it is left
    out and the record stays small enough for the model to actually use.
    """
    global _verify_record_cache
    if _verify_record_cache is not None:
        return _verify_record_cache
    try:
        from cv_generator import load_projects_from_md
        employment, projects = [], []
        for p in load_projects_from_md():
            title = (p.get("title") or "").strip()
            if not title:
                continue
            head = f"### {title}"
            role = (p.get("role") or "").strip()
            period = str(p.get("period") or "").strip()
            meta = " | ".join(x for x in (role, period) if x)
            if meta:
                head += f"\n({meta})"
            body = (p.get("description") or "").strip()
            entry = f"{head}\n{body}"
            (employment if p.get("type") == "employment" else projects).append(entry)
        parts = [
            "The candidate is portfolio-led: the projects below are SELF-DIRECTED work "
            "carried out under their own studio unless an employer is named in the entry. "
            "That is normal and legitimate — it is not a reason to doubt a claim."
        ]
        if employment:
            parts.append("## EMPLOYMENT (the only employers on record)\n" + "\n\n".join(employment))
        if projects:
            parts.append("## PROJECTS (self-directed unless stated)\n" + "\n\n".join(projects))
        _verify_record_cache = "\n\n".join(parts)
    except Exception as e:
        print(f"  ⚠ verification record load failed ({e})")
        _verify_record_cache = ""
    return _verify_record_cache


_projects_digest_cache: str | None = None


def _first_sentence(description: str, limit: int = 200) -> str:
    """Opening sentence of a project body, stripped of markdown, for the digest."""
    line = next((l for l in description.split("\n") if l.strip()), "")
    line = re.sub(r"^\s*[•\-\*]\s*", "", line)
    line = re.sub(r"\*\*|\*|`", "", line).strip()
    if len(line) > limit:
        cut = line[:limit].rsplit(" ", 1)[0]
        line = cut + "…"
    return line


def _load_projects_digest() -> str:
    """Compact one-line-per-project digest for the opening-hook prompt.

    The opening previously saw only the ethos (persona truncated at 2500 chars,
    which ethos.md alone fills), so every letter recited the same ethos headings
    with no concrete work to anchor to. This surfaces the real projects so the
    model can pick ONE that fits each posting and ground the ethos in something
    specific and different per job.

    Each entry carries a line of what the project actually IS. Title and skills
    alone were not enough to choose by: nine of twenty-five openings reached for
    "AI Job Scout System" and eight for "AI Asset Tagger System" regardless of
    the role, while the design, illustration, photography and infrastructure work
    went unused — the model was matching on how technical a name sounded rather
    than on what the project was.
    """
    global _projects_digest_cache
    if _projects_digest_cache is not None:
        return _projects_digest_cache
    try:
        from cv_generator import load_projects_from_md
        lines = []
        for p in load_projects_from_md():
            title = (p.get("title") or "").strip()
            if not title or not p.get("cover_letter", True):
                continue  # real work, but not developed enough to pitch with
            role = (p.get("role") or "").strip()
            skills = [s for s in (p.get("skills") or []) if s and s.strip()]
            skill_str = ", ".join(skills[:6])
            head = f"- {title}"
            if role:
                head += f" ({role})"
            lines.append(head)
            summary = _first_sentence(p.get("description") or "")
            if summary:
                lines.append(f"    what it is: {summary}")
            if skill_str:
                lines.append(f"    skills: {skill_str}")
        _projects_digest_cache = "\n".join(lines)
    except Exception as e:
        print(f"  ⚠ projects digest load failed ({e}); opening will use ethos only")
        _projects_digest_cache = ""
    return _projects_digest_cache


# For visual-design roles the model kept reaching for the AI pipelines (Asset
# Tagger, Asset Weaver) because their records are the most detailed — leaving an
# Audio-Visual Designer or a Packaging Designer pitched on an image-tagging tool.
# These hints steer each role toward the projects that actually demonstrate the
# relevant craft. They only reorder preference; the model still picks one real
# project and every fabrication gate still applies.
_ROLE_PROJECT_HINTS = {
    "product_designer":
        "FOR THIS ROLE: it is a design role. Prefer the design-forward projects — "
        "My Personal Identity Mark (visual identity), Hive Floral Pod (3D concept "
        "design), the Portfolio Website (design + build), Feral Research (design of "
        "a living archive). Reach for an AI pipeline (Asset Tagger, Asset Weaver) "
        "ONLY if the posting is explicitly about automation or AI tooling; a "
        "graphic/brand/packaging/motion/AV design role is better served by the "
        "visual and product work.",
    "technical_artist":
        "FOR THIS ROLE: prefer work showing craft plus pipeline — Hive Floral Pod "
        "(3D), Feral Bestiary work, the Portfolio Website, or a tooling project "
        "only where the posting is pipeline-focused.",
    "camera_assistant":
        "FOR THIS ROLE: prefer the photography work (Real Estate Photography, the "
        "Architectural & Wildlife Photography practice). Do not lead with software "
        "pipelines.",
    "web_developer":
        "FOR THIS ROLE: prefer the Portfolio Website (front-end build) and the "
        "engineering projects (AI Job Scout System, Feral Research, node ops).",
}


def _role_project_hint(role_type: str) -> str:
    return _ROLE_PROJECT_HINTS.get(role_type, "")


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
        projects_digest = _load_projects_digest()
        role_type = detect_role_type(job_title, job_description)
        role_hint = _role_project_hint(role_type)
        prompt = f"""Write the OPENING paragraph of a cover letter (3-4 sentences, at most 80 words).

THE JOB:
Company: {company}
Title: {job_title}
Posting (excerpt): {job_description[:2000]}

THE CANDIDATE (ethos = the backbone of the whole letter):
{persona[:8000]}

THE CANDIDATE'S REAL PROJECTS (the only concrete work you may cite — pick ONE):
{projects_digest}
{role_hint}

HOW TO WRITE THIS OPENING (follow in order):
1. Read the posting and decide which ONE of the candidate's ethos principles it most resonates with — e.g. "Building Tools That Amplify Human Creativity", "Craft × Structure", "Reduce Friction Between Idea and Execution", or "Knowledge as Infrastructure". Different jobs should surface different principles; do not default to the same one every time.
2. Pick the ONE real project from the list above that best fits this specific role, and name it.
   Choose on what the project IS ("what it is:" line), not on how technical its name sounds.
   A graphic design, branding or illustration post is better served by the illustration,
   identity, 3D or portfolio-site work than by an AI pipeline; a photography post by the
   photography work; an infrastructure or ops post by the node-ops or orchestration work.
   The list holds sixteen projects across design, illustration, photography, web and
   infrastructure — do not keep reaching for the same two or three AI systems.
3. Judge how much this posting actually reveals about the EMPLOYER'S OWN work. Recruitment agencies and thin postings often say nothing about it — in that case you must NOT describe what the employer does, because you would be guessing.
4. Choose the first sentence to fit what you found in step 3:
   - Employer's work is clearly described → you may open from it, then pivot to the candidate.
   - Employer's work is unclear, or the poster is an agency hiring for a client → open from the candidate's own practice or from the concrete demands of the ROLE ITSELF, never from an invented account of the employer.
   Vary the construction. Do not open every letter with "Your work at X … resonates with my approach"; that frame is one option among several, not a formula.
5. Open with that sentence, anchor it to the one named project, and connect both to this posting's actual focus. The result must read as written for THIS job — a reader comparing two of these letters should see different principles, different projects, different opening moves.

RULES:
- First person, UK English, plain prose. No markdown, no bullet points, no heading.
- The candidate is the WRITER, not the reader. Write "I"/"my" for the candidate; "you"/"your" may refer ONLY to the employer. Never describe the candidate's own work as "your work" — that inverts the letter.
- Reference something CONCRETE and specific from this posting (their product, mission, tech stack, or the role's actual focus) and connect it to the candidate's real background.
- Do NOT fabricate experience or qualifications not in the candidate profile.
- NEVER claim the candidate has worked in the employer's industry or sector (finance, healthcare, retail, legal, government, gaming, …) unless the candidate profile explicitly says so. Constructions like "I've built similar systems for financial platforms", "my experience with healthcare clients", or "having worked in retail" are FORBIDDEN unless verbatim supported by the profile above.
- You may describe what the EMPLOYER does in their sector; you may not assert that the candidate has done it too. Connect via the candidate's documented approach and process, not via invented domain experience.
- Do NOT invent a project, client, or deliverable. If you describe a specific piece of past work, it must be one named in the projects list above, described as it is described there. Never reframe the candidate's personal tooling or hardware (their own compute machine, their own vault, their own plugins) as work delivered for someone else.
- Never mention relocation or moving, and never claim the candidate lives in, is near, or is moving to the employer's city. The candidate is based in Edinburgh; the job's location is irrelevant to the opening.
- Ground the connection in the candidate's actual process or outcomes (systems thinking, automation, design rigor) — not literal tools or hardware (tablets, specific input devices, software names) unless the posting explicitly calls for them. Backstage implementation details do not belong in an opening paragraph.
- Avoid recycling the ethos headings verbatim as filler ("reduce friction between idea and execution", "craft and structure", "tools that amplify human creativity"). Express the chosen principle through the specific project and this posting, in your own words.
- BANNED phrases — do not use any of these or close paraphrases; they have become a tic across letters: "disappear into the workflow", "tools that disappear", "invisible infrastructure", "invisible scaffolding", "amplify intent without demanding attention", "extend intent without demanding attention", "serve the work rather than". Say what the project concretely did instead.
- Keep it TIGHT: 3-4 sentences, 80 words maximum. A tight opening reads sharper than a long one; do not pad to fill space.
- No clichés ("I was excited to see", "I am writing to apply", "passionate about"), no flattery filler.
- Do not include the greeting line; the letter template already has "Dear Hiring Team".

Output ONLY the paragraph."""
        # The opening is written at temperature 0.5, so a draft that trips a gate
        # is often just an unlucky roll — the same job frequently produces a clean
        # opening on a re-draft. Giving up to the template after one try inflated
        # the fallback rate (≈45%) without meaning the job COULDN'T be personalised.
        # So we re-draft a few times, keeping every gate strict, and only fall back
        # when the model genuinely can't produce a clean opening.
        attempts = _OPENING_ATTEMPTS
        last_reason = "no clean draft"
        salvageable = None  # best draft rejected only on presentation, not honesty
        for attempt in range(1, attempts + 1):
            text = call_llm(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="You write concise, specific, honest cover-letter openings. Output only the requested paragraph.",
                temperature=0.5,
                max_tokens=300,
            )
            text = (text or "").strip().strip('"')
            ok, result, kind = _vet_opening(text, company, persona)
            if ok:
                return result
            last_reason = result  # a short why-rejected string
            # A draft rejected only for being over the word cap is HONEST — it
            # passed every fabrication, person and sector gate. Falling back to
            # the generic template throws away a truthful, tailored paragraph to
            # avoid a paragraph that is merely long, which is the worse trade.
            # Keep the shortest such draft and use it if no clean one arrives.
            if kind == "presentation" and text:
                if salvageable is None or len(text.split()) < len(salvageable.split()):
                    salvageable = text
        if salvageable:
            print(f"  ⓘ CL opening: 語数超過だが内容は健全 "
                  f"({len(salvageable.split())}語); テンプレより優先して採用")
            return salvageable
        print(f"  ⚠ CL opening: {attempts}回とも不合格 ({last_reason}); using template opening")
        return None
    except Exception as e:
        print(f"  ⚠ CL opening hook generation failed ({e}); using template opening")
        return None


# How many times to re-draft an opening before falling back to the template.
_OPENING_ATTEMPTS = 3
# The prompt asks for ≤80 words, but the model clusters around 90-110 and a tight
# cap just burned the retry budget and fell back to a generic template — worse
# than a slightly-long tailored opening. Cap only the genuinely bloated (130+
# originally seen); the prompt still pushes for brevity within that.
_OPENING_MAX_WORDS = 110
# Ethos lines the model overuses verbatim across letters — each becomes a tic
# once the previous one is banned, so they are rejected at the gate too.
_BANNED_PHRASES = (
    "disappear into the workflow", "tools that disappear", "tools to disappear",
    "invisible infrastructure", "invisible scaffolding",
    "amplify intent without demanding attention",
    "extend intent without demanding attention",
    "without demanding attention",
    "reduce friction between idea and execution",
)


def _vet_opening(text: str, company: str, persona: str) -> tuple[bool, str, str]:
    """Run every opening gate.

    Returns (True, clean_text, "") or (False, reason, kind), where kind marks
    what sort of failure it was:
      "honesty"      — fabrication, wrong person, unclaimed sector, malformed.
                       Never usable; the template must be used instead.
      "presentation" — the paragraph is truthful and well-formed but breaks a
                       stylistic rule (currently only the word cap). The caller
                       may keep it rather than fall back to a generic template.
    """
    # --- Honesty and well-formedness gates first ---
    # Everything below must pass before a draft can be considered salvageable;
    # the word cap is checked LAST so "presentation" can only ever mean "this
    # paragraph is truthful and well-formed, just long".
    if not (120 <= len(text) <= 1000):
        return False, "length", "honesty"
    if any(m in text for m in ("\n\n", "- ", "• ", "#", "Dear ")):
        return False, "not a single plain paragraph", "honesty"
    # Banned ethos-tic phrases: once one recurring filler line was dropped the
    # model latched onto the next ("disappear into the workflow", "amplify intent
    # without demanding attention"). Reject and re-draft so each opening earns its
    # specificity instead of reciting the same ethos sentence.
    low = text.lower()
    hit = next((p for p in _BANNED_PHRASES if p in low), None)
    if hit:
        return False, f"banned filler phrase ({hit})", "honesty"
    # (No company-name requirement: it assumed company == the addressee, but for
    # the many recruitment-agency postings the company IS the agency, and the
    # prompt correctly tells the model to address the CLIENT or the role instead
    # of the agency. Requiring the agency's name rejected exactly those correct
    # openings — e.g. a Robert Walters posting for Ofgem that named Ofgem. The
    # remaining gates plus the prompt's specificity demand cover quality.)
    # Voice gate: an opening that never says "I" reads as a letter addressed TO
    # the applicant, not from them — unusable however factual.
    if not re.search(r"(?:^|\s)(?:I|I['’](?:m|ve|d|ll)|[Mm]y)\b", text):
        return False, "not first person", "honesty"
    inverted = _has_inverted_person(text)
    if inverted:
        return False, f"inverted person ({inverted})", "honesty"
    offending = _claims_unsupported_sector(text, persona)
    if offending:
        return False, f"unsupported '{offending}' experience", "honesty"
    unsupported = _verify_opening_claims(text)
    if unsupported:
        return False, f"unsupported claim ({unsupported})", "honesty"

    # --- Presentation gate, checked last ---
    # The prompt asks for ≤80 words and the model tends to run long. Reject so a
    # tighter re-draft is attempted, but flag it as presentation-only: by this
    # point the paragraph has cleared every honesty gate, so the caller may keep
    # it rather than fall back to a generic template.
    if len(text.split()) > _OPENING_MAX_WORDS:
        return False, f"too long ({len(text.split())} words)", "presentation"
    return True, text, ""


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