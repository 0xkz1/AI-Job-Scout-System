"""Nightly scout post-processing — run AFTER scraping/analysis/generation.

1. Diff _analyzed.json against the last run's state to find NEW high matches.
2. Auto-review the CV/CL of new matches scoring >= REVIEW_MIN.
3. Print a Telegram-ready summary to stdout — the Hermes cron job runs in
   no-agent mode, so stdout IS the notification. Empty stdout = silent night.

First run (no state file) records a baseline silently so the existing
backlog doesn't spam the channel.

Env overrides: SCOUT_NOTIFY_MIN (default 0.70), SCOUT_REVIEW_MIN (0.80).
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
REVIEW_MIN = float(os.environ.get("SCOUT_REVIEW_MIN", "0.80"))

OUTPUT_DIR = ROOT / "10_output"
STATE_FILE = OUTPUT_DIR / "_nightly_state.json"
RUN_SUMMARY = OUTPUT_DIR / "_nightly_run_summary.tsv"
CV_DIR = OUTPUT_DIR / "10_cvs"
CL_DIR = OUTPUT_DIR / "10_cover-letters"


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

    reviewed, review_failed, reviewed_jobs = [], [], set()
    ready_count = 0
    for j in new_high:
        if j["match"]["composite_score"] < REVIEW_MIN:
            continue
        base = resolve_base(j.get("company", ""), j.get("title", ""), j.get("url", ""))
        for kind, d in (("CV", CV_DIR), ("CL", CL_DIR)):
            doc = d / f"{base}_{kind}.md"
            if not doc.exists():
                continue
            try:
                from reviewer import run_review, review_is_current, get_score_threshold, _extract_score
                if not review_is_current(doc)[0]:
                    review_path = run_review(kind, doc, j)
                    reviewed.append(f"{base}_{kind}")
                    reviewed_jobs.add(base)
                    score, fact_block = _extract_score(
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

    if not new_high and not any_failure:
        return  # every site ok, nothing new — the only truly silent case

    if not new_high:
        # No new matches but a site failed — tell the user why it was quiet.
        print(f"⚠️ AI Job Scout — 新着なし。スクレイプに問題:\n{health_line}")
        return

    lines = [f"🎯 AI Job Scout — 新着の高マッチ {len(new_high)}件 (新規求人{len(new_jobs)}件中)"]
    if health_line:
        lines.append(f"📡 {health_line}")
    for j in new_high[:10]:
        s = j["match"]["composite_score"]
        flag = "🔥" if s >= REVIEW_MIN else "✨"
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
