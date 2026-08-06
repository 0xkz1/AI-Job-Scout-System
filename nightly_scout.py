"""Nightly scout post-processing — run AFTER scraping/analysis/generation.

1. Diff _analyzed.json against the last run's state to find NEW high matches.
2. Auto-review the CV/CL of new matches in the top review_top_percent of the
   ranked pool (selection.select_top("review", ...) — same mechanism CV/CL
   generation already used, now shared instead of reinvented).
3. Print a Telegram-ready summary to stdout — the Hermes cron job runs in
   no-agent mode, so stdout IS the notification. Empty stdout = silent night.

First run (no state file) records a baseline silently so the existing
backlog doesn't spam the channel.

Env overrides: SCOUT_NOTIFY_MIN (default 0.70).

Review used to be gated on an absolute composite_score floor (REVIEW_MIN, env
SCOUT_REVIEW_MIN = 0.80) while generation already went through
selection.select_top() on config.yaml:generation_top_percent — two mechanisms
answering one question. Switched 2026-08-06 to select_top("review", ...), so
both stages rank the same pool the same way and the cut is set in one place.

Selection is by composite_score rank, nothing else: the review score cannot
inform it, because a document has no review score until it has been reviewed.
On the current pool the top 40% cuts at composite 0.53 and covers 488 of 1178
ranked jobs, against 23 under the old 0.80 floor.
"""
import sys, os, json, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import dotenv_values
for k, v in dotenv_values(ROOT / ".env").items():
    if v:
        os.environ.setdefault(k, v)

NOTIFY_MIN = float(os.environ.get("SCOUT_NOTIFY_MIN", "0.70"))

OUTPUT_DIR = ROOT / "10_output"
STATE_FILE = OUTPUT_DIR / "_nightly_state.json"
RUN_SUMMARY = OUTPUT_DIR / "_nightly_run_summary.tsv"
SITE_YIELD = OUTPUT_DIR / "_nightly_site_yield.tsv"
YIELD_HISTORY = OUTPUT_DIR / "_nightly_site_yield_history.json"

# Nights of zero jobs, from a site that exited cleanly, before it is reported.
# One is normal — a narrow keyword set on a quiet night genuinely returns
# nothing new. Two in a row is not: it means the scrape is broken in the way
# that leaves no trace, which is how Indeed went 11 nights unnoticed. LinkedIn
# is the standing risk here, since the guest scraper parses class names that
# LinkedIn can rename without warning.
DRY_NIGHTS_BEFORE_WARNING = 2
YIELD_HISTORY_KEEP = 10
CV_DIR = OUTPUT_DIR / "10_cvs"
CL_DIR = OUTPUT_DIR / "10_cover-letters"
MATCH_DIR = OUTPUT_DIR / "00_matches"


def load_run_summary() -> list[dict]:
    """Per-site scrape outcomes written by job_scout_nightly.sh, as
    [{site, exit, elapsed, status}]. Empty when the summary is absent (script
    ran without the run_site wrapper, or was killed before writing any) — the
    caller then falls back to the old score-only behaviour."""
    out = []
    try:
        for line in RUN_SUMMARY.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            site, rc, elapsed = parts[0], int(parts[1]), int(parts[2])
            status = "ok" if rc == 0 else "timeout" if rc == 124 else "error"
            out.append({"site": site, "exit": rc, "elapsed": elapsed, "status": status})
    except Exception:
        pass
    return out


def summarize_sites(summary: list[dict]) -> tuple[str, bool]:
    """(one-line health string, any_failure). Failures list first so a bad
    site is legible at a glance in Telegram."""
    ok = [s for s in summary if s["status"] == "ok"]
    bad = [s for s in summary if s["status"] != "ok"]
    parts = []
    for s in bad:
        label = "タイムアウト" if s["status"] == "timeout" else f"失敗(exit {s['exit']})"
        parts.append(f"❌{s['site']} {label}")
    if ok:
        parts.append(f"✓{'・'.join(s['site'] for s in ok)}")
    return "  ".join(parts), bool(bad)


def load_site_yield() -> dict[str, int]:
    """Per-site job counts written by run.py via JIS_YIELD_FILE, as {site: count}.
    Empty when the file is absent — an older nightly script, or a run that never
    reached the scrape phase."""
    out: dict[str, int] = {}
    try:
        for line in SITE_YIELD.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            try:
                out[parts[0]] = int(parts[1])
            except ValueError:
                continue
    except Exception:
        pass
    return out


def update_yield_history(yields: dict[str, int]) -> dict[str, list[int]]:
    """Append tonight's counts to the rolling per-site history and save it.

    Only sites that ran tonight are appended, so a site removed from the nightly
    keeps its last known run rather than accumulating phantom zeroes that would
    eventually fire a warning about a scraper nobody is running.
    """
    try:
        history = json.loads(YIELD_HISTORY.read_text())
        if not isinstance(history, dict):
            history = {}
    except Exception:
        history = {}

    for site, count in yields.items():
        past = history.get(site) or []
        if not isinstance(past, list):
            past = []
        history[site] = (past + [count])[-YIELD_HISTORY_KEEP:]

    try:
        YIELD_HISTORY.write_text(json.dumps(history, indent=0))
    except OSError:
        pass
    return history


def dry_sites(history: dict[str, list[int]], yields: dict[str, int]) -> list[str]:
    """Sites that ran tonight and have returned nothing for enough consecutive
    nights to be reported. Judged on the recorded history, so a site is only
    flagged once there is evidence rather than on its first quiet night."""
    flagged = []
    for site in yields:
        recent = (history.get(site) or [])[-DRY_NIGHTS_BEFORE_WARNING:]
        if len(recent) >= DRY_NIGHTS_BEFORE_WARNING and not any(recent):
            flagged.append(f"{site}({len(recent)}晩連続0件)")
    return flagged


def load_jobs() -> list[dict]:
    try:
        return json.loads((OUTPUT_DIR / "_analyzed.json").read_text())
    except Exception:
        return []


def resolve_base(company, title, url):
    from matcher import make_safe_name
    base = make_safe_name(company, title)
    hashed = f"{base}_{hashlib.md5((url or '').encode()).hexdigest()[:6]}"
    if not (CV_DIR / f"{base}_CV.md").exists() and (CV_DIR / f"{hashed}_CV.md").exists():
        return hashed
    return base


def main():
    jobs = load_jobs()
    if not jobs:
        print("⚠️ job-scout-nightly: _analyzed.json missing or empty — pipeline may have failed")
        return

    # Scoring invariants, before anything is reported. Every scoring bug this
    # pipeline has had was silent — a plausible number, no error — so a nightly run
    # would have reproduced it indefinitely (review_score_threshold was
    # unreachable for months, and 255/255 reviews read 提出不可 as a result).
    # Printed, not raised: stdout is the Telegram notification here, and a broken
    # invariant is worth surfacing without discarding the night's real findings.
    try:
        from invariants import report as _invariant_report
        _invariant_report()
    except Exception as e:  # noqa: BLE001 - never let the check take the run down
        print(f"⚠️ 整合性チェックを実行できませんでした: {type(e).__name__}: {e}")

    current = {}
    for j in jobs:
        url = j.get("url")
        if url:
            current[url] = j

    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps({"seen": sorted(current)}, indent=0))
        return  # baseline run: stay silent

    seen = set(json.loads(STATE_FILE.read_text()).get("seen", []))
    new_jobs = [j for u, j in current.items() if u not in seen]

    # _analyzed.json intentionally keeps filtered-out jobs too (so changing
    # exclude keywords later doesn't require a re-scrape) — composite_score
    # alone doesn't know that. Without re-checking passes_filter() here, a
    # job with an excluded title (e.g. "Senior Product Designer" when
    # "senior" is excluded) that happens to score above NOTIFY_MIN would
    # reach Telegram even though it never gets a CV/report and the Streamlit
    # UI (which does call passes_filter live) would never show it either.
    import yaml
    from filter import passes_filter
    config = yaml.safe_load((ROOT / "config.yaml").read_text()) or {}

    new_high = sorted(
        (j for j in new_jobs
         if j.get("match", {}).get("composite_score", 0) >= NOTIFY_MIN
         and passes_filter(j, config)[0]),
        key=lambda j: j["match"]["composite_score"], reverse=True,
    )

    # Same jobs list object passed to select_top so its dedup keeps the
    # original dicts (selection._dedupe returns winners by reference, never a
    # copy) — id() membership below is safe because of that, not despite it.
    from selection import select_top
    review_set_ids = {id(j) for j in select_top("review", config, jobs=jobs)}

    reviewed, review_failed, reviewed_jobs = [], [], set()
    ready_count = 0
    for j in new_high:
        if id(j) not in review_set_ids:
            continue
        base = resolve_base(j.get("company", ""), j.get("title", ""), j.get("url", ""))
        for kind, d in (("CV", CV_DIR), ("CL", CL_DIR)):
            doc = d / f"{base}_{kind}.md"
            if not doc.exists():
                continue
            # Locked (hand-edited / applied / expired): run_review writes a
            # backlink into the document, and a verdict on a submitted or
            # closed application is advice that can no longer be taken.
            import gen_version
            if gen_version.is_locked(base, doc.read_text(encoding="utf-8"), MATCH_DIR):
                continue
            try:
                from reviewer import run_review, review_is_current, get_score_threshold, _extract_score
                if not review_is_current(doc)[0]:
                    review_path = run_review(kind, doc, j)
                    reviewed.append(f"{base}_{kind}")
                    reviewed_jobs.add(base)
                    score, fact_block, _nits = _extract_score(
                        review_path.read_text(encoding="utf-8"))
                    if score is not None and not fact_block and score >= get_score_threshold():
                        ready_count += 1
            except Exception as e:
                review_failed.append(f"{base}_{kind}: {str(e)[:60]}")

    STATE_FILE.write_text(json.dumps({"seen": sorted(seen | set(current))}, indent=0))

    # Scrape health: a site timeout/error means the notification must fire even
    # with zero new matches — otherwise "ran clean, nothing new" and "reed died,
    # so of course nothing new" look identical (the 35-silent-failures trap).
    summary = load_run_summary()
    health_line, any_failure = summarize_sites(summary)

    # A clean exit with an empty result set is the failure the exit code cannot
    # express, so it breaks the silence on the same terms as an outright error.
    yields = load_site_yield()
    dry = dry_sites(update_yield_history(yields), yields)
    dry_line = f"🕳 収穫ゼロ: {'・'.join(dry)} — セレクタ切れの疑い" if dry else ""

    if not new_high and not any_failure and not dry:
        return  # every site ok, nothing new — the only truly silent case

    if not new_high:
        # No new matches but a site failed or came back empty — say which.
        detail = "\n".join(x for x in (health_line, dry_line) if x)
        print(f"⚠️ AI Job Scout — 新着なし。スクレイプに問題:\n{detail}")
        return

    lines = [f"🎯 AI Job Scout — 新着の高マッチ {len(new_high)}件 (新規求人{len(new_jobs)}件中)"]
    if health_line:
        lines.append(f"📡 {health_line}")
    if dry_line:
        lines.append(dry_line)
    for j in new_high[:10]:
        s = j["match"]["composite_score"]
        # Distinguishes "reviewed tonight" from "notified but ranked outside
        # the top review_top_percent" — restored by the switch to select_top,
        # which naturally leaves some of new_high out again (a fixed
        # percentage of the pool, not everything above NOTIFY_MIN).
        flag = "🔥" if id(j) in review_set_ids else "✨"
        lines.append(f"{flag} {s*100:.0f}%  {j.get('company','?')} — {j.get('title','?')}")
        if j.get("location"):
            lines[-1] += f"  ({j['location']})"
    if len(new_high) > 10:
        lines.append(f"…ほか{len(new_high)-10}件")
    if reviewed_jobs:
        lines.append(
            f"📝 {len(reviewed_jobs)}求人分のCV/CLをレビュー ({len(reviewed)}ファイル) "
            f"— うち提出可 {ready_count}件 → Obsidianで確認"
        )
    if review_failed:
        lines.append(f"⚠️ レビュー失敗: {'; '.join(review_failed[:3])}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
