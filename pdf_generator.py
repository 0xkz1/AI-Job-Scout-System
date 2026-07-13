"""
PDF Generator — Markdown → HTML → PDF
=====================================
Converts tailored CV and Cover Letter Markdown files into polished PDFs.

Usage:
    # Generate PDFs for all jobs above match threshold
    python3 pdf_generator.py

    # Generate for a specific job
    python3 pdf_generator.py --company "Opus 2" --title "Junior Software Engineer"

    # Custom threshold (default: top 50%+ match score)
    python3 pdf_generator.py --threshold 0.70

Design:
    - Clean, professional layout (A4, margins, serif body / sans-serif headings)
    - Color palette: dark slate headings, muted accent line, black body text
    - Portable: no external font deps (uses system fonts via WeasyPrint)
"""

import os
import re
import sys
import json
import argparse
from pathlib import Path
from datetime import date

import markdown
from weasyprint import HTML

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "10_output"
CV_DIR = OUTPUT_DIR / "10_cvs"
CL_DIR = OUTPUT_DIR / "10_cover-letters"
PDF_DIR = OUTPUT_DIR / "20_pdfs"

# ─────────────────────────────────────────────
# CSS — Shared design system
# ─────────────────────────────────────────────

BASE_CSS = """
@page {
    size: A4;
    margin: 18mm 18mm 16mm 18mm;
    @bottom-center {
        content: counter(page);
        font-size: 9pt;
        color: #999;
    }
}

:root {
    --heading-color: #2c3e50;
    --accent-color: #4a90d9;
    --body-color: #1a1a1a;
    --muted-color: #666;
    --border-color: #e0e0e0;
}

body {
    font-family: "Georgia", "Times New Roman", serif;
    font-size: 10.5pt;
    line-height: 1.5;
    color: var(--body-color);
    margin: 0;
    padding: 0;
}

h1 {
    font-family: "Helvetica Neue", "Arial", sans-serif;
    font-size: 18pt;
    font-weight: 700;
    color: var(--heading-color);
    margin: 0 0 2pt 0;
    padding-bottom: 4pt;
    border-bottom: 2pt solid var(--heading-color);
}

h2 {
    font-family: "Helvetica Neue", "Arial", sans-serif;
    font-size: 11.5pt;
    font-weight: 700;
    color: var(--heading-color);
    margin: 14pt 0 4pt 0;
    padding-bottom: 2pt;
    border-bottom: 0.5pt solid var(--border-color);
    text-transform: uppercase;
    letter-spacing: 0.5pt;
}

h3 {
    font-family: "Helvetica Neue", "Arial", sans-serif;
    font-size: 10.5pt;
    font-weight: 600;
    color: var(--accent-color);
    margin: 8pt 0 3pt 0;
}

p {
    margin: 0 0 6pt 0;
    text-align: justify;
}

ul {
    margin: 0 0 6pt 0;
    padding-left: 16pt;
}

li {
    margin-bottom: 2pt;
    line-height: 1.45;
}

strong {
    font-weight: 700;
    color: var(--heading-color);
}

a {
    color: var(--accent-color);
    text-decoration: none;
}

hr {
    border: none;
    border-top: 0.5pt solid var(--border-color);
    margin: 8pt 0;
}

/* CV-specific: first line (name) styling */
body > p:first-of-type {
    font-family: "Helvetica Neue", "Arial", sans-serif;
    font-size: 20pt;
    font-weight: 700;
    color: var(--heading-color);
    margin-bottom: 4pt;
}

/* Contact line (second paragraph) */
body > p:nth-of-type(2) {
    font-size: 9pt;
    color: var(--muted-color);
    margin-bottom: 10pt;
}
"""

CL_CSS = BASE_CSS + """
/* Cover letter overrides */
body {
    font-size: 11pt;
    line-spacing: 1.55;
}

h1 {
    display: none;  /* Cover letters don't use h1 */
}

p {
    margin-bottom: 8pt;
}

/* Date + address block */
body > p:nth-of-type(1),
body > p:nth-of-type(2),
body > p:nth-of-type(3),
body > p:nth-of-type(4) {
    font-size: 10pt;
    color: var(--muted-color);
    margin-bottom: 2pt;
}
"""


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def md_to_html(md_text: str, is_cover_letter: bool = False) -> str:
    """Convert markdown text to styled HTML string."""
    html_body = markdown.markdown(
        md_text,
        extensions=["extra", "nl2br"],
    )
    css = CL_CSS if is_cover_letter else BASE_CSS
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{html_body}</body></html>"


def generate_pdf(md_path: Path, output_pdf_path: Path, is_cover_letter: bool = False) -> bool:
    """Convert a single Markdown file to PDF."""
    try:
        md_text = md_path.read_text(encoding="utf-8")
        if not md_text.strip():
            return False
        html = md_to_html(md_text, is_cover_letter=is_cover_letter)
        HTML(string=html).write_pdf(str(output_pdf_path))
        return True
    except Exception as e:
        print(f"  ⚠ PDF error for {md_path.name}: {e}")
        return False


def find_matching_cv_cl(company: str = "", title: str = "") -> list[tuple[Path, Path | None]]:
    """Find CV and optionally CL files matching company/title."""
    if not company:
        # Return all CVs
        cvs = sorted(CV_DIR.glob("*_CV.md"))
        return [(cv, _find_cl_for_cv(cv)) for cv in cvs]

    # Search by company + title
    safe_company = re.sub(r"[^\w\s-]", "", company).strip().replace(" ", "_")[:30]
    safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:50] if title else ""
    pattern = f"{safe_company}_{safe_title}_CV.md" if safe_title else f"{safe_company}*CV.md"
    cvs = sorted(CV_DIR.glob(pattern))
    return [(cv, _find_cl_for_cv(cv)) for cv in cvs]


def _find_cl_for_cv(cv_path: Path) -> Path | None:
    """Find the matching cover letter file for a CV."""
    stem = cv_path.stem.removesuffix("_CV")
    cl_path = CL_DIR / f"{stem}_CL.md"
    if cl_path.exists():
        return cl_path
    # Fallback: fuzzy match
    cls = list(CL_DIR.glob(f"{stem[:20]}*CL.md"))
    return cls[0] if cls else None


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate PDFs from CV/CL Markdown files")
    parser.add_argument("--company", default="", help="Filter by company name")
    parser.add_argument("--title", default="", help="Filter by job title")
    parser.add_argument("--threshold", type=float, default=0.0,
                        help="Only generate PDFs for jobs with match score >= threshold (default: all)")
    parser.add_argument("--cv-only", action="store_true", help="Skip cover letters")
    args = parser.parse_args()

    PDF_DIR.mkdir(parents=True, exist_ok=True)

    # If threshold specified, load analyzed data to filter
    eligible_prefixes = None
    if args.threshold > 0:
        analyzed_path = OUTPUT_DIR / "_analyzed.json"
        if not analyzed_path.exists():
            print("⚠ No _analyzed.json found for threshold filtering. Generating all CVs.")
        else:
            with open(analyzed_path) as f:
                analyzed = json.load(f)
            eligible_prefixes = set()
            for job in analyzed:
                score = job.get("match", {}).get("composite_score", 0)
                if score >= args.threshold:
                    safe_c = re.sub(r"[^\w\s-]", "", job.get("company", "")).strip().replace(" ", "_")[:30]
                    safe_t = re.sub(r"[^\w\s-]", "", job.get("title", "")).strip().replace(" ", "_")[:50]
                    eligible_prefixes.add(f"{safe_c}_{safe_t}")
            print(f"📋 Threshold {args.threshold:.0%}: {len(eligible_prefixes)} jobs eligible for PDF")

    # Find CV/CL pairs
    pairs = find_matching_cv_cl(args.company, args.title)

    if eligible_prefixes is not None:
        pairs = [(cv, cl) for cv, cl in pairs
                 if any(cv.stem.startswith(p) for p in eligible_prefixes)]

    if not pairs:
        print("No matching CV/CL files found.")
        return

    print(f"\n📄 Generating PDFs for {len(pairs)} job(s)...\n")

    cv_count = 0
    cl_count = 0

    for cv_path, cl_path in pairs:
        # Generate CV PDF
        cv_pdf = PDF_DIR / cv_path.stem.replace("_CV", "") / cv_path.stem
        cv_pdf.parent.mkdir(parents=True, exist_ok=True)
        if generate_pdf(cv_path, cv_pdf, is_cover_letter=False):
            print(f"  ✓ CV PDF: {cv_pdf.name}")
            cv_count += 1

        # Generate CL PDF
        if not args.cv_only and cl_path and cl_path.exists():
            cl_pdf = cv_pdf.parent / cl_path.stem
            if generate_pdf(cl_path, cl_pdf, is_cover_letter=True):
                print(f"  ✓ CL PDF: {cl_pdf.name}")
                cl_count += 1

    print(f"\n{'='*40}")
    print(f"✅ Generated {cv_count} CV PDFs, {cl_count} Cover Letter PDFs")
    print(f"📁 Output: {PDF_DIR}/")
    print(f"{'='*40}")


if __name__ == "__main__":
    main()
