"""
PDF rendering for generated CVs and cover letters.

Extracted from app.py so the CLI (pdf_generator.py) can render without
importing Streamlit. This module is the ONE renderer — invariants.py's
check_one_document_renderer enforces that no other module imports weasyprint,
because a second copy silently misses every layout fix applied here.
app.py imports these names rather than defining its own.
"""
from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

# --- Paths (mirrors app.py; same values, no Streamlit import) ---
SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "10_output"
MATCH_DIR = OUTPUT_DIR / "00_matches"

# --- PDF export (CV / Cover Letter) ---
PDF_DIR = OUTPUT_DIR / "20_pdfs"

# Recipient-facing PDF filenames carry the applicant's name so a hiring
# manager can tell whose document this is before opening it. The internal
# .md files (10_cvs, 10_cover-letters, 00_matches) keep their bare
# make_safe_name(company, title) join key — renaming 5,000+ files there
# would break the report↔CV/CL links. Only the PDF output name is prefixed.
APPLICANT_NAME_PREFIX = "Kazuki-Yunome"
# NOTE: ./static/pdfs/ is no longer written to — downloads go through
# st.download_button (see _pdf_download_button). The copies already there are
# left alone, but they duplicate every name under 10_output/20_pdfs/, so an
# Obsidian `pdf: "[[Name.pdf]]"` wikilink has two candidates to resolve to.
CV_DIR = OUTPUT_DIR / "10_cvs"
CL_DIR = OUTPUT_DIR / "10_cover-letters"


def _letter_date(on: "date | None" = None) -> str:
    """A letter's date, UK style: "2 August 2026", never zero-padded (%-d is
    glibc-only, so the day is built separately)."""
    from datetime import date as _date
    d = on or _date.today()
    return f"{d.day} {d.strftime('%B %Y')}"


_DATE_LINE_RE = re.compile(r"^\s*\d{1,2} [A-Z][a-z]+ \d{4}\s*$", re.MULTILINE)


def _dated_today(text: str) -> str:
    """Put today's date in the letter's sender block.

    The date belongs to the day the letter is SENT, not the day the pipeline
    happened to draft it. Held in the markdown it went stale silently: letters
    drafted three weeks earlier were still dated three weeks earlier, and a
    reader sees that before they read a word of the letter. So the markdown
    carries no date and the renderer stamps one. Existing letters do carry one
    — those are rewritten rather than doubled.
    """
    if _DATE_LINE_RE.search(text):
        return _DATE_LINE_RE.sub(_letter_date(), text, count=1)
    # No date line: add one under the name/contact block, which the sender
    # block ends with, i.e. before the first blank line.
    head, sep, rest = text.partition("\n\n")
    return f"{head.rstrip()}\n{_letter_date()}{sep}{rest}" if sep else text


def _md_to_pdf_bytes(md_path: Path) -> bytes:
    """Render a generated CV/CL markdown file to a clean A4 PDF."""
    # Lazy imports: weasyprint is slow to load and only needed on demand
    import markdown as _markdown
    from weasyprint import HTML

    # Cover letters are short prose, not page-count-constrained like a CV —
    # the tightened paragraph margin below exists to fit a CV in two pages
    # and otherwise just crushes CL paragraph breaks flat.
    is_cl = md_path.stem.endswith("_CL")

    text = md_path.read_text(encoding="utf-8")
    # Strip YAML frontmatter (Obsidian metadata, not for the PDF)
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)
    # Strip Obsidian Meta Bind blocks (buttons, inputs — not for the PDF)
    text = re.sub(r"```meta-bind[^\n]*\n.*?```\n?", "", text, flags=re.DOTALL)
    # Obsidian wiki-links → plain text ([[target|label]] → label)
    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), text)
    if is_cl:
        text = _dated_today(text)
        # The LLM habitually bolds or italicises a project name mid-sentence
        # ("I built **TAIFUNOME**", "my work on *Feral Bestiary*") as ad-lib
        # emphasis — cover_letter_generator.py never asks for it, and unlike a
        # CV a letter has no structural use for markdown emphasis at all (the
        # sender block, salutation, and closing are plain text). Measured
        # across the letters on disk: 99/471 carry stray bold, 166/471 stray
        # italic. Stripped here rather than fixed in the prompt, since a
        # rendering rule is certain where an LLM instruction is only ever
        # probable — the CL word-count limit is asked for the same way and is
        # still missed on roughly a fifth of openings.
        text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
        text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)

    # Generated CVs/CLs are near-plain text: ALL-CAPS section lines, "•" bullets,
    # and meaningful single line breaks. Preprocess into real markdown.
    lines = text.strip().split("\n")
    out_lines = []
    # Bold-only lines are entry titles in EXPERIENCE/SELECTED PROJECTS but mere
    # category labels in the toolkit; only the former need breathing room.
    titles_want_space = False
    # A CL recipient block is "Hiring Team\n<Company>\n<City>". Company lines
    # are often ALL-CAPS (VCCP, BBC, IBM, D&AD) and would otherwise trip the
    # ALL-CAPS section-header rule below, inflating the addressee to an h2
    # while "Hiring Team" and the city stay body text — a broken look, and one
    # the sender cannot see from the markdown source. The block is plain
    # address text, so every line in it is emitted verbatim. Only active for
    # cover letters: CVs have no such block and a "Hiring Team" heading in one
    # would not be the addressee.
    in_recipient_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "Hiring Team":
            in_recipient_block = is_cl
        elif stripped.startswith("Dear ") or not in_recipient_block:
            in_recipient_block = False
        if in_recipient_block:
            out_lines.append(line)  # recipient block: never a heading
            continue
        if i == 0 and stripped and not stripped.startswith("#"):
            out_lines.append(f"# {stripped}")  # first line = candidate name
        elif re.fullmatch(r"[A-Z][A-Z &/'’\-]{2,40}", stripped):
            titles_want_space = stripped in ("EXPERIENCE", "SELECTED PROJECTS")
            out_lines.append(f"\n## {stripped}")  # ALL-CAPS section header
        elif re.fullmatch(r"\*\*[^*]+\*\*", stripped):
            # A line that is nothing but bold text is an entry title (job,
            # project) or a toolkit category. Left as a paragraph, nl2br glues
            # it to the text beneath with no space at all; as a heading it gets
            # its own margin — a wider one for entries than for categories.
            level = "###" if titles_want_space else "####"
            out_lines.append(f"\n{level} {stripped.strip('*')}")
        elif re.fullmatch(r"\*\*[^*]+\*\* · .+", stripped):
            # Same entry-title line, plus a trailing " · <link>" (a project's
            # URL). The bare-bold pattern above requires the WHOLE line to be
            # "**...**" — the suffix breaks that fullmatch, so this line fell
            # through to the plain-text branch below. There it was joined to
            # the next line with a single \n, which nl2br glues into one <p>
            # with the following bullets — no heading tag, no page-break-avoid,
            # and "•" bullets rendered as literal dashes instead of a <li>
            # list. The ** and [text](url) markers are kept (not stripped):
            # ATX headings run inline markdown, so ### processes both.
            level = "###" if titles_want_space else "####"
            out_lines.append(f"\n{level} {stripped}")
        elif stripped.startswith(("**Other projects:", "**その他のプロジェクト:")):
            # Trails the last project's bullet list, so without a break of its
            # own markdown reads it as more of that list and it ends up flush
            # against the bullets. Its own paragraph, with room above.
            # Raw HTML, so the bold marker is expanded here — markdown does not
            # reach inside an HTML block without the md_in_html extension.
            inner = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", stripped)
            out_lines.append(f'\n<p class="trailing">{inner}</p>\n')
        elif stripped.startswith("**") and titles_want_space is False and ":" not in stripped[:3]:
            # Bold-led lines that continue in plain text (education entries):
            # give each its own paragraph so they do not run together.
            out_lines.append(f"\n{stripped}")
        elif stripped.startswith("•"):
            out_lines.append("- " + stripped.lstrip("• "))
        else:
            out_lines.append(line)
    text = "\n".join(out_lines)

    body = _markdown.markdown(text, extensions=["tables", "fenced_code", "nl2br"])
    # A CL is a greeting to someone else, not a CV — the candidate's name
    # shouldn't read as the headline. It also runs short of a page; a
    # couple of the natural letter breaks (recipient block, salutation,
    # the gap before the signature) get extra air instead of leaving
    # everything crammed at the top with dead space below.
    cl_spacing_css = (
        """p:nth-of-type(2), p:nth-of-type(3) { margin-top: 10pt; }
        p:last-of-type { margin-top: 20pt; }"""
        if is_cl else ""
    )
    html = f"""<html><head><meta charset="utf-8"><style>
        /* Tightened so a CV lands in as few pages as possible without
           reading as cramped — a third page is rarely reached by a reader.
           The page margin is what buys the second page: at 13mm the longest
           CVs spill onto a third, at 10mm none do. Font size and line height
           were left alone deliberately — shrinking them is what makes a CV
           read as cramped, and edge whitespace is the cheaper thing to give
           up. Heading margins barely move the page count; don't trade the
           space above entry titles for it. */
        @page {{ size: A4; margin: 10mm 11mm; }}
        body {{ font-family: "DejaVu Sans", sans-serif; font-size: 9.5pt; line-height: 1.3; color: #1a1a1a; }}
        h1 {{ font-size: {"12pt" if is_cl else "16pt"}; margin: 0 0 3pt; }}
        /* The rule under a section heading is a boundary, not an underline: the
           heading is already 11.5pt bold above 9.5pt body text, so #999 was
           competing with it. Lightened to #d5d5d5, which still separates a
           section on a dense page without reading as part of the title. No
           height changes, so the two-page budget is untouched. */
        h2 {{ font-size: 11.5pt; border-bottom: 1px solid #d5d5d5; padding-bottom: 2pt; margin: 7pt 0 3pt; page-break-after: avoid; }}
        h3 {{ font-size: 9.8pt; margin: 14pt 0 1pt; page-break-after: avoid; }}
        h4 {{ font-size: 9.5pt; margin: 4pt 0 0; page-break-after: avoid; }}
        p, li {{ margin: {"6pt" if is_cl else "1.5pt"} 0; }}
        {cl_spacing_css}
        /* Without an explicit margin the default 1em lands under every entry
           title, so the title floats between its heading space and its own
           text. Space belongs above a title, not below it. */
        ul {{ margin: 0 0 0; padding-left: 13pt; }}
        p.trailing {{ margin: 10pt 0 0; }}
        /* Short-entry CVs separate projects with "---", which is a readable
           divider in Obsidian but renders as a heavy default <hr> in print.
           The space above each entry title already separates them. */
        hr {{ display: none; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ccc; padding: 3pt 6pt; text-align: left; }}
        /* One accent, used twice: the role title under the name, and every
           link. Both are things a reader looks FOR — the first tells them what
           this CV is answering, the second is the only part of the page they
           can act on — and neither was distinguishable from body text before.
           Deep navy rather than anything brighter: this is a document that has
           to survive being printed in black and white by a recruiter, so the
           colour carries no information the text does not. */
        a {{ color: #1f3a5f; text-decoration: none; }}
        h1 + h4 {{ color: #1f3a5f; }}
    </style></head><body>{body}</body></html>"""
    return HTML(string=html).write_pdf()


_PDF_VERSIONS_META = PDF_DIR / ".pdf_versions.json"


def _version_filename(stem: str, n: int) -> str:
    """v1 keeps the bare name (backward compatible); v2+ gets a _vN suffix."""
    return f"{stem}.pdf" if n == 1 else f"{stem}_v{n}.pdf"


def _pdf_versions(stem: str) -> list[tuple[int, Path]]:
    """Existing PDF versions for a stem, ascending: [(1, stem.pdf), (2, stem_v2.pdf), ...]."""
    import re
    out = []
    p1 = PDF_DIR / f"{stem}.pdf"
    if p1.exists():
        out.append((1, p1))
    for p in PDF_DIR.glob(f"{stem}_v*.pdf"):
        m = re.fullmatch(rf"{re.escape(stem)}_v(\d+)\.pdf", p.name)
        if m:
            out.append((int(m.group(1)), p))
    out.sort()
    return out


def _load_pdf_meta() -> dict:
    import json
    try:
        return json.loads(_PDF_VERSIONS_META.read_text())
    except Exception:
        return {}


def _save_pdf_meta(meta: dict):
    import json
    PDF_DIR.mkdir(exist_ok=True)
    _PDF_VERSIONS_META.write_text(json.dumps(meta, indent=2))


def _pdf_source_sha(md_path: Path) -> str:
    """The identity of a PDF's source: what would actually reach the page.

    Two things are deliberately outside it and one deliberately inside:

    * The frontmatter is EXCLUDED. _md_to_pdf_bytes strips it, so no property
      there can change the PDF — and hashing it made conversion invalidate
      itself once the converter began writing `pdf:` back into the note: each
      run rewrote the file it had just hashed and minted another identical
      version, forever. Stamping a review did the same.
    * The renderer source is INCLUDED. The CSS and markdown preprocessing live
      in _md_to_pdf_bytes, so a layout change leaves the MD byte-identical and
      the stale PDF would be reused forever.

    Both the converter and the freshness badge must ask the same question, so
    they ask it here. They used to compute it separately and drifted: the badge
    hashed raw file bytes with no renderer, so it never matched what the
    converter stored and every freshly built PDF was labelled "(outdated)".
    """
    import hashlib, inspect
    body = re.sub(r"\A---\n.*?\n---\n", "", md_path.read_text(encoding="utf-8"), flags=re.DOTALL)
    # A letter is dated at render time, so the date is part of what it renders
    # to even though it appears nowhere in the source. Leave it out and the
    # reuse branch hands back yesterday's PDF, dated yesterday — the exact
    # staleness moving the date here was meant to end.
    stamped = _letter_date() if md_path.stem.endswith("_CL") else ""
    return hashlib.sha1(
        body.encode("utf-8")
        + stamped.encode("utf-8")
        + inspect.getsource(_md_to_pdf_bytes).encode("utf-8")
    ).hexdigest()


class PdfPageCountError(Exception):
    """A rendered document did not land on the page count its format requires."""


# A CV is written to fill exactly two A4 pages, a cover letter one. Both budgets
# are already enforced upstream in cv_generator.py — as a word ceiling
# (_CV_MAX_WORDS) and, for the ja route, a character ceiling — but those are
# proxies for page space, and measurement says they let three-page CVs through:
# of the 75 PDFs on disk on 2026-08-30, three CVs render three pages and ALL
# THREE pass the word gate (1077 and 1078 body words against a 1080 target,
# 1115 against the 1120 maximum). One of them was sent — Opus 2 Platform
# Engineer, applied 2026-08-18.
#
# Lowering the ceiling would not fix it. What overflows is line count, and an
# entry title costs page space no word count can see; cv_generator.py:1330 says
# exactly that, and charges _ENTRY_LINE_COST inside its trim/pad arithmetic but
# never in the comparison against the ceiling. So the word ceiling stays where
# it is as a trimming heuristic, and the pass/fail moves here — onto the only
# thing that answers the question, the rendered page count.
_EXPECTED_PAGES = {"CV": 2, "CL": 1}


def _doc_page_budget(md_path: Path) -> "tuple[str, int] | None":
    """(kind, required page count) for a generated document, or None for neither.

    A document with no declared budget is not blocked — there is nothing to
    check it against. Only CVs and cover letters have one.
    """
    stem = md_path.stem
    if stem.endswith("_CL") or "_CL_" in stem:
        return "CL", _EXPECTED_PAGES["CL"]
    if stem.endswith("_CV") or "_CV_" in stem:
        return "CV", _EXPECTED_PAGES["CV"]
    return None


def _pdf_page_count(pdf_bytes: bytes) -> int:
    """Page count of a rendered PDF, read back out of its bytes.

    Asked of poppler, over stdin, rather than of WeasyPrint or of the bytes
    directly — each alternative was tried first:

    * WeasyPrint can report it from HTML(...).render().pages, but reaching that
      means editing _md_to_pdf_bytes, whose source _pdf_source_sha hashes. Every
      PDF on disk would immediately read as stale and the next conversion of each
      would mint a pointless new version, for a change that alters no output byte.
    * Scanning the bytes for /Type /Page or /Count finds nothing: WeasyPrint
      writes its page objects into compressed object streams. Checked against
      pdfinfo over all 75 PDFs on disk — 75 mismatches out of 75, both patterns.

    stdin keeps bytes that have not passed the check off disk entirely.
    """
    try:
        proc = subprocess.run(["pdfinfo", "-"], input=pdf_bytes, capture_output=True)
    except FileNotFoundError as exc:
        raise PdfPageCountError(
            "pdfinfo was not found, so the page count cannot be verified "
            "(Debian/Ubuntu: apt install poppler-utils). Refusing rather than "
            "exporting an unverified document."
        ) from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip() or "pdfinfo failed"
        raise PdfPageCountError(f"pdfinfo could not read the rendered PDF: {detail}")
    match = re.search(
        r"^Pages:\s+(\d+)\s*$", proc.stdout.decode("utf-8", "replace"), re.MULTILINE
    )
    if not match:
        raise PdfPageCountError("pdfinfo returned no page count for the rendered PDF")
    return int(match.group(1))


def _assert_page_budget(md_path: Path, pdf_bytes: bytes) -> None:
    """Refuse a rendered document that missed the page count its format requires."""
    budget = _doc_page_budget(md_path)
    if budget is None:
        return
    kind, expected = budget
    actual = _pdf_page_count(pdf_bytes)
    if actual != expected:
        raise PdfPageCountError(
            f"{md_path.name} renders to {actual} pages; a {kind} must be exactly "
            f"{expected}. Nothing was written and no version was minted — trim "
            f"the source and convert again."
        )


def _convert_pdf_versioned(md_path: Path) -> tuple[Path, int, bool]:
    """Render md_path to a PDF, versioning by source-MD content, and link it.

    If the current markdown is identical to the newest existing version's
    source, reuse that PDF (no pointless duplicate). Otherwise mint the
    next sequential version (highest existing number + 1). Returns
    (pdf_path, version_number, is_new).

    Stamping the `pdf:` property is done HERE rather than left to the caller.
    It used to be a separate follow-up call, and the Gmail-draft path simply
    never made it — minting versions no note ever linked to. A PDF that
    nothing points at is not a finished conversion, so the two steps are one
    function with no seam for a caller to miss.
    """
    # PDF output names carry the applicant's name; the internal .md stem
    # (company_title) stays as the join key used to stamp pdf:/cv_pdf:/cl_pdf:
    # frontmatter back onto the report. Versioning is by prefixed stem so new
    # outputs mint their own sequence instead of colliding with legacy PDFs.
    stem = f"{APPLICANT_NAME_PREFIX}_{md_path.stem}"
    md_sha = _pdf_source_sha(md_path)
    versions = _pdf_versions(stem)
    meta = _load_pdf_meta()

    PDF_DIR.mkdir(exist_ok=True)

    if versions:
        latest_n, latest_path = versions[-1]
        if meta.get(latest_path.name) == md_sha and latest_path.exists():
            # Checked on reuse too, not only on mint: the three-page CVs already
            # on disk predate this gate, and reuse is the path that would keep
            # handing them back — stamped onto the report — without a word.
            _assert_page_budget(md_path, latest_path.read_bytes())
            _set_report_pdf_property(md_path, latest_path.name)
            return latest_path, latest_n, False  # unchanged — reuse
        n = latest_n + 1
    else:
        n = 1

    target = PDF_DIR / _version_filename(stem, n)
    pdf_bytes = _md_to_pdf_bytes(md_path)
    _assert_page_budget(md_path, pdf_bytes)
    target.write_bytes(pdf_bytes)
    meta[target.name] = md_sha
    _save_pdf_meta(meta)
    _set_report_pdf_property(md_path, target.name)
    return target, n, True

def _set_frontmatter_property(path: Path, key: str, value: str):
    """Set/replace a single frontmatter property in an existing markdown file."""
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    m = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if not m:
        return
    line = f'{key}: "{value}"'
    fm = m.group(1)
    if re.search(rf"^{key}:.*$", fm, flags=re.MULTILINE):
        fm = re.sub(rf"^{key}:.*$", line, fm, flags=re.MULTILINE)
    else:
        fm = fm + "\n" + line
    path.write_text(f"---\n{fm}\n---\n" + text[m.end():], encoding="utf-8")


def _set_report_doc_property(md_path: Path, key_suffix: str, target_name: str):
    """Set a cv_*/cl_* wikilink property on the match report's frontmatter.

    md_path is the CV/CL markdown (…_CV.md / …_CL.md); the report shares its
    base name. key_suffix "pdf" → cv_pdf/cl_pdf, "review" → cv_review/cl_review.
    Frontmatter properties keep these Dataview-queryable from the report.
    """
    stem = md_path.stem
    if stem.endswith("_CV"):
        key, base = f"cv_{key_suffix}", stem[:-3]
    elif stem.endswith("_CL"):
        key, base = f"cl_{key_suffix}", stem[:-3]
    else:
        return
    report = MATCH_DIR / f"{base}.md"
    _set_frontmatter_property(report, key, f"[[{target_name}]]")


def _set_report_pdf_property(md_path: Path, pdf_name: str):
    _set_report_doc_property(md_path, "pdf", pdf_name)
    # Same property on the CV/CL's own frontmatter, not just the report's —
    # the PDF should be reachable from either direction.
    _set_frontmatter_property(md_path, "pdf", f"[[{pdf_name}]]")
