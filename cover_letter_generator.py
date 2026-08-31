# Cover Letter Generator
# ======================
# Generates tailored cover letters based on job description and detected role type

from cv_generator import detect_role_type

# No date line: app.py stamps one at PDF-render time, so a letter drafted
# weeks ago still goes out dated the day it is actually sent.
MASTER_COVER_LETTER = """{name}
{location} | {email} | {phone}

Hiring Team
{company}
{job_location}

Dear Hiring Team,

{letter_body}

Yours sincerely,
{name}"""

# Read from the environment rather than written here — see contact_details. The
# keys are the ones this module already used, so every {name}/{phone} reference
# downstream is unchanged.
from contact_details import CONTACT as _CONTACT

PERSONAL_INFO = {
    "name": _CONTACT["name"],
    "location": _CONTACT["location"],
    "email": _CONTACT["email"],
    "phone": _CONTACT["phone"],
    "portfolio": _CONTACT["portfolio"],
    "github": _CONTACT["github"],
    "linkedin": _CONTACT["linkedin"],
}

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

    Fail-safe by design: a rejected bridge falls back to the static one, which
    contains no invented claims. A false positive costs one generic paragraph;
    a false negative ships a factual misrepresentation to an employer, so the
    check errs toward rejection.
    """
    persona_l = persona.lower()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        claim = _FIRST_PERSON_CLAIM.search(sentence)
        if not claim:
            continue
        # Only what follows the claim verb can be its object. A context bridge
        # names the employer first and reaches the candidate's own work later in
        # the same sentence — "Wordsmith AI's work on legal drafting feels
        # relevant to the way I built TAIFUNOME" — so scoping to the sentence
        # read the employer's own sector as a claim about the candidate and
        # rejected the bridge. That cost the top-ranked postings their bridges
        # first, since the best matches are real companies in named sectors.
        claimed = sentence[claim.start():].lower()
        for term in _SECTOR_TERMS:
            if term in claimed and term not in persona_l:
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


# "work at <employer>" appears in two opposite sentences, and the verifier model
# cannot reliably tell them apart:
#
#   "YOUR work at Lloyds Banking Group to prototype…"   ← addressing the reader
#   "during MY work at Lloyds Banking Group…"           ← claiming to have worked there
#
# The writing prompt explicitly invites the first when the posting describes the
# employer's work; the verifier reported it as fabrication on every one of three
# runs, and adding a paragraph to the verifier prompt explaining the possessive
# did not move it — it still rejected the honest sentence and the dishonest one
# identically. Whose work it is, is decided by the word in front of it, so decide
# it here instead of asking.
_EMPLOYER_ADDRESS = re.compile(
    r"\b(?:your|the)\s+(?:\w+\s+){0,3}?work\s+(?:at|with|for)\b"
    r"|\bwork\s+(?:you|your team)\b",
    re.IGNORECASE,
)
_CANDIDATE_EMPLOYMENT_CLAIM = re.compile(
    r"\b(?:my|our)\s+(?:\w+\s+){0,3}?(?:work|time|role|experience)\s+(?:at|with)\b"
    r"|\bI\s+(?:\w+\s+){0,2}?work(?:ed|ing)?\s+(?:at|for|with)\b"
    r"|\b(?:during|while|when)\s+(?:I|my)\b",
    re.IGNORECASE,
)


def _is_employer_address_false_positive(reason: str, text: str) -> bool:
    """True when the verifier flagged 'work at <employer>' that is the READER's.

    Deliberately narrow: it only forgives a verdict that is ABOUT working at some
    employer, and only when the paragraph addresses that work to the reader and
    never claims it in the first person. A paragraph containing both forms keeps
    the rejection — the dishonest half is the one that matters.
    """
    # The verdict wording varies run to run for the same input — "work at X",
    # "employment claim", "worked for X" — so match on the subject it is about
    # rather than one phrasing of it.
    if not re.search(r"\bwork(?:ed|ing)?\s+(?:at|for|with)\b|\bemploy(?:ment|er|ed)\b",
                     reason, re.IGNORECASE):
        return False
    if _CANDIDATE_EMPLOYMENT_CLAIM.search(text):
        return False
    return bool(_EMPLOYER_ADDRESS.search(text))


def _verify_opening_claims(text: str, document_label: str = "opening paragraph") -> str | None:
    """Second-pass fact check of an LLM-written candidate claim. Returns a short
    reason when a claim is unsupported, else None.

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
        prompt = f"""Check this {document_label} of a cover letter. The candidate WROTE this letter; the reader is the employer.

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
  "I designed brand identities for <employer>" and "during MY work at <employer>" are
  fabrication unless the record lists that employer. Reframing the candidate's own
  machine, vault, or plugin as something delivered for someone else is fabrication too.
- Named clients, employers, industries, or scale figures absent from the record.
- EVIDENCE BOUNDARY VIOLATION: A past action, method, result, or experience attributed
  to the candidate (e.g., user testing, usability testing, customer validation, user
  research, A/B testing, testing user flows) that is not explicitly supported by the
  record. Claims about what the candidate WOULD DO in the future are acceptable;
  claiming they ALREADY did it without evidence is fabrication. Never allow inferred UX
  practices just because the job description asks for them.
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
        # The model sometimes bolds its own verdict ("**PROBLEM: …**") despite
        # being asked for one plain line, and a startswith("PROBLEM") test then
        # read it as OK — so the fabrications it caught were the ones that got
        # through, silently, which is the worst direction for this check to fail
        # in. Strip the emphasis before deciding.
        verdict = verdict.strip("*_ ").strip()
        if verdict.upper().startswith("PROBLEM"):
            reason = verdict.split(":", 1)[-1].strip().strip("*_ ")[:120] or "unsupported claim"
            if _is_employer_address_false_positive(reason, text):
                return None
            return reason
        return None
    except Exception as e:
        print(f"  ⚠ CL {document_label} verification skipped ({e})")
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


# Some projects are evidence only for postings that ask for that craft. Each
# entry pairs the words that name the project with the words a posting uses when
# it actually wants it; naming the project to a posting that does neither is the
# letter stretching to fill a paragraph.
#
# An illustration series is only evidence for a posting that wants pictures made.
# Asked to open a Lloyds Banking Group creative-technologist letter, the model
# bridged the posting's word "storytelling" to a series about animals abandoned
# in war zones and offered it as evidence of customer-centred design. Three
# re-drafts of a strengthened prompt still produced it twice, and a logo pitched
# at the same kind of role followed within a day. Evidence selection is now a
# table lookup rather than a model's choice (see letter_facts_v1.md), so this
# check no longer guards the evidence blocks — it guards the one place a model
# can still name a project, the context bridge.
_NARROW_CRAFT_PROJECTS = (
    (
        "illustration series",
        ("feral bestiary", "bestiary"),
        ("illustration", "illustrator", "concept art", "concept artist",
         "art direction", "art director", "visual development", "character design",
         "storyboard", "drawing", "painting", "sketch", "comic", "animation",
         "editorial art",
         # Job titles that are art jobs without using any of the words above:
         # an "Art Technician" advert for a school describes preparing materials
         # and supporting lessons, and named none of them.
         "art technician", "art teacher", "art department", "fine art",
         "artist", "atelier", "studio art"),
    ),
    (
        "identity/logo work",
        ("identity mark", "logo design", "personal identity"),
        ("brand identity", "logo", "identity design", "visual identity", "branding",
         "brand designer", "brand design", "graphic design", "graphic designer",
         "typography", "rebrand", "brand guidelines", "marketing materials",
         "art direction", "packaging"),
    ),
)


def _cites_narrow_craft_without_cause(text: str, job_description: str,
                                      job_title: str = "") -> str | None:
    """A craft credit offered to a posting that never asks for that craft.

    Returns a short reason, or None. Judged on the posting's own words rather
    than the detected role type: a creative-technologist posting CAN be
    image-making or brand work, and when it is, the project is the right thing
    to cite.

    The TITLE counts as part of the posting. An "Art Technician" advert whose
    body talks only about supporting lessons and preparing materials contains
    none of the signal words, and judging the body alone rejected an
    illustration credit offered to a school art department — the one posting in
    the batch where it was plainly the right credit to offer.
    """
    low = text.lower()
    posting = f"{job_title} {job_description or ''}".lower()
    for label, mentions, signals in _NARROW_CRAFT_PROJECTS:
        mention = next((m for m in mentions if m in low), None)
        if mention and not any(s in posting for s in signals):
            return f"{label} ({mention})"
    return None


def _load_evidence_bank() -> list[dict]:
    """Build a deterministic evidence bank from the CV source of truth.

    The model may choose between records, but it must never be asked to infer
    the candidate's history from prose. The record is intentionally small:
    title, period, role, and the source description are the only facts a letter
    generator can draw from.
    """
    try:
        from cv_generator import load_projects_from_md
        bank = []
        for index, project in enumerate(load_projects_from_md(), start=1):
            title = (project.get("title") or "").strip()
            description = (project.get("description") or "").strip()
            if not title or not description or not project.get("cover_letter", True):
                continue
            bank.append({
                # Short codes are deliberate. Asking a local model to reproduce
                # a long title containing punctuation exactly made valid plans
                # look invalid even when it selected the right project.
                "id": f"E{index:02d}",
                # The entry's own id in career/cv/**. letter_facts_v1.md is
                # keyed by it, so a fact whose CV entry was deleted or marked
                # cover_letter: false stops being selectable on its own.
                "source_id": (project.get("id") or "").strip(),
                "title": title,
                "role": (project.get("role") or "").strip(),
                "period": str(project.get("period") or "").strip(),
                "kind": "employment" if project.get("type") == "employment" else "self-directed project",
                "facts": description,
            })
        return bank
    except Exception as e:
        print(f"  ⚠ CL evidence bank load failed ({e})")
        return []


# ---------------------------------------------------------------------------
# The assembler
#
# A letter is assembled from blocks, not authored. Only one block is written by
# a model, and it is two sentences long:
#
#   1. opening    static  — which role, which company
#   2. canonical  static  — who the candidate is (canonical_narrative_v1.md)
#   3. evidence   locked  — 1-2 fact blocks from letter_facts_v1.md
#   4. bridge     LLM     — why this company, what could be contributed
#   5. closing    static  — one sentence, appended to the bridge paragraph
#
# The predecessor asked a model to draft, critique and rewrite the whole letter.
# That put the candidate's identity inside the generation loop, so it drifted
# per company, and every fabrication gate had to police the entire text. Here
# the identity is a file. The gates only have to police two sentences.
# ---------------------------------------------------------------------------

_LETTER_MIN_WORDS = 250
_LETTER_MAX_WORDS = 400
# A bridge is two sentences and they are the last two sentences of the letter,
# so they carry the ending. 85 was the cap while a static closing followed them
# and could absorb the slack; without it, a bridge that runs to 85 words is a
# paragraph trailing off rather than a letter finishing.
_BRIDGE_MAX_WORDS = 65
_BRIDGE_MAX_SENTENCES = 2
# Three, not two: the filler gates below are strict on purpose, and a rejection
# is cheap — the expensive verification call only runs on a draft that has
# already cleared every text check.
_BRIDGE_ATTEMPTS = 4
# Below this, a posting says nothing a bridge could be grounded in, and the
# static bridge is the honest output.
_BRIDGE_MIN_DESCRIPTION = 600

_OPENING_TEMPLATE = "I am writing to apply for the {job_title} position at {company}."

# Opens the second evidence block. Deliberately the weakest connective there
# is: the two blocks are chosen independently, so anything stronger ("Likewise",
# "In the same way") would assert a link the selection never established.
_EVIDENCE_CONNECTIVES = ("Separately,", "Elsewhere,")

# The filler gates, in two tiers.
#
# _BANNED_PHRASES was tuned when a model wrote the whole letter and had ~300
# words to fill. Applying all ninety of it to a two-sentence bridge did not work
# twice over: the model cannot hold a ninety-phrase prohibition, and the checks
# that policed padding across four paragraphs ("ensuring that", "user feedback")
# reject ordinary phrasing when there are only two sentences to say anything in.
# Three drafts in a row died on it and the letter fell back to the static
# bridge — a stricter gate producing a blander letter.
#
# What survives here is every phrase from that list that is still empty inside
# two sentences, split by whether the posting's own vocabulary can excuse it.
# The honesty gates below (_verify_opening_claims, _claims_unsupported_sector,
# _has_inverted_person) are unchanged and are what actually keeps the letter
# truthful; these two lists only keep it from sounding like everyone else's.

# Flattery and self-description. A posting saying these is no licence to say
# them back: "passionate about" in a job ad describes what they want to hear,
# not what their product is.
_BRIDGE_NEVER_ECHO = (
    "passionate about", "excited to see", "i am excited about",
    "i am looking forward to", "i look forward to", "make an impact",
    "valuable asset", "asset to the team", "strong fit", "strong candidate",
    "good fit", "unique approach", "wealth of experience",
    "aligns with", "aligns closely", "aligns perfectly", "resonates with",
    "is what draws me", "logical next step", "logical next environment",
    "innovative culture", "fast-paced environment", "dynamic environment",
    "i believe my background", "i believe my skills", "i am drawn to",
    "contribute my skills and experience", "drive business growth",
    "drive business value", "directly addressed by", "delightful",
    "highly sophisticated",
    # Overstated connectors. "mirrors" asserts that the employer's work and the
    # candidate's method have the same structure, which is more than either
    # party can know from a job ad. The letter is a filter, not a pitch: it can
    # afford to say the connection "feels relevant" and let the reader decide.
    "mirrors", "directly enables", "directly matches", "perfectly matches",
    "is a perfect", "is a natural fit", "maps directly", "translates directly",
)

# Empty abstraction, and the tics this candidate's letters kept reaching for.
# Allowed only when the posting itself uses the phrase about its own work,
# because then it is quotation rather than reaching.
_BRIDGE_STYLE_BANS = (
    "disappear into the workflow", "tools that disappear", "tools to disappear",
    "invisible infrastructure", "invisible scaffolding",
    "without demanding attention", "reduce friction", "without friction",
    "friction between idea and execution", "friction between intent and execution",
    "deployment-agnostic", "without sacrificing", "without losing touch",
    "accelerates product", "accelerate product design",
    "accelerate product transformation", "engineered an end-to-end",
    "end-to-end platform", "end-to-end process", "systems-thinking background",
    "production-ready", "proved that", "measurable outcomes",
    "user satisfaction", "business efficiency", "exceptional ui", "exceptional ux",
    "high-leverage", "shared infrastructure", "cohesive framework",
    "scalable", "seamless", "cutting-edge", "intuitive and effective",
)


# A comparison back to the candidate's own past work, tacked onto the end of the
# contribution sentence: "I would propose refining the design system's
# modularity, as I did in connecting research domains under a single engine."
# The canonical narrative and the evidence block have already made that case, so
# the clause spends the letter's last words arguing something the reader has
# just read. Scoped to the final sentence only — the first sentence reaching
# back ("feels relevant to the way I built TAIFUNOME") is the bridge working.
_BACKWARD_CLOSE = re.compile(
    r"\b(?:just |much |exactly )?(?:as|like)\s+I\s+(?:already\s+)?"
    r"(?:did|have\s+done|['’]ve\s+done|had\s+done"
    r"|built|designed|created|developed|shipped|wrote|made|ran|led)\b",
    re.IGNORECASE,
)


# A definite reference to a system the employer is presumed to have. "I would
# refine how new client requirements integrate into the platform's modular
# architecture" went to a posting whose 8,500 words never say platform,
# architecture, modular, codebase or infrastructure — the letter told them
# something about their own engineering that it had no way to know. The prompt
# already forbids inventing a description of the employer; this catches the form
# that slips through, where a definite article presupposes the thing exists.
_EMPLOYER_SYSTEM = re.compile(
    r"\b(?:your|their|the)\s+(?:[\w-]+\s+){0,2}"
    r"(platform|architecture|codebase|infrastructure|design system|tech stack|"
    r"backend|frontend|pipeline|ecosystem|toolchain|product suite)"
    r"(?:['’]s)?\b",
    re.IGNORECASE,
)


def _asserts_an_unstated_employer_system(text: str, job_description: str) -> str | None:
    """Return the presumed system noun the posting never mentions, else None."""
    posting = (job_description or "").lower()
    for match in _EMPLOYER_SYSTEM.finditer(text):
        noun = next(group for group in match.groups() if group)
        if noun.lower() in posting:
            continue
        # "the pipeline I built" is the candidate's own work, not a claim about
        # the reader's, so a first-person continuation withdraws the objection.
        if re.match(r"\s*(?:i\b|i['’]|my\b)", text[match.end():match.end() + 24], re.I):
            continue
        return noun
    return None


def _closes_by_restating_the_candidates_past(text: str) -> str | None:
    """Return the backward-looking clause closing the bridge, else None."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    if len(sentences) < 2:
        return None
    match = _BACKWARD_CLOSE.search(sentences[-1])
    return match.group(0).strip() if match else None


# "align" in every form. Kept as a stem rather than a phrase because the model
# routes around a phrase list: told not to write "aligns with", it produced
# "aligned", then "alignment". A posting using the word is no excuse — it is the
# emptiest connector in the genre, and the sentence it appears in is always
# "your X aligns with my Y", which states no cause.
_BRIDGE_ALIGN = re.compile(r"\balign(?:s|ed|ing|ment|ments)?\b", re.IGNORECASE)

# Tool and library names. The CV lists the whole stack already, and the reader
# has it in front of them — naming Cursor and Claude Code in the bridge spends
# the letter's last two sentences on a toolbar. What belongs here is the work,
# and the tools it happens to be done with are the least transferable part of it.
_BRIDGE_TOOL_NAMES = (
    "cursor", "claude code", "copilot", "chatgpt", "midjourney", "comfyui",
    "figma", "sketch", "blender", "procreate", "illustrator", "photoshop",
    "affinity", "indesign", "after effects", "premiere", "darktable",
    "obsidian", "notion", "sanity", "webflow", "wordpress",
    "python", "typescript", "javascript", "react", "node.js", "gsap",
    "ollama", "chromadb", "redis", "postgres", "postgresql", "docker",
    "kubernetes", "playwright", "selenium", "heroku", "cloudflare",
    "prometheus", "grafana", "tmux",
)


def _bridge_names_a_tool(text_low: str) -> str | None:
    """The tool name this bridge reaches for, or None."""
    return next((name for name in _BRIDGE_TOOL_NAMES
                 if re.search(r"(?<![\w.])" + re.escape(name) + r"(?![\w])", text_low)),
                None)


def _bridge_banned_hit(text_low: str, job_description: str) -> str | None:
    """The banned phrase this bridge uses, or None."""
    posting = (job_description or "").lower()
    align = _BRIDGE_ALIGN.search(text_low)
    if align:
        return align.group(0)
    for phrase in _BRIDGE_NEVER_ECHO:
        if phrase in text_low:
            return phrase
    for phrase in _BRIDGE_STYLE_BANS:
        if phrase in text_low and phrase not in posting:
            return phrase
    return None


# "your work"/"your plugin" naming one of the candidate's own projects. This is
# the person inversion that _has_inverted_person exists to catch, in the one
# form it misses: "work" is deliberately absent from _CANDIDATE_ATTRIBUTES
# because "your work at <employer>" is a legitimate way to address the reader.
# It stops being ambiguous once the sentence also names a project that belongs
# to the candidate — "Your work translating research into modular systems, like
# TAIFUNOME" is the letter handing the candidate's own platform to the reader.
_READER_OWNED_WORK = re.compile(
    r"\byour\s+(?:own\s+)?(?:\w+\s+){0,2}?"
    r"(?:work|project|projects|build|builds|system|systems|tool|tools|"
    r"plugin|plugins|pipeline|pipelines|platform|"
    # "Your focus on integrating research, design and code into a single
    # workflow" is the canonical narrative's own sentence, handed to the reader.
    r"focus|method|methodology|workflow|ownership|way of working)\b",
    re.IGNORECASE,
)


_PARROT_NGRAM = 7


def _parrots_the_posting(text: str, job_description: str) -> str | None:
    """Return the span the bridge copied out of the posting, or None.

    Handing an employer their own sentence back is the oldest tell in the genre,
    and this candidate's letters had a specific version of it: Bending Spoons
    says "human judgment and machine intelligence reinforce each other", and the
    letter said it too, as though it were an observation. The prompt has asked
    the model not to do this since the first draft; asking has never been enough.

    Seven words is long enough that an accidental collision does not happen —
    shared vocabulary is words and pairs, not clauses.
    """
    def _words(source: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", (source or "").lower())

    bridge_words = _words(text)
    if len(bridge_words) < _PARROT_NGRAM:
        return None
    posting_words = _words(job_description)
    posting_grams = {
        tuple(posting_words[i:i + _PARROT_NGRAM])
        for i in range(len(posting_words) - _PARROT_NGRAM + 1)
    }
    for i in range(len(bridge_words) - _PARROT_NGRAM + 1):
        gram = tuple(bridge_words[i:i + _PARROT_NGRAM])
        if gram in posting_grams:
            return " ".join(gram)
    return None


def _candidate_project_names(evidence: list[dict]) -> list[str]:
    """Distinctive names for the candidate's own work, for the inversion check.

    Taken from the evidence bank titles up to the em dash, which is where the
    short name ends ("Asset Weaver — Obsidian Plugin"). Generic heads such as
    "Portfolio Website Design & Development" never appear verbatim in a bridge,
    so they cost nothing; the distinctive ones are the whole point.
    """
    names = {"TAIFUNOME"}
    selected = {item["source_id"] for item in evidence}
    for record in _load_evidence_bank():
        if record.get("source_id") not in selected:
            continue
        head = re.split(r"\s*[—–-]\s*", record.get("title", ""), maxsplit=1)[0].strip()
        if len(head) >= 5 and any(ch.isupper() for ch in head):
            names.add(head)
    return sorted(names)


def _opens_by_giving_the_reader_the_candidates_method(text: str) -> str | None:
    """Return the offending opening when the bridge starts "Your focus…".

    Five of six bridges written against real postings opened this way:

        "Your focus on translating complex systems into clear structures feels
         relevant to Pine Tree Barn's work of guiding customers…"

    "your" is the employer, so the sentence tells the employer that their own
    focus is relevant to their own work. The candidate has vanished. It is the
    prompt's own target sentence with the subject inverted — the model kept the
    "feels relevant to" frame and put the wrong party in front of it.

    Scoped to the opening rather than to "your" anywhere: addressing the reader
    mid-bridge ("I would bring that to your team") is how the letter is supposed
    to read, and only the subject position produces this failure.
    """
    match = _READER_OWNED_WORK.match(text.strip())
    return match.group(0) if match else None


def _attributes_candidate_work_to_reader(text: str, evidence: list[dict]) -> str | None:
    """Return the offending phrase when the bridge calls the candidate's own
    project the reader's work, else None."""
    names = [n.lower() for n in _candidate_project_names(evidence)]
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        match = _READER_OWNED_WORK.search(sentence)
        if not match:
            continue
        low = sentence.lower()
        if any(name in low for name in names):
            return match.group(0)
    return None


def _normalise_bridge(text: str) -> str:
    """Strip the formatting a model adds to two sentences of plain prose.

    Bold around project names and a paragraph break between the two sentences
    are presentation habits, not claims. Rejecting a truthful draft over them
    spent a retry and pushed otherwise good letters onto the static bridge, so
    they are removed instead of vetted.
    """
    cleaned = (text or "").strip().strip('"').strip("“”")
    cleaned = re.sub(r"^```(?:\w+)?\s*|\s*```$", "", cleaned).strip()
    cleaned = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", cleaned)
    cleaned = cleaned.replace("`", "")
    # "Barclays's effort", "Motorola Solutions's work": the model defaults to
    # 's on every possessive, including names that already end in s. UK style
    # takes the bare apostrophe there ("Barclays'"); this is spelling, not a
    # claim, so it is fixed rather than grounds to reject the draft.
    cleaned = re.sub(r"(\w+s)['’]s\b", r"\1’", cleaned)
    # A bridge is one paragraph. The two sentences arriving on separate lines is
    # the model laying out the two numbered instructions it was given.
    return " ".join(cleaned.split())

# There is no closing line. "I would welcome the chance to talk through where
# this could be most useful to you" was a third sentence that added nothing the
# two before it had not already said — a stock sign-off after four paragraphs
# that had earned a real ending. The letter finishes on the contribution.

# Used when the posting is too thin to ground a bridge, or when every generated
# bridge fails vetting. It claims nothing about the employer, so it is always
# safe to send — the letter degrades in specificity, never in truthfulness.
_STATIC_BRIDGE = ("I am applying to {company} because I would like to put this way of "
                  "working inside a team rather than run it alone. I would bring the "
                  "same method: build the smallest version that works, then let what it "
                  "reveals decide the next step.")

_canonical_narrative_cache: str | None = None
_letter_facts_cache: list[dict] | None = None


def _cover_letter_dir():
    """Locate career/cover-letter/, which holds the authored letter assets."""
    from pathlib import Path

    candidates = [
        Path(__file__).resolve().parent.parent / "cover-letter",
        Path("/media/kz003/atelier/00_Kazuki/career/cover-letter"),
        Path("/home/kz003/atelier/00_Kazuki/career/cover-letter"),
    ]
    return next((p for p in candidates if p.is_dir()), None)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter, body) for a `---`-delimited markdown file."""
    import yaml

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    return (yaml.safe_load(parts[1]) or {}), parts[2]


def _load_canonical_narrative() -> str:
    """The immutable identity paragraphs, verbatim.

    No model sees this text as something to improve. It is read, cached and
    concatenated. A failure to load returns "" and the caller refuses to build
    a letter at all — a letter missing its identity block is worse than none.
    """
    global _canonical_narrative_cache
    if _canonical_narrative_cache is not None:
        return _canonical_narrative_cache
    _canonical_narrative_cache = ""
    directory = _cover_letter_dir()
    if directory is None:
        print("  ⚠ CL canonical narrative: cover-letter directory not found")
        return ""
    path = directory / "canonical_narrative_v1.md"
    if not path.exists():
        print(f"  ⚠ CL canonical narrative missing ({path})")
        return ""
    try:
        _, body = _split_frontmatter(path.read_text(encoding="utf-8"))
        # Everything before "## Narrative" is editing guidance for the author,
        # and the trailing "## 和訳" is a reference translation. Neither is
        # letter text.
        match = re.search(r"^##\s*Narrative\s*$(.*?)(?=^##\s|\Z)", body,
                          re.M | re.S)
        section = (match.group(1) if match else "").strip()
        # The source file is hard-wrapped so it stays readable and diffable.
        # The letter is not: a paragraph is one line, or it sits in the output
        # next to the unwrapped evidence blocks looking like two different
        # documents stapled together.
        _canonical_narrative_cache = "\n\n".join(
            " ".join(para.split())
            for para in re.split(r"\n\s*\n", section) if para.strip()
        )
        if not _canonical_narrative_cache:
            print("  ⚠ CL canonical narrative: no '## Narrative' section")
    except Exception as e:
        print(f"  ⚠ CL canonical narrative load failed ({e})")
    return _canonical_narrative_cache


def _load_letter_facts() -> list[dict]:
    """Locked, letter-ready phrasings of CV entries, keyed by CV entry id.

    Kept apart from the CV entries themselves because the two are written for
    different readers: a CV bullet is scanned, a letter fact is read inside a
    sentence. Concatenating bullets into prose is what produced markdown
    artefacts and CV register in the letter body.
    """
    global _letter_facts_cache
    if _letter_facts_cache is not None:
        return _letter_facts_cache
    _letter_facts_cache = []
    directory = _cover_letter_dir()
    if directory is None:
        return []
    path = directory / "letter_facts_v1.md"
    if not path.exists():
        print(f"  ⚠ CL letter facts missing ({path})")
        return []
    try:
        frontmatter, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
        for item in (frontmatter.get("facts") or []):
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("id") or "").strip()
            fact = " ".join(str(item.get("fact") or "").split())
            if not source_id or not fact:
                continue
            _letter_facts_cache.append({
                "source_id": source_id,
                "fact": fact,
                "tier": str(item.get("tier") or "core").strip().lower(),
                "group": str(item.get("group") or "").strip().lower(),
                "roles": [str(r).strip().lower() for r in (item.get("roles") or [])],
                "keywords": [str(k).strip().lower() for k in (item.get("keywords") or [])],
            })
    except Exception as e:
        print(f"  ⚠ CL letter facts load failed ({e})")
        _letter_facts_cache = []
    return _letter_facts_cache


def _select_evidence(job_title: str, job_description: str, role_type: str,
                     limit: int = 3) -> list[dict]:
    """Choose the evidence blocks deterministically.

    No model is involved. The same role type always draws the same evidence for
    the same posting, which is the property the previous LLM selection could not
    give: two applications for the same job title stopped citing two different
    halves of the same record.

    A fact is eligible only while its CV entry is still in the evidence bank, so
    deleting a CV entry, or marking it cover_letter: false, silently withdraws
    the fact rather than leaving orphaned prose in circulation.
    """
    facts = _load_letter_facts()
    if not facts:
        return []
    live = {item.get("source_id") for item in _load_evidence_bank() if item.get("source_id")}
    facts = [f for f in facts if f["source_id"] in live]
    if not facts:
        print("  ⚠ CL evidence: no letter fact matches a live CV entry")
        return []

    role = (role_type or "general").lower()
    eligible = [f for f in facts if role in f["roles"]]
    if not eligible:
        eligible = [f for f in facts if "general" in f["roles"]]
    if not eligible:
        eligible = facts

    posting = f"{job_title} {job_description}".lower()
    scored = []
    for index, fact in enumerate(eligible):
        hits = sum(1 for k in fact["keywords"] if k and k in posting)
        # index is the tie-breaker, so file order is the author's stated
        # preference and the outcome never depends on dict iteration order.
        scored.append((-hits, index, fact))
    scored.sort(key=lambda row: (row[0], row[1]))

    # At most one fact per group. TAIFUNOME has both a platform record and a
    # studio record, and picking both spent two paragraphs reintroducing the
    # same thing the canonical narrative had already named.
    #
    # The first block is always a core one — method and ownership, which is what
    # the letter is for. A technical or operational block joins it only when the
    # posting's own words reach for it, because the CV already carries the stack
    # and a letter that repeats it has spent a paragraph saying nothing new.
    chosen, used_groups = [], set()

    def _take(fact: dict) -> None:
        chosen.append(fact)
        if fact["group"]:
            used_groups.add(fact["group"])

    def _available(rows):
        # scored holds NEGATED hits so one sort key orders it; undo that here so
        # every caller below reads a plain count and `hits > 0` means what it says.
        return [(-negated, fact) for negated, _, fact in rows
                if fact not in chosen
                and not (fact["group"] and fact["group"] in used_groups)]

    core = [(hits, fact) for hits, fact in _available(scored) if fact["tier"] == "core"]
    if core:
        _take(core[0][1])

    # One slot is then RESERVED for proof, when the posting reaches for any.
    #
    # Core blocks carry the broad vocabulary — brand, design system, product,
    # content — so they outscore the narrower technical ones on almost every
    # posting. Measured over 300 design postings before this reserve existed,
    # 247 letters came out core+core and only 53 carried a single block saying
    # what was actually built; raising the limit to 3 moved that to 64, because
    # the extra slot went to a third core block. A letter of three method
    # paragraphs is the failure the Lothian Buses letter was hand-written to
    # escape, and it escaped by naming artefacts.
    #
    # `hits > 0` still gates it: a posting that never reaches for the stack
    # gets no reserve, and the slot returns to the general fill below.
    proof = [(hits, fact) for hits, fact in _available(scored)
             if fact["tier"] != "core" and hits > 0]
    if proof and len(chosen) < limit:
        _take(proof[0][1])

    # Recomputed each pass rather than iterated once. _available() reads
    # used_groups, so a list materialised before the loop cannot see a group the
    # loop itself adds. This was unreachable while the limit was 2 — the loop
    # ran at most once — and became a live defect at 3, where it let both
    # kazukiyunome.com build blocks into one letter despite their shared group:
    # two engineering paragraphs about a single website, in 5 of 300 measured
    # design postings.
    while len(chosen) < limit:
        rows = [(hits, fact) for hits, fact in _available(scored)
                if fact["tier"] == "core" or hits > 0]
        if not rows:
            break
        _take(rows[0][1])
    return chosen


def _vet_bridge(text: str, persona: str, job_title: str, job_description: str,
                evidence: list[dict] | None = None) -> tuple[bool, str]:
    """Gate the only model-written block in the letter.

    Everything else in the letter is authored text that a human already
    approved, so there is nothing to check there and no reason to spend a
    verification call on it. All of the fabrication risk is concentrated in
    these two sentences.
    """
    stripped = text.strip()
    if not stripped:
        return False, "empty"
    words = len(stripped.split())
    if words > _BRIDGE_MAX_WORDS:
        return False, f"too long ({words} words)"
    sentences = len(re.findall(r"[.!?](?:\s|$)", stripped))
    if sentences > _BRIDGE_MAX_SENTENCES:
        return False, f"{sentences} sentences, must be {_BRIDGE_MAX_SENTENCES}"
    if any(marker in stripped for marker in ("•", "\n-", "#", "**", "Dear ", "Yours sincerely")):
        return False, "contains formatting or letter framing"
    low = stripped.lower()
    hit = _bridge_banned_hit(low, job_description)
    if hit:
        return False, f"banned filler phrase ({hit})"
    tool = _bridge_names_a_tool(low)
    if tool:
        return False, f"names a tool the CV already lists ({tool})"
    if "independent venture" in low or "long-term ambition" in low:
        return False, "mentions an exit plan"
    if not re.search(r"(?:^|\s)(?:I|I['’](?:m|ve|d|ll)|[Mm]y)\b", stripped):
        return False, "not first person"
    inverted = _has_inverted_person(stripped)
    if inverted:
        return False, f"inverted person ({inverted})"
    parroted = _parrots_the_posting(stripped, job_description)
    if parroted:
        return False, f"quotes the posting back ({parroted})"
    handed_over = _opens_by_giving_the_reader_the_candidates_method(stripped)
    if handed_over:
        return False, f"opens by calling the candidate's own method theirs ({handed_over})"
    presumed = _asserts_an_unstated_employer_system(stripped, job_description)
    if presumed:
        return False, f"assumes an employer {presumed} the posting never mentions"
    looks_back = _closes_by_restating_the_candidates_past(stripped)
    if looks_back:
        return False, f"closes by restating work already given ({looks_back})"
    misattributed = _attributes_candidate_work_to_reader(stripped, evidence or [])
    if misattributed:
        return False, (f"calls the candidate's own project the reader's "
                       f"({misattributed})")
    offending = _claims_unsupported_sector(stripped, persona)
    if offending:
        return False, f"unsupported '{offending}' experience"
    stretched = _cites_narrow_craft_without_cause(stripped, job_description, job_title)
    if stretched:
        return False, f"{stretched} cited for a posting that does not ask for it"
    pcts = re.findall(r"\d+(?:\.\d+)?\s*%", low)
    if pcts:
        record = (_load_verification_record() or "").lower()
        missing = [p for p in pcts if p not in record
                   and p.replace(" ", "") not in record.replace(" ", "")]
        if missing:
            return False, f"unverified metric ({', '.join(missing)})"
    unsupported = _verify_opening_claims(stripped, "context bridge")
    if unsupported:
        return False, f"unsupported claim ({unsupported})"
    return True, ""


def _generate_context_bridge(job_title: str, company: str, job_description: str,
                             canonical: str, evidence: list[dict],
                             persona: str, rejected: str = "") -> str | None:
    """Write the two sentences that connect a fixed identity to one posting.

    The model is given the finished identity text and the selected evidence as
    read-only context. It is not asked to summarise either — restating them is
    the failure mode, because the reader has just read them.
    """
    try:
        from llm_client import call_llm

        evidence_text = "\n".join(f"- {item['fact']}" for item in evidence)
        # The gate and the instruction read from the same list. Hand-writing a
        # shorter list of forbidden phrases in the prompt meant the model was
        # rejected three times running for "production-ready" and "ensuring the"
        # — phrases it had never been told to avoid.
        banned = ", ".join(f'"{p}"' for p in _BRIDGE_NEVER_ECHO + _BRIDGE_STYLE_BANS)
        # Retries used to resend the identical prompt, so the model produced the
        # identical draft and burned all three attempts on the same rejected
        # phrase. Naming the fault is what makes a second attempt an attempt.
        correction = ""
        if rejected:
            correction = (f"\nEVERY PREVIOUS ATTEMPT WAS REJECTED, for: {rejected}.\n"
                          "Those faults are cumulative — a new draft must avoid all of "
                          "them at once. Do not rephrase around a banned word; say "
                          "something concrete instead.\n")
        prompt = f"""Write the CONTEXT BRIDGE of a UK-English cover letter: exactly two sentences.
{correction}

THE POSTING
Company: {company}
Role: {job_title}
{job_description[:4000]}

WHAT THE READER HAS ALREADY READ (do not summarise, repeat or paraphrase any of it)
{canonical}

{evidence_text}

These are the LAST TWO SENTENCES OF THE LETTER. Nothing follows them — no sign-off line, no offer to talk, no "I would welcome the chance to". The second sentence has to be able to end the letter on its own.

THE TWO SENTENCES, in this order:
1. MOTIVATION — why this company's actual work is a meaningful next step for the direction described above. One connection, stated plainly. Ground it in something the POSTING states about the company; if the posting says nothing about their work (agency listings often do not), write about what the ROLE itself demands instead. Never invent a description of the employer.
2. CONTRIBUTION — one concrete thing that could be contributed here, grounded in the evidence above. Describe WORK, not attributes, and not the tools the work is done with. It must be something the evidence actually supports. Forward-looking only: do not close it by comparing back to what the candidate has already done ("..., as I did in connecting research domains under a single engine"). Sentence 1 has made that comparison; the reader has the evidence paragraph above it.

THE REGISTER TO WRITE IN — this is the target, imitate its restraint, do not copy its words:
"Bending Spoons' interest in AI-supported product work feels relevant to the systems-oriented way I built TAIFUNOME. I would bring that same approach to prototyping and refining UX flows, then turning them into a coherent design system that reduces ambiguity between concept and build."
Notice: the connection is claimed modestly ("feels relevant to", not "directly enables" or "directly mirrors"); the project is referred to, not explained; the contribution is the work itself, with no tool names; and it stops.

THE SUBJECT OF THE FIRST SENTENCE IS THE COMPANY. Name them. Then say what it is relevant TO — which is the candidate's own work, written as "I"/"my".
  RIGHT: "{company}'s interest in X feels relevant to the way I built Y."
  WRONG: "Your focus on X feels relevant to {company}'s work on Y."
The second version is the most common way this goes wrong. "your" means the EMPLOYER, so it tells them their own focus is relevant to their own work, and the candidate has disappeared from the sentence. Never open with "Your focus", "Your work", "Your approach" or "Your method".

RULES
- NEVER use the word "align" in any form ("aligns with", "aligned", "alignment"). State the connection plainly instead: what they do, and what it is relevant to. This is the single most common reason a draft is thrown away.
- Exactly two sentences, one paragraph, 35-60 words in total. Plain prose, first person, UK English. No markdown, no bold, no bullet points, no greeting, no sign-off.
- Understate rather than overstate the connection. "mirrors", "directly enables", "directly matches", "perfectly matches" claim the two things have the same structure, which a job ad cannot establish. "feels relevant to" is the right strength.
- Do not explain the candidate's own work back to them. "the kind of systems-level work I've done in building TAIFUNOME" is throat-clearing; "the systems-oriented way I built TAIFUNOME" says it and moves on.
- NEVER name a tool, library, framework or piece of software. The CV lists the whole stack already, and the reader has it. Name the work, not what it was made with.
- The candidate is the WRITER, not the reader. Write "I"/"my" for the candidate and "you"/"your" only for the employer. TAIFUNOME, Asset Weaver and every other project named above are the CANDIDATE'S work — never call them "your work".
- Do not restate the candidate's biography, the typhoon metaphor, the move to Edinburgh, or the evidence. That text is already in the letter.
- Do not adopt the job title as an identity ("As a UX Designer, ..."). The candidate is applying, not incumbent.
- Never claim experience in the employer's industry or sector (finance, healthcare, retail, legal, government, gaming, ...). You may describe what the EMPLOYER does; you may not assert the candidate has done it.
- Never invent numbers, metrics, clients, employers or projects.
- Do not mention relocation, visas, or the job's location.
- Say what is concretely true rather than reaching for an abstraction. If a sentence would work equally well in a letter to any other company, it is not specific enough yet.
- Do not quote the posting back. Never repeat the company's own slogan or mission wording as though it were your observation — describe what they do in your own words. Any run of seven words copied from the posting is rejected.
- BANNED — the draft is rejected outright if it contains any of these, or a close paraphrase: {banned}

Output ONLY the two sentences."""
        return (call_llm(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=("You write two factual sentences connecting a fixed candidate "
                           "profile to one job posting. You never add a third sentence."),
            temperature=0.3,
            max_tokens=200,
        ) or "").strip().strip('"')
    except Exception as e:
        print(f"  ⚠ CL bridge generation skipped ({e})")
        return None


def _build_context_bridge(job_title: str, company: str, job_description: str,
                          canonical: str, evidence: list[dict]) -> tuple[str, str]:
    """Return (bridge_text, source). Never fails: falls back to the static bridge."""
    static = _STATIC_BRIDGE.format(company=company)
    if len((job_description or "").strip()) < _BRIDGE_MIN_DESCRIPTION:
        return static, "static"
    try:
        from matcher import _load_persona_summary
        persona = _load_persona_summary() or ""
    except Exception as e:
        print(f"  ⚠ CL persona load failed ({e}); using static bridge")
        return static, "static"

    # Faults accumulate. Telling the model only about its most recent rejection
    # let it cycle: it dropped "scalable", produced "production-ready", then
    # went back to "scalable" — three attempts spent rediscovering the same two
    # words because each retry had forgotten the one before.
    rejected: list[str] = []
    for _ in range(_BRIDGE_ATTEMPTS):
        draft = _normalise_bridge(_generate_context_bridge(
            job_title, company, job_description, canonical, evidence, persona,
            "; ".join(rejected)) or "")
        if not draft:
            continue
        ok, reason = _vet_bridge(draft, persona, job_title, job_description, evidence)
        if ok:
            return draft, "llm"
        print(f"  ⚠ CL bridge rejected ({reason}); retrying")
        rejected.append(reason)
    return static, "static"


def _fit_evidence_to_budget(job_title: str, company: str, canonical: str,
                            evidence: list[dict]) -> list[dict]:
    """Drop evidence blocks that would push the letter off one page.

    The canonical narrative is authored, and it grows: at 148 words two evidence
    blocks fitted comfortably, at 250 they did not. Rather than make the author
    hold the arithmetic — or silently ship a 430-word letter — the block that
    does not fit is the one that goes, because it is the only part of the letter
    that is genuinely optional.

    The bridge is not written yet, so its maximum is reserved rather than
    measured. A letter that comes in under budget because the bridge was short
    is the acceptable direction to be wrong in.
    """
    fixed = len(_OPENING_TEMPLATE.format(job_title=job_title, company=company).split())
    fixed += len(canonical.split()) + _BRIDGE_MAX_WORDS
    kept, total = [], fixed
    for item in evidence:
        cost = len(item["fact"].split()) + (1 if kept else 0)
        if kept and total + cost > _LETTER_MAX_WORDS:
            break
        kept.append(item)
        total += cost
    return kept


def _evidence_paragraphs(evidence: list[dict]) -> list[str]:
    """Render the evidence blocks, marking the second one as a second one.

    Facts are authored self-contained so that they can be selected in any
    combination, which leaves the second block opening cold — "I made Hive
    Floral Pod for the 2023 Shachihata Design Competition" arriving with no
    signal that a new example has started. One connective fixes that without
    claiming any relationship between the two, which is the part no fixed word
    could get right for every pair.

    Only facts opening with "I" take it: prefixing anything else would leave a
    capital mid-sentence, and lowercasing blindly would eat a proper noun.

    A connective is spent only on a project the letter has not named yet, and
    each is spent once. Both rules became load-bearing when a third block was
    allowed. "Separately," in front of a second paragraph about the site the
    first one just described is not a signal, it is a false one — the Lothian
    Buses posting draws the portfolio site twice — and two paragraphs opening
    on the same word read as a list the writer stopped attending to, which was
    54% of letters when every position past the first took the same connective.
    A block whose project is already named opens cold on purpose: the facts are
    authored self-contained, so it names its own subject in the first clause.
    """
    paragraphs, seen, spent = [], set(), 0
    for item in evidence:
        fact = item["fact"].strip()
        if seen and item["source_id"] not in seen and fact.startswith("I "):
            connective = _EVIDENCE_CONNECTIVES[min(spent, len(_EVIDENCE_CONNECTIVES) - 1)]
            fact = f"{connective} {fact}"
            spent += 1
        seen.add(item["source_id"])
        paragraphs.append(fact)
    return paragraphs


def _assemble_letter_body(job_title: str, company: str, canonical: str,
                          evidence: list[dict], bridge: str) -> str:
    """Concatenate the blocks. No judgement is exercised here, by design."""
    blocks = [_OPENING_TEMPLATE.format(job_title=job_title, company=company),
              canonical.strip()]
    blocks += _evidence_paragraphs(evidence)
    blocks.append(bridge.strip())
    return "\n\n".join(block for block in blocks if block)


def _vet_letter_body(text: str) -> tuple[bool, str]:
    """Structural check on the assembled body.

    Content was vetted where it was produced, so this only confirms the letter
    is the shape a letter should be: within length, prose throughout, and not
    carrying framing that MASTER_COVER_LETTER already supplies.
    """
    words = len(text.split())
    if not (_LETTER_MIN_WORDS <= words <= _LETTER_MAX_WORDS):
        return False, f"word count {words} outside {_LETTER_MIN_WORDS}–{_LETTER_MAX_WORDS}"
    if any(marker in text for marker in ("• ", "\n- ", "#", "**")):
        return False, "contains non-prose formatting"
    if "Dear " in text or "Yours sincerely" in text:
        return False, "duplicates the letter framing"
    # No filler check here on purpose. The only text a model wrote is the
    # bridge, and it was already checked against the bridge lists with the
    # posting's own vocabulary taken into account. Re-checking the whole body
    # against a different list would flag the bridge for phrases its own gate
    # had deliberately allowed.
    return True, ""


def generate_cover_letter(job_title: str, company: str, job_location: str = "Edinburgh",
                          job_description: str = "") -> tuple[str, str]:
    """Assemble a cover letter.

    Returns (letter_text, source), where source is ``assembled`` when the
    context bridge was written for this posting and ``assembled-static`` when it
    fell back to the neutral bridge. There is no template path: the identity and
    the evidence are authored files, so a letter can always be built once they
    load.

    Raises RuntimeError when the authored assets are missing, or when the
    posting names no employer, because a letter without either would be a
    different document than the one intended.
    """
    # Adzuna carries listings with an empty employer — a freelance brief posted
    # by an individual, or a board's own relisting. Every one of them produced a
    # letter reading "I am writing to apply for the ... position at ." and, when
    # a bridge was written, addressed whatever name the model could find in the
    # posting: one went out to CV-Library, the job board, as though it were the
    # hiring company. There is no salvage — a cover letter is addressed to
    # someone, so with no one to address it is not a document worth having.
    if not (company or "").strip():
        raise RuntimeError("cover letter: posting names no employer")

    canonical = _load_canonical_narrative()
    if not canonical:
        raise RuntimeError("cover letter: canonical narrative unavailable")

    role_type = detect_role_type(job_title, job_description)
    evidence = _select_evidence(job_title, job_description, role_type)
    if not evidence:
        raise RuntimeError("cover letter: no evidence available for this role")
    evidence = _fit_evidence_to_budget(job_title, company, canonical, evidence)

    bridge, bridge_source = _build_context_bridge(job_title, company, job_description,
                                                  canonical, evidence)
    letter_body = _assemble_letter_body(job_title, company, canonical, evidence, bridge)

    ok, reason = _vet_letter_body(letter_body)
    if not ok:
        # The assembled body is authored text plus a vetted bridge, so a failure
        # here means an asset drifted out of budget rather than that the letter
        # is unsafe. Say so loudly and still return it; a human reviews every
        # letter before it is sent.
        print(f"  ⚠ CL assembled letter outside spec ({reason})")

    # The scraper's location carries the county ("Edinburgh, Midlothian"), which
    # reads as a half-finished postal address in the recipient block. A letter
    # addresses the city.
    recipient_location = job_location.split(",")[0].strip() or job_location

    letter = MASTER_COVER_LETTER.format(
        name=PERSONAL_INFO["name"],
        location=PERSONAL_INFO["location"],
        email=PERSONAL_INFO["email"],
        phone=PERSONAL_INFO["phone"],
        company=company,
        job_location=recipient_location,
        letter_body=letter_body,
    )
    return letter, ("assembled" if bridge_source == "llm" else "assembled-static")


def save_cover_letter(job_title: str, company: str, job_location: str, job_description: str, output_dir: str, match_filename: str = "", cv_filename: str = "", override_body: str = "") -> str:
    """Generate and save cover letter as Markdown."""
    from pathlib import Path

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    role_type = detect_role_type(job_title, job_description)

    if override_body:
        recipient_location = job_location.split(",")[0].strip() or job_location
        letter = MASTER_COVER_LETTER.format(
            name=PERSONAL_INFO["name"],
            location=PERSONAL_INFO["location"],
            email=PERSONAL_INFO["email"],
            phone=PERSONAL_INFO["phone"],
            company=company,
            job_location=recipient_location,
            letter_body=override_body,
        )
        opening_source = "override"
    else:
        letter, opening_source = generate_cover_letter(job_title, company, job_location, job_description)

    from matcher import make_safe_name
    filename = f"{make_safe_name(company, job_title)}_CL.md"
    filepath = Path(output_dir) / filename

    # role_type is stated outright rather than left to be read back out of the
    # source_template link: the letter is no longer built from a per-role
    # template, so the link no longer ends in the role name.
    frontmatter = f"""---
title: "{company} - {job_title} (Cover Letter)"
type: "cover-letter"
company: "{company}"
match_report: "[[{match_filename}]]"
cv: "[[{cv_filename}]]"
source_template: "[[career/cover-letter/canonical_narrative_v1]]"
role_type: "{role_type}"
opening_source: "{opening_source}"
generation_mode: "assembler"
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
