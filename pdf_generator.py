"""
PDF Generator — CLI Entrypoint
===============================
Delegates rendering to app.py's live renderer (_convert_pdf_versioned) to guarantee
all PDF outputs follow the latest layout, CSS rules, and versioning system.

Usage:
    # Generate PDFs for all jobs above match threshold
    python3 pdf_generator.py

    # Generate for a single note file
    python3 pdf_generator.py --file "10_output/10_cvs/Wordsmith_AI_Product_Designer_CV.md"

    # Generate for a specific job
    python3 pdf_generator.py --company "Wordsmith AI" --title "Product Designer"
"""

import sys
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from app import (
    _convert_pdf_versioned,
    OUTPUT_DIR,
    CV_DIR,
    CL_DIR,
    PDF_DIR,
)
from matcher import canonical_company, make_safe_name
import gen_version


def _stale_guard(md_path: Path, force: bool) -> bool:
    """Refuse to render a document whose body predates the current spec.

    Rendering is faithful — it turns whatever markdown is on disk into a PDF —
    so it cannot tell a current CV from one written before the shape changed.
    That is how a three-page, pre-taifunome CV reached a finished PDF: the
    markdown had been touched by a patch script, its mtime looked fresh, and
    nothing between the file and the PDF asked whether the body was current.

    Printed on stdout, not stderr: the Obsidian plugin runs this over ssh with
    stderr discarded, and a refusal the user cannot read is just a failure.

    Returns True when rendering may proceed.
    """
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return True  # unreadable here means unreadable to the renderer too; let it say so
    reason = gen_version.staleness_reason(text, is_cv=md_path.stem.endswith("_CV"))
    if not reason:
        return True
    if force:
        print(f"⚠️ 古い型のまま出力します (--force): {reason}")
        return True
    base = md_path.stem.removesuffix("_CV").removesuffix("_CL")
    print(f"🛑 古い型のため中止: {md_path.name}")
    print(f"   {reason}")
    print(f"   再生成: printf '{base}\\n' > /tmp/regen.txt && "
          f".venv/bin/python3 regen_top_docs.py --only /tmp/regen.txt")
    print("   このまま出力する場合は --force")
    return False


def main():
    parser = argparse.ArgumentParser(description="Generate PDFs using the live system renderer.")
    parser.add_argument("--file", default="", help="Path to specific Markdown file to convert")
    parser.add_argument("--company", default="", help="Filter by company name")
    parser.add_argument("--title", default="", help="Filter by job title")
    parser.add_argument("--threshold", type=float, default=0.0,
                        help="Only generate PDFs for jobs with match score >= threshold")
    parser.add_argument("--cv-only", action="store_true", help="Skip cover letters")
    parser.add_argument("--force", action="store_true",
                        help="Render even when the document's body predates the current spec")
    args = parser.parse_args()

    PDF_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Single File Mode
    if args.file:
        file_path = Path(args.file).resolve()
        if not file_path.exists():
            print(f"❌ File not found: {file_path}")
            sys.exit(1)
        if not _stale_guard(file_path, args.force):
            sys.exit(2)
        pdf_path, version, is_new = _convert_pdf_versioned(file_path)
        status_str = "Minted new version" if is_new else "Reused existing version"
        print(f"✅ [{status_str}] PDF v{version}: {pdf_path}")
        return

    # 2. Batch Mode
    cv_files = sorted(CV_DIR.glob("*_CV.md"))
    if args.company:
        if args.title:
            prefix = make_safe_name(args.company, args.title)
            cv_files = [f for f in cv_files if f.stem == f"{prefix}_CV"]
        else:
            safe_c = canonical_company(args.company)
            cv_files = [f for f in cv_files if safe_c.lower() in f.name.lower()]

    print(f"📄 Processing {len(cv_files)} CV(s) with live renderer...")
    count = 0
    skipped = 0
    for cv_path in cv_files:
        if not _stale_guard(cv_path, args.force):
            skipped += 1
            continue
        pdf_path, version, is_new = _convert_pdf_versioned(cv_path)
        print(f"  ✓ CV: {cv_path.name} -> v{version}")
        count += 1

        if not args.cv_only:
            stem = cv_path.stem.removesuffix("_CV")
            cl_path = CL_DIR / f"{stem}_CL.md"
            if cl_path.exists() and _stale_guard(cl_path, args.force):
                cl_pdf, cl_v, _ = _convert_pdf_versioned(cl_path)
                print(f"  ✓ CL: {cl_path.name} -> v{cl_v}")

    print(f"✅ Rendered {count} document set(s).")
    if skipped:
        print(f"🛑 Skipped {skipped} stale CV(s) — regenerate them, or pass --force.")


if __name__ == "__main__":
    main()
