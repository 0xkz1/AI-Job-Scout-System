#!/bin/bash
# NOT the scheduled nightly. Do not put this in crontab.
#
# The nightly that actually runs is job-scout-nightly, a Hermes cron job on the
# `archivist` profile at 02:00, whose script is
# dotfiles/hermes/profiles/archivist/scripts/job_scout_nightly.sh. It is
# invisible to `crontab -l`, to systemd timers, and to a bare `hermes cron list`
# — that lists the default profile only, so you have to ask each profile by
# name. Believing there was no scheduler is how this file came to be rewritten
# as a parallel nightly in the first place.
#
# Scheduling both would run two pipelines against one _analyzed.json.
#
# Kept as the manual/foreground equivalent: same stages, simpler budgeting, no
# Telegram delivery. Use it to run the pipeline by hand or to test a stage in
# isolation. Anything that belongs in the real nightly belongs in
# job_scout_nightly.sh.
#
# The whole nightly, in one process.
#
# It used to be a fragment: scraper_saved.py and `run.py --site indeed`. Three
# things that have to happen every night were not in it, and each was found
# missing only by someone noticing an absence rather than an error:
#
#   - url-list.md was never ingested, so pasted job links sat unread. 44 of them
#     had been scraped into staging and were waiting weeks to reach the database.
#   - the pipeline was pinned to a single site, so LinkedIn, Reed, Adzuna,
#     Guardian and the remote APIs contributed nothing on the scheduled path.
#   - reviews never ran at all. run.py does not review; nightly_scout.py does.
#     237 jobs had a generated CV and no review because nothing invoked it.
#
# Stages are independent: one failing must not cancel the rest, so each is
# `|| true` with its status recorded. Each also gets a timeout, because a hung
# browser is the failure that silently eats a whole night.
set -uo pipefail
cd /media/kz003/atelier/00_Kazuki/career/Job-Intelligence-System

LOG_DIR="10_output/_debug/cron"
mkdir -p "${LOG_DIR}"
STAMP=$(date '+%Y%m%d_%H%M%S')
LOG="${LOG_DIR}/nightly_${STAMP}.log"
exec > >(tee -a "${LOG}") 2>&1
echo "=== nightly run ${STAMP} ==="

# The venv, not whatever `python3` resolves to. The two are not interchangeable:
# on 2026-08-13 scikit-learn was importable from the system interpreter and
# absent from the venv, so the TF-IDF context fallback returned a constant 0.5
# under one and a real score under the other — which interpreter a scheduled run
# happened to pick decided whether a sixth of the database was scored.
PYTHON="$(dirname "$0")/.venv/bin/python3"
[ -x "${PYTHON}" ] || PYTHON="python3"

# Indeed answers a headless browser with a Cloudflare challenge and the only way
# through is a headed relaunch, which needs an X display cron does not have.
# scraper_indeed._headed_display_available() detects that and raises rather than
# reporting an empty search — but detecting it does not scrape anything, the
# searches are simply lost. Its own message says to use xvfb-run.
#
# DISPLAY being set does NOT mean an X server is reachable: cron inherits it from
# the desktop session that installed the crontab while having no access to that
# server, which is how Indeed spent 11 days returning nothing while every night
# exited 0. Check the socket, not the variable.
RUNNER=()
if [ -z "${DISPLAY:-}" ] || [ ! -e "/tmp/.X11-unix/X${DISPLAY#*:}" ]; then
    if command -v xvfb-run >/dev/null 2>&1; then
        RUNNER=(xvfb-run -a --server-args="-screen 0 1920x1080x24")
    else
        echo "⚠ no usable X display and no xvfb-run — Indeed will lose every" \
             "Cloudflare-challenged search. Install xvfb."
    fi
fi

declare -A STATUS
stage() {
    local name="$1" limit="$2"; shift 2
    echo ""
    echo "──────── ${name} (timeout ${limit}) ────────"
    local start; start=$(date +%s)
    if timeout "${limit}" "$@"; then
        STATUS[$name]="ok"
    elif [ $? -eq 124 ]; then
        STATUS[$name]="TIMEOUT"
    else
        STATUS[$name]="failed"
    fi
    echo "── ${name}: ${STATUS[$name]} ($(( $(date +%s) - start ))s)"
}

# Order matters. url-list and saved-jobs write into 00_saved/ staging; run.py
# ingests that staging as part of its own merge, so both must land before it.
# Both review stages read what run.py ranked, so they come after.
stage url_list  20m "${RUNNER[@]}" "${PYTHON}" scraper_url_list.py
stage saved     20m "${RUNNER[@]}" "${PYTHON}" scraper_saved.py
stage pipeline   6h "${RUNNER[@]}" "${PYTHON}" -u run.py

# Everything below this line spends money on postings that are still open, and
# roughly half of them were not: the first full sweep on 2026-09-01 found 2351
# of 4462 already closed — 77% of reed's, 60% of adzuna's. A closed posting was
# re-scored, re-reviewed and handed fresh documents for as long as it sat in the
# database, because nothing ever asked the site. The tick this sets is a
# job-scoped lock (gen_version), so it is what points the stages below at live
# work.
#
# After the pipeline, not before it: the pipeline is the night's real work and
# must not lose hours to this. --limit spreads the sweep over nights, the same
# reasoning as the rescore cap; a `live` verdict is trusted for a week, so the
# standing load is the slice that aged out rather than the whole pool.
stage expiry    30m "${PYTHON}" -u check_expired.py --limit 250

# run.py scores what it ingests and nothing else, so anything already in the
# database when the persona changes keeps the score it was given against the old
# one. Two scales in one ranking rank nothing (5dedcf8), and the drift is
# invisible: a stale score looks exactly like a fresh one. National Westminster
# Bank's UI Software Engineer sat at composite 0.80 — the top of the pool — on a
# persona two revisions old, because it arrived after the last full rescore.
#
# Ordinarily this is small: postings ingested since the last run, which carry no
# score from the current persona at all. 385 tonight. It only becomes large when
# the persona genuinely changes — rescore_context.PERSONA_DRIFT_THRESHOLD keeps
# a 1.4% edit from marking the whole corpus stale, after an earlier version did
# exactly that and 63% of the rescored postings came back with the same number.
#
# The cap is for the case that remains: a real persona edit, which legitimately
# invalidates everything. 400 a night spreads that over a few nights instead of
# one six-hour bill, and keeps the nightly's length predictable — the same
# reasoning as cv_generation_limit, a bound on what a run writes rather than a
# line below which work never happens.
#
# Before the review stages, so they rank on scores from the current persona.
stage rescore    3h "${PYTHON}" -u rescore_context.py --limit 400

# Two review stages, because they answer different questions and neither covers
# the other.
#
# nightly_scout is a DIFF: it compares against _nightly_state.json and reviews
# only what is new since last time, then prints the Telegram summary. That is
# what makes it a good notifier and a bad backfiller — run it twice in one
# evening and the second run finds nothing, because the first updated the state.
# It is not that it failed; it is that "new" is all it was ever asked for.
#
# backfill is the sweep: every document in the review selection that has no
# review file yet. --new-only is what keeps it affordable — rereview_top.py
# overwrites existing reviews by default, which is right when the reviewer's
# logic changed and ruinous as a nightly habit.
#
# Without the sweep the backlog only grows: 237 jobs held a generated CV and no
# review, including ones sitting in the top 10% of the pool, because every
# arrival after their own night was someone else's "new".
stage review    4h "${PYTHON}" -u nightly_scout.py
stage backfill  4h "${PYTHON}" -u rereview_top.py --new-only

echo ""
echo "──────── summary ────────"
for k in url_list saved pipeline expiry rescore review backfill; do
    printf '  %-10s %s\n' "$k" "${STATUS[$k]:-skipped}"
done
echo "  00_matches:       $(find 10_output/00_matches -name '*.md' 2>/dev/null | wc -l) reports"
echo "  10_cvs:           $(ls 10_output/10_cvs/*.md 2>/dev/null | wc -l) CVs"
echo "  10_cover-letters: $(ls 10_output/10_cover-letters/*.md 2>/dev/null | wc -l) cover letters"
echo "  15_reviews:       $(ls 10_output/15_reviews/*.md 2>/dev/null | wc -l) reviews"
echo "  log:              ${LOG}"

# Non-zero only if every stage failed — a partial night is still a useful night,
# and a red cron line for one flaky site trains the reader to ignore red lines.
# Keep this list in step with the stages above; it silently under-reports if a
# stage is added and not listed here.
for k in url_list saved pipeline expiry rescore review backfill; do
    [ "${STATUS[$k]:-}" = "ok" ] && exit 0
done
exit 1
