"""Collapse tracking-param duplicate records in _analyzed.json.

Same root cause as the Digital Waffle case: run.py's known-URL check compared
raw strings, so "?lipi=" (LinkedIn) and "?utm_medium=api" (Adzuna) copies of a
posting already in the DB were ingested as separate jobs. The re-scrape is
always the weaker record — the filter/LLM budget went to the original, so the
copy carries TF-IDF context and loses calculate_title_relevance's LLM rescue.

Keeper: the record with an LLM context read, then the higher composite.
Canonical URL: the group's clean (query-free) URL when one exists.
The loser's own match report (hash-suffixed, or under its own base name when
the two records disagreed on company casing) is moved to .matches_archive,
never deleted. CV/CL/reviews are shared with the keeper — none are touched.

DRY-RUN by default; pass --apply to write.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

JIS = Path(__file__).resolve().parent
sys.path.insert(0, str(JIS))
sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--apply"] + \
           (["--apply"] if "--apply" in sys.argv else [])
APPLY = "--apply" in sys.argv
sys.argv = [sys.argv[0]]  # imported modules must not see our flags

from matcher import (  # noqa: E402
    generate_match_report, make_safe_name, read_applied_flag, read_expired_flag,
    read_carried_properties,
)
from scraper_url_list import normalize_url  # noqa: E402
import regen_match_reports as R  # noqa: E402
import gen_version  # noqa: E402

OUT = JIS / "10_output"
DB_PATH = OUT / "_analyzed.json"
MATCH_DIR = OUT / "00_matches"
ARCHIVE = OUT / ".matches_archive"
INDEX = MATCH_DIR / "_index.json"


def rank(job):
    m = job.get("match") or {}
    return (m.get("context_source") == "llm", m.get("composite_score", 0),
            len(job.get("description") or ""))


def report_paths(job):
    """Every match report this record could own: base name and URL-hash name."""
    base = make_safe_name(job.get("company", ""), job.get("title", ""))
    h = hashlib.md5((job.get("url") or "").encode()).hexdigest()[:6]
    return [MATCH_DIR / f"{base}.md", MATCH_DIR / f"{base}_{h}.md"]


def fm_url(path):
    m = re.search(r'^url:\s*"?(.*?)"?\s*$', path.read_text(encoding="utf-8")[:2000], re.M)
    return m.group(1) if m else None


db = json.loads(DB_PATH.read_text())
groups = defaultdict(list)
for j in db:
    if j.get("url"):
        groups[normalize_url(j["url"])].append(j)

if APPLY:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tgz = OUT / f".backup_pre_url_variant_merge_{ts}.tgz"
    subprocess.run(["tar", "czf", str(tgz), "10_output/_analyzed.json",
                    "10_output/00_matches"], cwd=JIS, check=True)
    print(f"backup: {tgz.name}")

drop_ids, dropped_urls, to_archive, keepers = set(), set(), [], []
for key, members in groups.items():
    if len(members) < 2:
        continue
    members = sorted(members, key=rank, reverse=True)
    keeper, losers = members[0], members[1:]
    clean = next((j["url"] for j in members if "?" not in j["url"]), None)
    canonical = clean or keeper["url"]
    dups = sorted({j["url"] for j in members} - {canonical})

    print(f"\n{key}")
    print(f"  KEEP {rank(keeper)[1]:.2f} {keeper.get('title')} | {keeper.get('company')}")
    for l in losers:
        print(f"  DROP {rank(l)[1]:.2f} {l.get('title')} | {l.get('company')}")
        drop_ids.add(id(l))
        dropped_urls.add(l["url"])
        # A report belongs to the loser only if its frontmatter URL says so —
        # the shared base-name file is the keeper's in every other case.
        for p in report_paths(l):
            if p.exists() and fm_url(p) == l["url"] and p not in [q for q, _ in to_archive]:
                if gen_version.job_lock_reason(p.stem, MATCH_DIR):
                    print(f"    ! {p.name} is applied/expired-locked — left in place")
                    continue
                to_archive.append((p, l["url"]))
                print(f"    archive report: {p.name}")
    keepers.append((keeper, canonical, dups))
    print(f"  url -> {canonical}")

print(f"\ngroups={len(keepers)} records_dropped={len(drop_ids)} "
      f"reports_archived={len(to_archive)} apply={APPLY}")

if not APPLY:
    sys.exit(0)

for keeper, canonical, dups in keepers:
    keeper["url"] = canonical
    keeper["duplicate_urls"] = sorted(set((keeper.get("duplicate_urls") or []) + dups))

kept = [j for j in db if id(j) not in drop_ids]
DB_PATH.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"_analyzed.json: {len(db)} -> {len(kept)} records")

ARCHIVE.mkdir(exist_ok=True)
for path, _ in to_archive:
    dest = ARCHIVE / path.name
    if dest.exists():
        dest = ARCHIVE / f"{path.stem}_urlvariant{path.suffix}"
    shutil.move(str(path), str(dest))
print(f"archived {len(to_archive)} reports -> {ARCHIVE.name}/")

# The loser can be the one holding the PLAIN base name — it happens whenever the
# keeper is the tracking-param record (Lockside, Paddle: the clean-URL copy was
# the weaker one). Archiving it then strands the keeper under its hash suffix
# while the name the CV/CL wikilinks resolve against sits empty, so promote the
# keeper's report back onto the base name.
for keeper, canonical, dups in keepers:
    base = report_paths(keeper)[0]
    if base.exists():
        continue
    # The suffix was hashed from whichever URL the record carried when the
    # report was written — which is now one of duplicate_urls, not canonical.
    for u in [canonical, *dups]:
        hashed = MATCH_DIR / (f"{base.stem}_"
                              f"{hashlib.md5(u.encode()).hexdigest()[:6]}.md")
        if hashed.exists():
            hashed.rename(base)
            print(f"promoted {hashed.name} -> {base.name}")
            break

# Legacy index: drop the dropped records' rows, repoint survivors at the
# canonical URL.
idx = json.loads(INDEX.read_text(encoding="utf-8"))
before = len(idx)
idx = [e for e in idx if e.get("url") not in dropped_urls]
canon_by_norm = {normalize_url(k["url"]): k["url"] for k, _, _ in
                 [(k, c, d) for k, c, d in keepers]}
for e in idx:
    u = e.get("url")
    if u and normalize_url(u) in canon_by_norm:
        e["url"] = canon_by_norm[normalize_url(u)]
INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"_index.json: {before} -> {len(idx)} entries")

# Re-render each keeper's surviving report so its frontmatter URL and
# "Also posted at" line match the merged record. Same code path as
# regen_match_reports, one file at a time — the vault-wide run would rewrite
# ~150 unrelated reports that drifted in the last nightly.
rendered = 0
for keeper, _, _ in keepers:
    path = next((p for p in report_paths(keeper) if p.exists()), None)
    if path is None:
        print(f"  ! no report on disk for {keeper.get('title')} — skipped")
        continue
    if gen_version.job_lock_reason(path.stem, MATCH_DIR):
        print(f"  ! {path.name} applied/expired-locked — left as is")
        continue
    text = path.read_text(encoding="utf-8")
    fm = R.parse_frontmatter(text)
    job = dict(keeper)
    if fm.get("saved_at"):
        job["scraped_at"] = fm["saved_at"]
    for k in ("route", "source", "type"):
        if fm.get(k):
            job[k] = fm[k]
    new_text = generate_match_report(
        job, dict(job["match"]),
        R.wikilink_to_filename(fm.get("cv", "")),
        R.wikilink_to_filename(fm.get("cover_letter", "")),
        expired=read_expired_flag(path),
        applied=read_applied_flag(path),
        carried=read_carried_properties(path),
    )
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        rendered += 1
print(f"re-rendered {rendered} keeper reports")
