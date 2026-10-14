#!/usr/bin/env python3
"""Rename existing PDFs in 10_output/20_pdfs to the Kazuki-Yunome_ prefix and
update all frontmatter references (pdf:, cv_pdf:, cl_pdf:) that point at them.

Internal .md join keys (company_title) are NOT touched — only PDF filenames
and the frontmatter properties that name PDFs.

Usage:
    python3 migrate_pdf_names.py          # dry run
    python3 migrate_pdf_names.py --apply  # rename + rewrite frontmatter
"""
import re
import sys
from pathlib import Path
from doc_paths import md_files

ROOT = Path(__file__).resolve().parent
PDF_DIR = ROOT / "10_output" / "20_pdfs"
PREFIX = "Kazuki-Yunome"
SCAN_DIRS = [ROOT / "10_output" / "10_cvs", ROOT / "10_output" / "10_cover-letters", ROOT / "10_output" / "00_matches"]

APPLY = "--apply" in sys.argv


def pdf_files():
    for p in sorted(PDF_DIR.iterdir()):
        if p.is_file() and p.suffix == ".pdf" and not p.name.startswith(PREFIX):
            # Skip files that already carry the applicant name in any casing
            # (e.g. the legacy manual rename Kazuki_Yunome_Full_Stack_Developer_CV.pdf)
            # so we don't double-prefix them.
            if re.match(r"^Kazuki[-_]Yunome", p.name, re.IGNORECASE):
                print(f"   (skip: already named) {p.name}")
                continue
            yield p


def refs_in_text(text: str) -> list[str]:
    """All PDF filenames referenced as [[...pdf]] in frontmatter."""
    return re.findall(r"\[\[([^\]\n]+\.pdf)\]\]", text)


def main():
    files = list(pdf_files())
    print(f"旧名PDF: {len(files)}件")
    if not APPLY:
        print("(dry run — --apply で実行)")

    # Map old pdf filename -> new pdf filename
    rename_map = {p.name: f"{PREFIX}_{p.name}" for p in files}

    # 1) rename files
    for p in files:
        new = PDF_DIR / rename_map[p.name]
        print(f"  {p.name}  ->  {new.name}")
        if APPLY:
            p.rename(new)

    # 2) rewrite frontmatter refs
    touched = 0
    for d in SCAN_DIRS:
        if not d.exists():
            continue
        for md in md_files(d):
            text = md.read_text(encoding="utf-8")
            orig = text
            for old, new in rename_map.items():
                text = re.sub(rf"\[\[{re.escape(old)}\]\]", f"[[{new}]]", text)
            if text != orig:
                touched += 1
                print(f"  ref: {md.relative_to(ROOT)}")
                if APPLY:
                    md.write_text(text, encoding="utf-8")

    # 3) pdf_versions meta json
    meta = PDF_DIR / ".pdf_versions.json"
    if meta.exists():
        text = meta.read_text(encoding="utf-8")
        orig = text
        for old, new in rename_map.items():
            text = text.replace(f'"{old}"', f'"{new}"')
        if text != orig:
            print(f"  meta: {meta.relative_to(ROOT)}")
            if APPLY:
                meta.write_text(text, encoding="utf-8")

    print(f"frontmatter/meta更新: {touched}ファイル" + (" (dry run)" if not APPLY else ""))


if __name__ == "__main__":
    main()
