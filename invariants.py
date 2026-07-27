"""Runtime checks for the failure mode this pipeline actually has: silence.

Every scoring bug found on 2026-07-25 was invisible. None raised, none logged,
none produced an empty file — each one just wrote a plausible-looking number:

  * review_score_threshold 85 was unreachable (rubric maxed at 100, style penalty
    subtracted up to 30), so submission_ready was false for 255/255 reviews for
    months and nobody noticed.
  * The style penalty outranked rubric coverage, producing 287 pairs where the
    better-fitting document ranked below the worse one.
  * skills_score divided by however many skills the posting happened to list, so
    vague postings scored highest — the component was ANTI-correlated with review
    outcome (r=-0.15).
  * A posting whose scrape returned tracker JavaScript got submission_score 100
    and submission_ready true, off a rubric the reviewer invented from the title.
  * "Class 2 Driver" sat inside the top 30% with title_relevance 0.0, because the
    recompute script skipped jobs whose skills failed to extract.
  * A weights change in config.yaml could not reach already-scored jobs, because
    the recompute read the weights stored on each entry instead.

A nightly cron does not make judgement errors, but it will reproduce all of the
above forever. Tests cannot catch them either: each needs the real database, the
real config and the real review corpus to show up. So these are asserted against
live data on every run, and a violation prints to stdout — which for the Hermes
cron IS the notification.

    python3 invariants.py            # exit 1 on any violation
    python3 invariants.py --warn     # report, always exit 0
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

OUTPUT = ROOT / "10_output"
ANALYZED = OUTPUT / "_analyzed.json"
REVIEWS = OUTPUT / "15_reviews"

# The cron script that actually runs the scrapers. It lives outside this repo, so
# `sites` in config.yaml and the `run_site` lines in there can drift apart with
# nothing to notice — and did: linkedin sat in `sites` for six days without ever
# being invoked. A missing file is not treated as a violation, since the path is
# environment-specific.
NIGHTLY_SCRIPT = Path.home() / "dotfiles/hermes/profiles/archivist/scripts/job_scout_nightly.sh"

# A composite spread this flat means the ranking cannot separate jobs, whatever
# the mean looks like. Before the 2026-07-25 fixes it sat at 0.088 with every job
# inside 0.71 +/- 0.09; after, 0.158. Set below the "after" figure, not at it —
# this is a floor for "still discriminating", not a target to hold.
MIN_COMPOSITE_SD = 0.10

# Enough reviews that a distribution statistic means something.
MIN_REVIEWS_FOR_STATS = 30


def _load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}


def _fm(path: Path) -> dict:
    """Frontmatter of a review file as a flat str->str map."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    out = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            out[key.strip()] = val.strip().strip('"')
    return out


# --- checks -----------------------------------------------------------------
# Each returns a list of violation strings. Empty list = healthy.


def check_submission_threshold_is_reachable(config: dict) -> list[str]:
    """The submission gate must be achievable by a perfect document.

    Exercises the real scorer rather than reasoning about it: a rubric of all
    'Strong' plus a deliberately huge pile of style nits is the best case a
    document can present. If that cannot clear the threshold, the gate is dead
    and every review is 要修正 regardless of quality.
    """
    from reviewer import _extract_score, get_score_threshold

    body = (
        "```yaml\nrubric:\n"
        + "".join(f'  - requirement: "r{i}"\n    evidence: "Strong"\n' for i in range(5))
        + "```\n\n### ❗ 事実\n- **問題なし**。\n\n### ✍️ 文体\n"
        + "".join(f"- nit {i}\n" for i in range(40))
    )
    best, fact_block, nits = _extract_score(body)
    threshold = get_score_threshold()
    if best is None:
        return ["submission scoring returned None for an all-Strong rubric"]
    if best < threshold:
        return [
            f"review_score_threshold={threshold} is unreachable: the best a document "
            f"can score is {best} (all-Strong rubric, {nits} style nits). "
            f"submission_ready will be false for every review."
        ]
    return []


def check_floor_below_selection_cutoff(config: dict) -> list[str]:
    """match_score_threshold must trim the top-N%, not replace it.

    It is documented as a secondary quality guard. Once it rises above the
    top-N% cutoff it silently becomes the primary selector, and the configured
    percentage stops meaning anything — which is how "top 30%" quietly became 68
    jobs out of a 143-job band.
    """
    from selection import ranked_jobs, stage_percent, top_percent_count

    floor = config.get("match_score_threshold")
    if not floor:
        return []
    ranked = ranked_jobs(config)
    if not ranked:
        return []
    out = []
    for stage in ("generation", "review"):
        pct = stage_percent(config, stage)
        k = top_percent_count(len(ranked), pct)
        cutoff = ranked[k - 1]["match"]["composite_score"]
        if float(floor) > cutoff:
            kept = sum(1 for j in ranked[:k] if j["match"]["composite_score"] >= float(floor))
            out.append(
                f"match_score_threshold={floor} exceeds the {stage} top-{pct:g}% cutoff "
                f"({cutoff:.3f}), so the floor is the real selector: {k} jobs in the "
                f"band, {kept} survive. Re-fit the floor (it is an absolute score, so "
                f"any weights change moves it)."
            )
    return out


def check_stored_weights_match_config(config: dict) -> list[str]:
    """Scored jobs must reflect the CURRENT weights.

    Each entry records the weights it was scored with. Recompute used to read
    those instead of config.yaml, so editing weights changed nothing for jobs
    already in the database — the new values applied only to jobs scraped later,
    leaving one database scored under two rules.
    """
    from matcher import DEFAULT_WEIGHTS

    if not ANALYZED.exists():
        return []
    want = dict(DEFAULT_WEIGHTS)
    want.update(config.get("weights") or {})
    stale = Counter()
    for job in json.loads(ANALYZED.read_text(encoding="utf-8")):
        got = (job.get("match") or {}).get("weights")
        if got and any(abs(float(got.get(k, -1)) - float(v)) > 1e-9 for k, v in want.items()):
            stale[json.dumps(got, sort_keys=True)] += 1
    if not stale:
        return []
    total = sum(stale.values())
    worst = stale.most_common(1)[0][0]
    return [
        f"{total} jobs were scored with weights other than config.yaml's "
        f"({want}); commonest stale set {worst}. Run recompute_skill_scores.py."
    ]


def check_irrelevant_titles_excluded(config: dict) -> list[str]:
    """A title-excluded job must not reach a stage.

    title_relevance multiplies the composite, so <0.5 means "hard excluded" and
    0.0 means the composite must be 0. Finding such a job inside a stage's
    selection means the multiplication never reached the stored score.
    """
    from selection import select_top

    out = []
    for stage in ("generation", "review"):
        bad = [
            j for j in select_top(stage, config)
            if float((j.get("match") or {}).get("title_relevance", 1.0)) < 0.5
        ]
        if bad:
            names = ", ".join(f"{j.get('title', '?')[:34]}" for j in bad[:3])
            out.append(
                f"{len(bad)} title-excluded jobs (title_relevance<0.5) are inside the "
                f"{stage} selection: {names}. Stored composite ignores "
                f"title_relevance — recompute_skill_scores.py applies it."
            )
    return out


# Shortest description that could carry a 5-requirement rubric. A search-results
# snippet runs ~150-300 chars and cannot; the junk-description jobs that scored
# review 100 had 0 usable chars. Held here rather than read from
# selection.is_unscoreable on purpose — see check_unscoreable_excluded.
MIN_REVIEWABLE_DESC = 400


def check_unscoreable_excluded(config: dict) -> list[str]:
    """Jobs with no usable description must not reach a stage, and must not hold
    a live submission score.

    Neither the matcher nor the reviewer abstains when the posting failed to
    scrape: the reviewer invents requirements from the job title and finds them
    all met. Those scores read as verdicts and must be null instead.

    Judged with its OWN length rule instead of calling selection.is_unscoreable,
    because that function IS the exclusion being tested — asking it whether the
    exclusion worked makes the check track every loosening of the rule and pass
    unconditionally. It did exactly that: while is_unscoreable still fell back to
    `snippet`, this check reported healthy on a corpus where a 0-char description
    with a 174-char snippet had reached review 91. An invariant has to measure
    against something the implementation cannot move.
    """
    from matcher import make_safe_name
    from selection import select_top

    def too_thin(job: dict) -> bool:
        from matcher import is_junk_description

        desc = job.get("description") or ""
        return len(desc.strip()) < MIN_REVIEWABLE_DESC or is_junk_description(desc)

    out = []
    for stage in ("generation", "review"):
        bad = [j for j in select_top(stage, config) if too_thin(j)]
        if bad:
            names = ", ".join(
                f"{(j.get('title') or '?')[:28]}({len((j.get('description') or '').strip())}c)"
                for j in bad[:3]
            )
            out.append(
                f"{len(bad)} jobs with under {MIN_REVIEWABLE_DESC} chars of description "
                f"are inside the {stage} selection: {names}. The reviewer will invent a "
                f"rubric from the title; ranked_jobs should hold them out."
            )
    if ANALYZED.exists() and REVIEWS.exists():
        # Deduped, like selection: duplicates share one make_safe_name, so scanning
        # raw entries flagged "Nothing / Software Creative Technologist" — a junk
        # 5000-char adzuna scrape sitting beside the real 3996-char LinkedIn one
        # that the review was correctly written from.
        from selection import _dedupe

        thin = {
            make_safe_name(j.get("company", ""), j.get("title", ""))
            for j in _dedupe(json.loads(ANALYZED.read_text(encoding="utf-8")))
            if j.get("match") and too_thin(j)
        }
        live = []
        for path in REVIEWS.glob("*_review.md"):
            stem = path.stem[: -len("_review")]
            base = stem[:-3] if stem.endswith(("_CV", "_CL")) else stem
            if base not in thin:
                continue
            fm = _fm(path)
            if fm.get("submission_score") not in (None, "null"):
                live.append(f"{path.stem}={fm.get('submission_score')}")
        if live:
            out.append(
                f"{len(live)} reviews of jobs with no reviewable description still carry "
                f"a score ({', '.join(live[:3])}). Run invalidate_unscoreable_reviews.py."
            )
    return out


def check_one_entry_per_document_path(config: dict) -> list[str]:
    """Selected jobs must map 1:1 onto document paths.

    make_safe_name(company, title) is the CV/CL/review filename, so two selected
    entries sharing it collide: the report on disk comes from whichever was
    written last while selection ranks by the other. Penguin Recruitment's
    "Geotechnical Design Engineer" was held at 0.34, 0.38 and 0.66 at once.

    Two causes, reported separately because only one loses data. Genuine duplicates
    of the same posting mean dedupe let a repeat through. Distinct postings can also
    collide, because make_safe_name truncates the title at 50 characters and the
    company at 30: "BTEC Tech Awards Sept 22 - Creative Media Production - Examiner"
    and the same posting's "- Moderator" differ only past the cut. Truncation
    collisions are common — 322 of 1895 rows truncate at all — and only matter where
    a document is actually written, so a collision outside the generation set is
    reported as a note rather than as data loss.
    """
    from matcher import make_safe_name
    from selection import ranked_jobs, select_top

    def _name(job: dict) -> str:
        return make_safe_name(job.get("company", ""), job.get("title", ""))

    def _collisions(jobs: list[dict]) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        for job in jobs:
            grouped.setdefault(_name(job), []).append(job)
        return {n: js for n, js in grouped.items() if len(js) > 1}

    out = []
    generated = _collisions(select_top("generation", config))
    if generated:
        name, jobs = next(iter(generated.items()))
        titles = " / ".join(repr(j.get("title", "")) for j in jobs[:2])
        out.append(
            f"{len(generated)} document paths are written twice by the generation set "
            f"(e.g. {name} from {titles}). Whichever is written last wins while "
            f"selection ranks by the other."
        )

    ranked = _collisions(ranked_jobs(config))
    outside = {n: js for n, js in ranked.items() if n not in generated}
    if outside:
        name, jobs = next(iter(outside.items()))
        titles = " / ".join(repr(j.get("title", "")) for j in jobs[:2])
        out.append(
            f"{len(outside)} document paths are shared by ranked jobs below the "
            f"generation cutoff (e.g. {name} from {titles}). Nothing is overwritten "
            f"today; it becomes data loss if either job rises into the selection."
        )
    return out


def check_composite_still_discriminates(config: dict) -> list[str]:
    """The ranking must actually spread jobs apart.

    A composite can look healthy on the mean while carrying no ordering
    information: before the fixes every job sat at 0.71 +/- 0.09, so "top 30%"
    was close to arbitrary. Low spread is not visible in any single job's report.
    """
    from selection import ranked_jobs

    ranked = ranked_jobs(config)
    if len(ranked) < MIN_REVIEWS_FOR_STATS:
        return []
    sd = statistics.stdev([j["match"]["composite_score"] for j in ranked])
    if sd < MIN_COMPOSITE_SD:
        return [
            f"composite_score sd={sd:.3f} is below {MIN_COMPOSITE_SD} — the ranking "
            f"barely separates jobs, so top-N% selection is near-arbitrary."
        ]
    return []


def check_review_scores_track_rubric(config: dict) -> list[str]:
    """A stored submission_score must equal what the scorer produces now.

    The number in the frontmatter is what every downstream view sorts on. If the
    scoring rule changed and the files were not backfilled, the ranking reflects
    a rule that no longer exists — and nothing in the file says so.
    """
    from reviewer import _extract_score

    if not REVIEWS.exists():
        return []
    drift = []
    for path in sorted(REVIEWS.glob("*_review.md")):
        fm = _fm(path)
        stored = fm.get("submission_score")
        if stored in (None, "null") or fm.get("unscoreable") == "true":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        fresh, _fb, _nits = _extract_score(text)
        if fresh is not None and str(fresh) != stored:
            drift.append(f"{path.stem}: stored {stored} vs computed {fresh}")
    if drift:
        return [
            f"{len(drift)} reviews hold a stale submission_score "
            f"({'; '.join(drift[:3])}). Run backfill_scores.py."
        ]
    return []


# Per-site wall-clock cap enforced by the Hermes cron wrapper (`timeout`, so a
# breach shows up as exit 124). Not readable from this repo — the wrapper lives in
# ~/.hermes/profiles/archivist/cron/jobs.json — so it is mirrored here and must be
# updated alongside it.
SITE_TIMEOUT_SECONDS = 1500
# MEASURED seconds per search, per site. Two earlier attempts at this were wrong:
#   1. Modelling it as "2s setup + 2s per page" gave 14s at depth 6 — off by 5x,
#      because page navigation is not the cost. The per-job description fetch is:
#      serial, 1s apart, paid for every NEW posting. Dismissing it as cached was
#      backwards, since a productive site is mostly new postings each night.
#   2. Applying reed's measured 68s to every site flagged all five, including
#      guardian, which demonstrably completes.
# Sites differ by an order of magnitude, so each carries its own number:
#   reed      68.0  observed directly (37 searches in 42 min, depth 6)
#   guardian  22.6  back-computed from a completing run (1421s / 63 searches)
#   adzuna     ---  API path now; the old Playwright timeout says only ">23.8"
#   indeed     ---  its 27s runs were instant Cloudflare failures, not work
# A site with no entry is NOT judged: warning off a guess would train the reader
# to ignore this check. Add a number only from `time run.py --site <site>`.
# Stored as (seconds_per_search, depth_it_was_measured_at) so lowering depth is
# reflected instead of ignored. Cost splits into a fixed page walk — ~2s of settle
# per page — and the description fetch, which scales with how many postings the
# depth returns; both fall as depth falls, so the figure is scaled linearly by
# depth. Linear is an approximation, deliberately kept simple: it is calibrated at
# the depth actually measured, and re-measuring is cheap (`time run.py --site X`).
_SECONDS_PER_SEARCH = {
    "reed": (68.0, 6),
    "guardian": (22.6, 3),
}


def check_scrape_fits_its_timeout(config: dict) -> list[str]:
    """Page depth must leave time for the night's new descriptions.

    A site that exceeds its cron timeout is killed mid-run (exit 124) and writes
    truncated data — which is where the unscoreable backlog came from, not from any
    scraper error. Nothing in the pipeline notices: the run "completed", the
    database grew, and the half-scraped postings went on to score.

    The trap is that the cost is invisible until the night it is not: descriptions
    are cached, so a depth that fits comfortably for months breaks the first time
    enough NEW postings appear. reed ran at depth 10 (~1386s of the 1500s cap) until
    the multi-country expansion, then timed out.
    """
    from selection import max_pages_for

    searches = max(1, len(config.get("keywords") or [1])) * max(
        1, len(config.get("locations") or [1]))
    out = []
    for site in (config.get("sites") or []):
        if site == "remote_apis":  # API path, no page walking
            continue
        measured = _SECONDS_PER_SEARCH.get(site)
        if measured is None:
            continue  # unmeasured — see _SECONDS_PER_SEARCH
        rate, measured_depth = measured
        depth = max_pages_for(site, config)
        per_search = rate * depth / measured_depth
        needed = searches * per_search
        if needed > SITE_TIMEOUT_SECONDS:
            out.append(
                f"{site}: ~{needed:.0f}s needed against a {SITE_TIMEOUT_SECONDS}s cron "
                f"timeout ({searches} searches x {per_search:.0f}s measured, depth "
                f"{depth}). Expect exit 124 and truncated postings. Cut `keywords` x "
                f"`locations` to at most {int(SITE_TIMEOUT_SECONDS / per_search)} "
                f"searches, or make the description fetch concurrent — depth is not the "
                f"main cost, the serial 1s-per-job description fetch is."
            )
    return out


# A configured site that has produced nothing for this long has stopped working,
# whatever its exit code said. Wide enough to tolerate a quiet board or a couple of
# failed nights; far short of the 13 days adzuna went unnoticed.
MAX_SITE_SILENCE_DAYS = 5


def check_every_site_still_yields(config: dict) -> list[str]:
    """Each configured site must have produced a job recently.

    A scraper whose selectors go stale does not raise — it extracts nothing and
    reports success. Adzuna's detail-page selectors were all matching zero elements
    by 2026-07-25, so it had contributed no job since 07-12: thirteen nights of
    green runs, a growing database (other sites), and no signal anywhere. The
    per-site exit codes could not show it either, because the run genuinely
    succeeded.
    """
    from datetime import date, datetime, timedelta

    if not ANALYZED.exists():
        return []
    sites = [s for s in (config.get("sites") or []) if s]
    if not sites:
        return []
    latest: dict[str, str] = {}
    for job in json.loads(ANALYZED.read_text(encoding="utf-8")):
        src = job.get("source")
        stamp = (job.get("scraped_at") or "")[:10]
        if src and stamp > latest.get(src, ""):
            latest[src] = stamp
    # Sources a site records its jobs under, where they differ from the site name.
    # remote_apis fans out to three boards and tags each with its own name, so
    # looking for source == "remote_apis" finds nothing however well it is working.
    aliases = {"remote_apis": ("remotive", "remoteok", "arbeitnow")}
    for site, names in aliases.items():
        newest = max((latest[n] for n in names if n in latest), default=None)
        if newest:
            latest[site] = max(latest.get(site, ""), newest)

    cutoff = (date.today() - timedelta(days=MAX_SITE_SILENCE_DAYS)).isoformat()
    out = []
    for site in sites:
        seen = latest.get(site)
        if seen is None:
            # Never-yielded is ambiguous: a broken scraper and a site added to
            # `sites` that has not had a nightly run yet look identical from here.
            # Say so rather than assert a fault — remote_apis was flagged this way
            # on the day it was added, before its first run.
            out.append(
                f"{site}: in `sites` but no job recorded under it yet — either the "
                f"scraper is failing or it has not had a nightly run since being "
                f"added. Run `run.py --site {site}` to tell which."
            )
        elif seen < cutoff:
            try:
                days = (date.today() - datetime.fromisoformat(seen).date()).days
                age = f"{days} days"
            except ValueError:
                age = f"since {seen}"
            out.append(
                f"{site}: no job scraped for {age} (last {seen}) while still in "
                f"`sites`. A stale selector yields nothing without erroring — check "
                f"the extractor against a live page before trusting the exit code."
            )
    return out


def check_configured_sites_are_scheduled(config: dict) -> list[str]:
    """Every site in `sites` must have a `run_site` line in the nightly script.

    check_every_site_still_yields catches the symptom — no jobs for N days — but
    reports it as a possible stale selector, which sends you to read a scraper that
    is fine. linkedin was in `sites` and absent from the cron script for six days:
    it had never once been invoked, and nothing in the repo could tell, because the
    script is in a separate dotfiles repo.

    The reverse direction matters as much. A site scraped nightly but missing from
    `sites` still writes to the database while being excluded from every per-site
    budget and check here.
    """
    import re

    if not NIGHTLY_SCRIPT.exists():
        return []
    configured = [s for s in (config.get("sites") or []) if s]
    if not configured:
        return []
    script = NIGHTLY_SCRIPT.read_text(encoding="utf-8")
    # Only invocations count. The word also appears in comments and in the
    # run_site() definition itself, neither of which runs anything.
    scheduled = set(re.findall(r"^\s*run_site\s+(\S+)", script, re.MULTILINE))

    out = []
    unscheduled = [s for s in configured if s not in scheduled]
    if unscheduled:
        out.append(
            f"in `sites` but never run by {NIGHTLY_SCRIPT.name}: "
            f"{', '.join(unscheduled)}. These scrape nothing at night, so the "
            f"'no job for N days' warning will blame a stale selector on a scraper "
            f"that was simply never called. Add a `run_site` line or drop from `sites`."
        )
    unconfigured = sorted(scheduled - set(configured))
    if unconfigured:
        out.append(
            f"run nightly but absent from `sites`: {', '.join(unconfigured)}. Their "
            f"jobs still land in the database while being skipped by every per-site "
            f"timing budget and check here."
        )
    return out


def check_truncated_descriptions_get_enriched(config: dict) -> list[str]:
    """Report how much of the enrichment backlog would outrank real postings.

    The Adzuna API returns a 500-char summary and has no job-details endpoint at
    all (every candidate path 404s), so its postings arrive unreviewable by design.
    Measured over 980 filter-passing jobs, a summary does not merely carry less
    information — it scores HIGHER than a full description: composite 0.440 vs
    0.340, context 0.454 vs 0.398. The reason is structural. A 500-char excerpt is
    the opening pitch; the requirements and constraints are what got cut, so the
    model reads only what the posting is selling. That is the same failure as the
    invented review rubric, one stage earlier.

    So these are excluded from ranking too, not just from review, and this check
    measures the size of what is being held back rather than a fault. It is worth
    surfacing because the exclusion is invisible: the jobs are present and scored,
    and only a comparison against full-text postings shows the inflation.
    """
    from filter import passes_filter
    from selection import _dedupe, stage_percent, top_percent_count

    if not ANALYZED.exists():
        return []
    pool = [
        j for j in _dedupe(json.loads(ANALYZED.read_text(encoding="utf-8")))
        if j.get("match") and passes_filter(j, config)[0]
        and j.get("match", {}).get("composite_score", 0) > 0
    ]
    if not pool:
        return []
    pool.sort(key=lambda j: j["match"]["composite_score"], reverse=True)
    pct = max(stage_percent(config, s) for s in ("generation", "review"))
    band = pool[: top_percent_count(len(pool), pct)]
    stuck = [j for j in band if j.get("description_truncated")]
    if not stuck:
        return []
    return [
        f"{len(stuck)} jobs would sit in the top {pct:g}% on a 500-char API summary "
        f"alone (band of {len(band)} before exclusions). Summaries score ~0.10 higher "
        f"than full text because the cut part is the requirements, so these are held "
        f"out of ranking as well as review. Recover them a batch at a time with "
        f"`refetch_unscoreable.py --top-only` — adzuna refuses long runs."
    ]


CHECKS = (
    check_submission_threshold_is_reachable,
    check_scrape_fits_its_timeout,
    check_every_site_still_yields,
    check_configured_sites_are_scheduled,
    check_truncated_descriptions_get_enriched,
    check_floor_below_selection_cutoff,
    check_stored_weights_match_config,
    check_irrelevant_titles_excluded,
    check_unscoreable_excluded,
    check_one_entry_per_document_path,
    check_composite_still_discriminates,
    check_review_scores_track_rubric,
)


def run_all(config: dict | None = None) -> list[str]:
    """Every violation across all checks. Empty list = healthy.

    A check that itself explodes is reported as a violation rather than allowed
    to abort the run: a broken invariant check is also a thing worth knowing, and
    it must not take the nightly pipeline down with it.
    """
    config = config if config is not None else _load_config()
    found: list[str] = []
    for check in CHECKS:
        try:
            found.extend(check(config))
        except Exception as e:  # noqa: BLE001 - reported, never fatal
            found.append(f"{check.__name__} could not run: {type(e).__name__}: {e}")
    return found


def report(config: dict | None = None) -> list[str]:
    """run_all, printed in the shape the nightly cron forwards to Telegram."""
    found = run_all(config)
    if found:
        print(f"⚠️ 整合性チェック: {len(found)}件の違反")
        for v in found:
            print(f"  • {v}")
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warn", action="store_true",
                    help="report violations but exit 0")
    args = ap.parse_args()
    found = report()
    if not found:
        print(f"✓ 整合性チェック: {len(CHECKS)}項目すべて通過")
    return 0 if (args.warn or not found) else 1


if __name__ == "__main__":
    sys.exit(main())
