#!/usr/bin/env python3
"""
Data Integrity Check Script for Job Scraper Pipeline
=====================================================
Checks consistency between match reports, CVs, and cover letters.
"""

import os
import re
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
MATCHES_DIR = OUTPUT_DIR / "00_matches"
CVS_DIR = OUTPUT_DIR / "00_cvs"
LETTERS_DIR = OUTPUT_DIR / "00_cover-letters"


def extract_company_title(filename: str, file_type: str) -> tuple[str, str] | None:
    """Extract (company, title) from filename."""
    if file_type == "match":
        # Format: {company}_{title}_match.md
        match = re.match(r"^(.+?)_(.+?)_match\.md$", filename)
    elif file_type == "cv":
        # Format: {company}_{title}_CV.md
        match = re.match(r"^(.+?)_(.+?)_CV\.md$", filename)
    elif file_type == "letter":
        # Format: cover_letter_{company}_{title}.md
        match = re.match(r"^cover_letter_(.+?)_(.+?)\.md$", filename)
    else:
        return None
    if match:
        return (match.group(1), match.group(2))
    return None


def scan_directory(dir_path: Path, file_type: str) -> dict[tuple[str, str], str]:
    """Scan directory and return mapping of (company, title) -> filename."""
    result = {}
    for f in dir_path.glob("*.md"):
        extracted = extract_company_title(f.name, file_type)
        if extracted:
            # Normalize for comparison
            company = extracted[0].lower().replace("-", "_")
            title = extracted[1].lower().replace("-", "_")
            result[(company, title)] = f.name
    return result


def main():
    print("=" * 60)
    print("📊 DATA INTEGRITY CHECK")
    print("=" * 60)

    # Scan all three directories
    matches = scan_directory(MATCHES_DIR, "match")
    cvs = scan_directory(CVS_DIR, "cv")
    letters = scan_directory(LETTERS_DIR, "letter")

    print(f"\n📁 00_matches/:     {len(matches)} files")
    print(f"📁 00_cvs/:        {len(cvs)} files")
    print(f"📁 00_cover-letters/: {len(letters)} files")

    # Check matches -> CVs
    print("\n" + "=" * 60)
    print("🔍 CHECK: Every match report has a corresponding CV")
    print("=" * 60)
    missing_cv = []
    for key, fname in matches.items():
        if key not in cvs:
            missing_cv.append((key, fname))
    if missing_cv:
        print(f"❌ {len(missing_cv)} match reports MISSING CVs:")
        for key, fname in missing_cv[:20]:
            print(f"   - {fname}")
        if len(missing_cv) > 20:
            print(f"   ... and {len(missing_cv) - 20} more")
    else:
        print("✅ All match reports have corresponding CVs")

    # Check CVs -> matches
    print("\n" + "=" * 60)
    print("🔍 CHECK: Every CV has a corresponding match report")
    print("=" * 60)
    missing_match = []
    for key, fname in cvs.items():
        if key not in matches:
            missing_match.append((key, fname))
    if missing_match:
        print(f"❌ {len(missing_match)} CVs MISSING match reports:")
        for key, fname in missing_match[:20]:
            print(f"   - {fname}")
        if len(missing_match) > 20:
            print(f"   ... and {len(missing_match) - 20} more")
    else:
        print("✅ All CVs have corresponding match reports")

    # Check matches -> cover letters
    print("\n" + "=" * 60)
    print("🔍 CHECK: Every match report has a corresponding cover letter")
    print("=" * 60)
    missing_letter = []
    for key, fname in matches.items():
        if key not in letters:
            missing_letter.append((key, fname))
    if missing_letter:
        print(f"❌ {len(missing_letter)} match reports MISSING cover letters:")
        for key, fname in missing_letter[:20]:
            print(f"   - {fname}")
        if len(missing_letter) > 20:
            print(f"   ... and {len(missing_letter) - 20} more")
    else:
        print("✅ All match reports have corresponding cover letters")

    # Check cover letters -> matches
    print("\n" + "=" * 60)
    print("🔍 CHECK: Every cover letter has a corresponding match report")
    print("=" * 60)
    missing_match_for_letter = []
    for key, fname in letters.items():
        if key not in matches:
            missing_match_for_letter.append((key, fname))
    if missing_match_for_letter:
        print(f"❌ {len(missing_match_for_letter)} cover letters MISSING match reports:")
        for key, fname in missing_match_for_letter[:20]:
            print(f"   - {fname}")
        if len(missing_match_for_letter) > 20:
            print(f"   ... and {len(missing_match_for_letter) - 20} more")
    else:
        print("✅ All cover letters have corresponding match reports")

    # Check for duplicates within each directory
    print("\n" + "=" * 60)
    print("🔍 CHECK: Duplicate files within each directory")
    print("=" * 60)

    def check_duplicates(file_map: dict, label: str):
        seen = {}
        for key, fname in file_map.items():
            if key in seen:
                seen[key].append(fname)
            else:
                seen[key] = [fname]
        dupes = {k: v for k, v in seen.items() if len(v) > 1}
        if dupes:
            print(f"❌ {label}: {len(dupes)} duplicate keys found:")
            for k, v in list(dupes.items())[:10]:
                print(f"   Key {k}: {v}")
            if len(dupes) > 10:
                print(f"   ... and {len(dupes) - 10} more")
        else:
            print(f"✅ {label}: No duplicates")

    check_duplicates(matches, "00_matches")
    check_duplicates(cvs, "00_cvs")
    check_duplicates(letters, "00_cover-letters")

    # Summary
    print("\n" + "=" * 60)
    print("📋 SUMMARY")
    print("=" * 60)
    total_issues = len(missing_cv) + len(missing_match) + len(missing_letter) + len(missing_match_for_letter)
    if total_issues == 0:
        print("✅ ALL CHECKS PASSED - Data is consistent!")
    else:
        print(f"❌ {total_issues} total integrity issues found")
        print(f"   - Matches without CVs: {len(missing_cv)}")
        print(f"   - CVs without matches: {len(missing_match)}")
        print(f"   - Matches without letters: {len(missing_letter)}")
        print(f"   - Letters without matches: {len(missing_match_for_letter)}")

    return total_issues == 0


if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)