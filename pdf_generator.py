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


def main():
    parser = argparse.ArgumentParser(description="Generate PDFs using the live system renderer.")
    parser.add_argument("--file", default="", help="Path to specific Markdown file to convert")
    parser.add_argument("--company", default="", help="Filter by company name")
    parser.add_argument("--title", default="", help="Filter by job title")
    parser.add_argument("--threshold", type=float, default=0.0,
                        help="Only generate PDFs for jobs with match score >= threshold")
    parser.add_argument("--cv-only", action="store_true", help="Skip cover letters")
    args = parser.parse_args()

    PDF_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Single File Mode
    if args.file:
        file_path = Path(args.file).resolve()
        if not file_path.exists():
            print(f"❌ File not found: {file_path}")
            sys.exit(1)
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
    for cv_path in cv_files:
        pdf_path, version, is_new = _convert_pdf_versioned(cv_path)
        print(f"  ✓ CV: {cv_path.name} -> v{version}")
        count += 1

        if not args.cv_only:
            stem = cv_path.stem.removesuffix("_CV")
            cl_path = CL_DIR / f"{stem}_CL.md"
            if cl_path.exists():
                cl_pdf, cl_v, _ = _convert_pdf_versioned(cl_path)
                print(f"  ✓ CL: {cl_path.name} -> v{cl_v}")

    print(f"✅ Rendered {count} document set(s).")


if __name__ == "__main__":
    main()
