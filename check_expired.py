"""Open each match report's posting and tick `expired` on the ones that closed.

The tick already exists and already does the right thing: gen_version treats
`expired: true` as a job-scoped lock, so a closed posting stops being reviewed,
stops being regenerated, and is refused a first CV. What was missing is the part
that decides it — until now that was done by hand, one report at a time, by
opening the URL in a browser.

WHAT IT WILL AND WILL NOT CONCLUDE

Only positive evidence ticks the box. A rate-limit page, a Cloudflare
interstitial, a timeout and a redirect all mean "cannot tell", and cannot-tell
leaves the report exactly as it was. That asymmetry is the whole design: a live
posting written off as expired is silently dropped from the pipeline — no
review, no CV, no letter — and nothing downstream would ever question it.

WHY EACH SITE IS CHECKED THE WAY IT IS (measured 2026-08-31, not assumed)

  linkedin   the logged-out jobPosting endpoint answers 200 for a live posting
             and 200 + "No longer accepting applications" for a closed one; a
             withdrawn id 404s. ~2s a request, no browser.
  reed       a closed posting answers 404 with <h1>This job has expired</h1>.
             The status is the rule; the heading is recorded as evidence.
  adzuna     the stored /jobs/land/ad/<id>?se=... links answer 400 for live and
             dead ads alike — the `se` token is short-lived, so the URL in the
             database carries no information. The canonical /jobs/details/<id>
             on the same host does: 200 live, 410 gone.
  arbeitnow  410 for a removed posting, 200 for a live one.
  remotive   same.

  guardian   a closed posting carries <p id="message">This job has expired</p>;
             a live one has no #message element at all. Match the ELEMENT, not
             the phrase: the first two Guardian postings drawn from this database
             both carried the banner, which made it look unconditional — until a
             posting taken off the site's own live listing turned out to have no
             #message element at all. Two expired samples are not a control group.

  indeed     NOT CHECKED, and not for want of trying. uk.indeed.com answers 401
             "Authenticating..." to a plain request, 403 "Security Check" to the
             /m/ mobile path, and the same Cloudflare "Additional Verification
             Required" page to a headless browser with stealth applied and
             cookies/indeed_cookies.json loaded — asked for a known-dead jk and a
             live one, which came back indistinguishable. scraper_indeed reached
             the same conclusion from the other side: its
             _fill_descriptions_from_pane note records /viewjob as blocked
             outright and unfixable, which is why it reads descriptions off the
             search listing instead. There is no per-posting page to ask, so the
             612 indeed reports stay a manual job — --list-manual puts them in a
             worth-checking order instead of leaving them a pile.

Sources with no rule are reported as `unsupported` and never touched.

    python3 check_expired.py --dry-run
    python3 check_expired.py --limit 200
    python3 check_expired.py --source linkedin
    python3 check_expired.py --source adzuna --limit 40   # blocks easily, go slow
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scraper_linkedin_guest import USER_AGENT, job_id_from_url  # noqa: E402

MATCHES = ROOT / "10_output" / "00_matches"
ANALYZED = ROOT / "10_output" / "_analyzed.json"
# Every verdict this has ever reached, so a second run does not re-fetch what it
# already knows. Kept out of the reports themselves: a report is rewritten
# wholesale on every rescrape, and only the flags matcher.read_flag knows about
# survive that — a provenance key added here would be dropped on the next run.
STATE = ROOT / "10_output" / "_expiry_checks.json"

GONE, LIVE, BLOCKED, UNSUPPORTED = "gone", "live", "blocked", "unsupported"

# The sources check_url has a measured rule for. Everything else is skipped
# before it costs a slot in --limit: a run capped at 200 that spent 14 of them
# printing "no rule for indeed" is 14 postings that went unchecked.
SUPPORTED_SOURCES = ("linkedin", "reed", "adzuna", "arbeitnow", "remotive",
                     "guardian")

LINKEDIN_JOB = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
LINKEDIN_CLOSED = "no longer accepting applications"
# The Guardian renders its closed-posting notice into this element, and omits
# the element entirely while a posting is open. Anchored to the element rather
# than to the words for the reason in the docstring.
GUARDIAN_BANNER = re.compile(r'<p[^>]*id="message"[^>]*>(.*?)</p>',
                             re.DOTALL | re.IGNORECASE)

# Seconds between requests to one site. LinkedIn answers a steady trickle
# indefinitely and 429s a burst; adzuna is the opposite — it tolerates a short
# burst and then starts refusing everything, and refetch_unscoreable's notes put
# the turn at roughly a dozen detail pages, so its pace is deliberately slower
# than anything else here.
# adzuna's 8.0 is measured, not guessed: at 4.0 the first full sweep got through
# 519 ads and then answered 429 to everything, which cost the remaining 1355. The
# other four sources finished that same run without a single block.
DELAYS = {"linkedin": 2.0, "reed": 1.5, "adzuna": 8.0,
          "arbeitnow": 1.5, "remotive": 1.5, "theguardian": 1.5}
# Consecutive blocks after which a site is left alone for a later run. Pushing
# past this does not recover the postings, it just deepens the ban for the next
# attempt.
MAX_CONSECUTIVE_BLOCKS = 3
# How long a "live" verdict is trusted before it is worth asking again.
DEFAULT_FRESH_DAYS = 7

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-GB,en;q=0.9",
}


# --------------------------------------------------------------------------
# Reading the reports
# --------------------------------------------------------------------------

def _frontmatter(text: str) -> str:
    m = re.match(r"\A---\n(.*?)\n---", text, re.DOTALL)
    return m.group(1) if m else ""


def _field(fm: str, key: str) -> str:
    m = re.search(rf'^{key}:\s*"?([^"\n]*)', fm, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _flag(fm: str, key: str) -> bool:
    """The same spellings matcher.read_flag accepts, so a tick made in Obsidian
    reads the same here as it does on every other path."""
    return _field(fm, key).lower() in ("true", "yes", "on")


def read_reports(match_dir: Path | None = None) -> list[dict]:
    """Every match report as {path, url, source, score, expired, applied}.

    The directory is resolved at call time, not bound as a default: a default
    argument captures MATCHES when the module is imported, so a test that points
    the module at a fixture directory would still be answered with the real one —
    and a "dry run" over 5000 real reports is thousands of live requests.
    """
    match_dir = match_dir or MATCHES
    out = []
    for path in sorted(match_dir.glob("*.md")):
        try:
            head = path.read_text(encoding="utf-8")[:4000]
        except OSError:
            continue
        fm = _frontmatter(head)
        if not fm:
            continue
        try:
            score = float(_field(fm, "match_score") or 0)
        except ValueError:
            score = 0.0
        out.append({
            "path": path,
            "url": _field(fm, "url"),
            "source": _field(fm, "source"),
            "score": score,
            "expired": _flag(fm, "expired"),
            "applied": _flag(fm, "applied"),
            "saved_at": _field(fm, "saved_at"),
        })
    return out


def tick_expired(path: Path, dry_run: bool = False) -> bool:
    """Set `expired: true` in the report's frontmatter. False if there is no
    `expired:` key to set — an older report, which a regeneration will give one.

    Only that one line changes. The report carries hand-set state other steps
    depend on (applied, the review links, the PDF links), and rewriting it from
    the database here would be a second, unreviewed write path for all of it.
    """
    text = path.read_text(encoding="utf-8")
    fm = _frontmatter(text)
    if not fm or not re.search(r"^expired:", fm, re.MULTILINE):
        return False
    new_fm = re.sub(r"^expired:.*$", "expired: true", fm, count=1, flags=re.MULTILINE)
    if not dry_run:
        path.write_text(text.replace(fm, new_fm, 1), encoding="utf-8")
    return True


# --------------------------------------------------------------------------
# Asking the sites
# --------------------------------------------------------------------------

def clickable(url: str, source: str) -> str:
    """The URL a human should be handed for this posting.

    Indeed's stored /rc/clk links are 300 characters of tracking around one `jk`,
    and this list exists to be clicked. Cloudflare lets a real browser through
    where it refuses this script, so the plain /viewjob form is the useful one.
    """
    if (source or "").lower() == "indeed":
        jk = re.search(r"[?&]jk=([a-f0-9]+)", url or "")
        if jk:
            host = urlsplit(url).netloc or "uk.indeed.com"
            return f"https://{host}/viewjob?jk={jk.group(1)}"
    return url


def _title_and_h1(html: str) -> str:
    def one(pattern):
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else ""
    return " | ".join(x for x in (one(r"<title[^>]*>(.*?)</title>"),
                                  one(r"<h1[^>]*>(.*?)</h1>")) if x)[:160]


def check_url(url: str, source: str, fetch) -> tuple[str, str]:
    """(verdict, evidence) for one posting. `fetch(url)` -> (status, text).

    Every branch that is not a documented, site-specific signal falls through to
    BLOCKED, which writes nothing. See the module docstring for what each site
    was measured to answer.
    """
    source = (source or "").lower()

    if source == "linkedin":
        job_id = job_id_from_url(url)
        if not job_id:
            return UNSUPPORTED, "no job id in the URL"
        status, html = fetch(LINKEDIN_JOB.format(job_id=job_id))
        if status == 404:
            return GONE, "guest endpoint 404 — posting withdrawn"
        if status == 200:
            if LINKEDIN_CLOSED in (html or "").lower():
                return GONE, "no longer accepting applications"
            return LIVE, _title_and_h1(html)
        return BLOCKED, f"HTTP {status}"

    if source == "reed":
        parts = urlsplit(url)
        status, html = fetch(f"{parts.scheme}://{parts.netloc}{parts.path}")
        if status == 404:
            return GONE, _title_and_h1(html) or "HTTP 404"
        if status == 200:
            return LIVE, _title_and_h1(html)
        return BLOCKED, f"HTTP {status}"

    if source == "adzuna":
        m = re.search(r"/(?:jobs/)?(?:details|land/ad)/(\d+)", url)
        if not m:
            return UNSUPPORTED, "no ad id in the URL"
        host = urlsplit(url).netloc or "www.adzuna.co.uk"
        status, html = fetch(f"https://{host}/jobs/details/{m.group(1)}")
        if status in (404, 410):
            return GONE, f"HTTP {status} on the canonical ad page"
        if status == 200:
            return LIVE, _title_and_h1(html)
        # 403 and the "suspicious behaviour" body are what adzuna serves once it
        # decides a client is scraping; 400 is what the token-bound land/ad link
        # answers whether or not the ad is live. Neither is evidence.
        return BLOCKED, f"HTTP {status}"

    if source == "guardian":
        status, html = fetch(url)
        if status == 200:
            banner = GUARDIAN_BANNER.search(html or "")
            text = re.sub(r"\s+", " ",
                          re.sub(r"<[^>]+>", " ", banner.group(1))).strip() if banner else ""
            if "expired" in text.lower():
                return GONE, text
            if banner:
                # A banner saying something this code has not been shown is not
                # evidence of anything. Reading it as expiry would hand the site
                # the ability to close every Guardian posting at once.
                return BLOCKED, f"unrecognised banner: {text[:80]}"
            return LIVE, _title_and_h1(html)
        if status == 404:
            return GONE, "HTTP 404"
        return BLOCKED, f"HTTP {status}"

    if source in ("arbeitnow", "remotive"):
        status, html = fetch(url)
        if status in (404, 410):
            return GONE, f"HTTP {status}"
        if status == 200:
            return LIVE, _title_and_h1(html)
        return BLOCKED, f"HTTP {status}"

    return UNSUPPORTED, f"no rule for source {source or '(none)'}"


def make_fetch(session: requests.Session, delays: dict[str, float]):
    """A fetch(url) -> (status, text) that paces itself per host."""
    last: dict[str, float] = {}

    def fetch(url: str) -> tuple[int, str]:
        host = urlsplit(url).netloc
        wait = max(delays.values() or [1.5])
        for key, seconds in delays.items():
            if key in host:
                wait = seconds
                break
        since = time.monotonic() - last.get(host, 0.0)
        if since < wait:
            time.sleep(wait - since + random.uniform(0, 0.5))
        try:
            resp = session.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        except requests.RequestException as e:
            last[host] = time.monotonic()
            return 0, f"{type(e).__name__}: {e}"
        last[host] = time.monotonic()
        return resp.status_code, resp.text

    return fetch


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------

def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _age_days(stamp: str) -> float:
    try:
        then = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return 1e9
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 86400


def mark_removed(urls: set[str], dry_run: bool = False) -> int:
    """Set `listing_removed` on the database rows behind the closed postings.

    The same field refetch_unscoreable writes, and for the same reason: the job
    stays visible as a lead lost to a dead listing instead of vanishing, and no
    later pass spends a fetch on it again.
    """
    if not urls or not ANALYZED.exists():
        return 0
    db = json.loads(ANALYZED.read_text(encoding="utf-8"))
    hit = 0
    for job in db:
        if job.get("url") in urls and not job.get("listing_removed"):
            job["listing_removed"] = True
            hit += 1
    if hit and not dry_run:
        ANALYZED.write_text(json.dumps(db, ensure_ascii=False, indent=2, default=str),
                            encoding="utf-8")
    return hit


def removed_urls() -> set[str]:
    """Postings the database already knows are gone, from an earlier refetch."""
    if not ANALYZED.exists():
        return set()
    db = json.loads(ANALYZED.read_text(encoding="utf-8"))
    return {j.get("url") for j in db if j.get("listing_removed") and j.get("url")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=200,
                    help="postings to fetch this run (0 = no cap)")
    ap.add_argument("--source", action="append", default=None,
                    help="only this source; repeatable")
    ap.add_argument("--match", default=None,
                    help="only reports whose filename contains this (case-insensitive) "
                         "— for checking one posting you are looking at right now")
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--fresh-days", type=float, default=DEFAULT_FRESH_DAYS,
                    help="skip postings confirmed live more recently than this")
    ap.add_argument("--recheck", action="store_true",
                    help="ignore every cached verdict")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and decide, but write nothing")
    ap.add_argument("--list-manual", action="store_true",
                    help="list the open reports no rule can reach, worth-checking "
                         "order, and fetch nothing")
    args = ap.parse_args()

    reports = read_reports()

    if args.list_manual:
        # indeed cannot be asked, so its 612 reports would otherwise be a pile to
        # work through in file order. Ranked by score, they are a queue: the ones
        # worth an application are the ones worth knowing are still open.
        manual = [r for r in reports
                  if not r["expired"] and not r["applied"] and r["url"]
                  and r["source"].lower() not in SUPPORTED_SOURCES
                  and (not args.match or args.match.lower() in r["path"].name.lower())]
        manual.sort(key=lambda r: (-r["score"], r["saved_at"]))
        if args.limit:
            manual = manual[:args.limit]
        for r in manual:
            print(f"{r['score']:.2f}  {r['saved_at'] or '?':10}  {r['source'] or '?':9}  "
                  f"{r['path'].name[:-3]}\n        {clickable(r['url'], r['source'])}")
        print(f"\n{len(manual)} report(s) — no automated rule reaches these; "
              f"tick `expired` by hand in the report and this run will skip it.")
        return 0

    state = {} if args.recheck else load_state()
    already_gone = removed_urls()

    # The free pass first: a posting the database already recorded as removed
    # needs no request at all, only the tick its report never got.
    reconciled = 0
    for r in reports:
        if r["expired"] or r["applied"] or r["url"] not in already_gone:
            continue
        if tick_expired(r["path"], args.dry_run):
            reconciled += 1
            r["expired"] = True
    if reconciled:
        verb = "would tick" if args.dry_run else "ticked"
        print(f"↩ {verb} {reconciled} report(s) the DB already had as listing_removed")

    wanted = {s.lower() for s in args.source} if args.source else None
    todo = []
    no_rule = 0
    for r in reports:
        if r["expired"] or r["applied"] or not r["url"]:
            continue
        if wanted and r["source"].lower() not in wanted:
            continue
        if args.match and args.match.lower() not in r["path"].name.lower():
            continue
        if r["source"].lower() not in SUPPORTED_SOURCES:
            no_rule += 1
            continue
        if r["score"] < args.min_score:
            continue
        seen = state.get(r["url"])
        if seen and not args.recheck:
            # A verdict of gone would have ticked the report; unsupported will
            # not change until this file does. Only "live" is worth re-asking,
            # and only once it has had time to stop being true.
            if seen.get("verdict") in (GONE, UNSUPPORTED):
                continue
            if _age_days(seen.get("checked_at", "")) < args.fresh_days:
                continue
        todo.append(r)

    todo.sort(key=lambda r: (-r["score"], r["path"].name))
    if args.limit:
        todo = todo[:args.limit]
    if not todo:
        print(f"nothing to check ({no_rule} skipped — no rule for their source)"
              if no_rule else "nothing to check")
        return 0

    print(f"checking {len(todo)} posting(s)"
          + (" (dry run)" if args.dry_run else "")
          + (f"; {no_rule} skipped — no rule for their source" if no_rule else ""))

    session = requests.Session()
    fetch = make_fetch(session, DELAYS)
    counts = {GONE: 0, LIVE: 0, BLOCKED: 0, UNSUPPORTED: 0}
    consecutive: dict[str, int] = {}
    stopped: set[str] = set()
    gone_urls: set[str] = set()

    for i, r in enumerate(todo, 1):
        source = r["source"].lower()
        if source in stopped:
            continue
        verdict, evidence = check_url(r["url"], source, fetch)
        counts[verdict] += 1
        state[r["url"]] = {"verdict": verdict, "evidence": evidence,
                           "source": source, "report": r["path"].name,
                           "checked_at": datetime.now(timezone.utc).isoformat()}

        if verdict == BLOCKED:
            consecutive[source] = consecutive.get(source, 0) + 1
            if consecutive[source] >= MAX_CONSECUTIVE_BLOCKS:
                stopped.add(source)
                print(f"  ⏹ {source}: {MAX_CONSECUTIVE_BLOCKS} blocks in a row — "
                      f"leaving the rest for a later run")
        else:
            consecutive[source] = 0

        if verdict == GONE:
            gone_urls.add(r["url"])
            ticked = tick_expired(r["path"], args.dry_run)
            mark = "✓" if ticked else "· (report has no expired: key)"
            print(f"  [{i}/{len(todo)}] {mark} {r['path'].name}  — {evidence}")
        elif verdict == BLOCKED:
            print(f"  [{i}/{len(todo)}] ? {r['path'].name}  — {evidence}")

        if i % 25 == 0 and not args.dry_run:
            STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    if not args.dry_run:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    rows = mark_removed(gone_urls, args.dry_run)

    print(f"\nexpired {counts[GONE]}  |  live {counts[LIVE]}  |  "
          f"cannot tell {counts[BLOCKED]}  |  no rule {counts[UNSUPPORTED] + no_rule}")
    if rows:
        verb = "would mark" if args.dry_run else "marked"
        print(f"{verb} listing_removed on {rows} database row(s)")
    if args.dry_run:
        print("dry run — nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
