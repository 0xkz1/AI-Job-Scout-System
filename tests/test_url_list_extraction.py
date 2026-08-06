"""The URL-list scraper must not waste extraction calls, or bypass the
project's provider chain.

Three faults, all measured on the 2026-08-03/06 runs:

  * It POSTed straight to localhost:11434 instead of going through call_llm, so
    it alone ignored FALLBACK_PROVIDERS and key_quarantine — unable to use a
    healthy cloud key, and unable to stand down from one returning 401. It also
    pinned every extraction to a local 26B reasoning model: a median 107s per
    URL against its own 120s timeout, so the slowest pages timed out and were
    discarded. Through call_llm the same extraction takes ~5s.

  * Indeed's Cloudflare interstitial renders 250 characters, over the len < 100
    guard, so every blocked /viewjob URL was handed to the model as if it were
    a posting. 15 URLs, ~107s each, zero jobs.

  * LinkedIn's `lipi` tracking parameter was not stripped, so the same posting
    copied from Saved Jobs and from search normalised to two different URLs and
    was fetched and stored twice.
"""
import ast
import json
import pathlib

import scraper_url_list as s

ROOT = pathlib.Path(__file__).resolve().parent.parent


# --- provider chain -------------------------------------------------------

def test_extraction_goes_through_call_llm():
    tree = ast.parse((ROOT / "scraper_url_list.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "extract_job_from_text")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "call_llm" in called, (
        "extract_job_from_text no longer routes through llm_client.call_llm — "
        "it has lost FALLBACK_PROVIDERS and key_quarantine again"
    )


def test_no_hardcoded_ollama_endpoint():
    """Checked against string literals, not the file text — the comment above
    extract_job_from_text names the port while explaining why it is gone."""
    tree = ast.parse((ROOT / "scraper_url_list.py").read_text(encoding="utf-8"))
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    offenders = [v for v in literals if "11434" in v or "/api/generate" in v]
    assert not offenders, (
        f"a hardcoded Ollama endpoint is back ({offenders}); provider selection "
        f"belongs to llm_client so quarantined keys are skipped and healthy "
        f"ones are used"
    )


def test_extraction_asks_for_enough_output_tokens():
    """call_llm defaults to max_tokens=512, which truncates a job description
    mid-sentence — and the description is the entire point of this call."""
    tree = ast.parse((ROOT / "scraper_url_list.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "extract_job_from_text")
    call = next(n for n in ast.walk(fn)
                if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "call_llm")
    kw = {k.arg: k.value for k in call.keywords}
    assert "max_tokens" in kw, "max_tokens left at the 512 default"
    assert kw["max_tokens"].value >= 2048


# --- anti-bot pages -------------------------------------------------------

def test_the_real_indeed_cloudflare_page_is_detected():
    # Verbatim from uk.indeed.com/viewjob on 2026-08-06 — 250 chars, which is
    # why the len < 100 guard did not catch it.
    page = ("Find jobs Company Reviews Find salaries Upload your resume Sign in "
            "Employers / Post Job Additional Verification Required  Your Ray ID "
            "for this request is a26a3f6799ef8067  Return home   →  "
            "Troubleshooting Cloudflare Errors  Need more help? Contact us")
    assert len(page) > 100, "this page passes the too-short guard, hence the marker check"
    assert s.looks_blocked(page) == "additional verification required"


def test_the_jobleads_variant_is_detected():
    """A second wording, found only because the first fix let these through and
    the model answered with a well-formed object whose every field was empty."""
    page = ("www.jobleads.com\nPerforming security verification\n\nThis website "
            "uses a security service to protect against malicious bots. This page "
            "is displayed while the website verifies you are not a bot.\n\n"
            "Ray ID: a26a6ceb1a997376\nPerformance and Security by Cloudflare")
    assert s.looks_blocked(page) == "performing security verification"


def test_an_unknown_interstitial_is_caught_by_the_ray_id_heuristic():
    # Wording nobody has seen yet, but the two structural tells hold: very
    # short, and citing a Cloudflare Ray ID.
    page = "Some Site\nOne moment please\n\nRay ID: deadbeef1234\n"
    assert s.looks_blocked(page) == "cloudflare ray id on a near-empty page"


def test_a_real_job_page_is_not_flagged_as_blocked():
    page = ("Senior Product Designer at Acme Corp. Edinburgh, Scotland. "
            "We are looking for a product designer to own our design system, "
            "run research sessions and ship features in Figma. Requirements: "
            "3+ years product design, prototyping, design systems. ") * 8
    assert s.looks_blocked(page) is None


def test_a_long_page_mentioning_a_ray_id_is_not_blocked():
    """The heuristic needs BOTH tells. A real posting that happens to contain
    the words must survive — length is what separates them."""
    page = ("Senior Platform Engineer at Acme. You will debug edge traffic, "
            "read a Cloudflare Ray ID from logs, and tune WAF rules. ") * 20
    assert len(page) > s.BLOCK_MAX_CHARS
    assert s.looks_blocked(page) is None


# --- URL normalisation ----------------------------------------------------

def test_lipi_tracking_param_is_stripped():
    saved = ("https://www.linkedin.com/jobs/view/4429990426/"
             "?lipi=urn%3Ali%3Apage%3Ad_flagship3_opportunity_tracker%3Be2IRtVhFSQ")
    plain = "https://www.linkedin.com/jobs/view/4429990426/"
    assert s.normalize_url(saved) == s.normalize_url(plain)


def test_indeed_hl_param_is_stripped():
    """Same posting, pasted from two places. Observed 2026-08-06:
    jk=041cc148b17a1ece was fetched twice in one run because only the second
    form's parameters were being stripped."""
    a = "https://uk.indeed.com/viewjob?jk=041cc148b17a1ece&hl=en"
    b = "https://uk.indeed.com/viewjob?jk=041cc148b17a1ece&from=serp&vjs=3"
    assert s.normalize_url(a) == s.normalize_url(b)


def test_the_job_identifying_param_is_kept():
    # Stripping too much would collapse distinct Indeed postings into one.
    a = "https://uk.indeed.com/viewjob?jk=478229beba043340&hl=en&from=serp"
    b = "https://uk.indeed.com/viewjob?jk=f48183e2d5ce288a&hl=en&from=serp"
    assert s.normalize_url(a) != s.normalize_url(b)
    assert "jk=478229beba043340" in s.normalize_url(a)


# --- routing --------------------------------------------------------------

def test_linkedin_urls_route_away_from_the_llm():
    from scraper_linkedin_guest import job_id_from_url
    assert job_id_from_url("https://www.linkedin.com/jobs/view/4427214460/") == "4427214460"
    assert job_id_from_url("https://uk.indeed.com/viewjob?jk=abc123") == ""


# --- adopting what the nightly already fetched ----------------------------

def test_indeed_jk_is_read_regardless_of_tracking_params():
    assert s._indeed_jk("https://uk.indeed.com/viewjob?jk=041cc148b17a1ece&hl=en") == "041cc148b17a1ece"
    assert s._indeed_jk("https://uk.indeed.com/viewjob?from=serp&jk=041cc148b17a1ece&vjs=3") == "041cc148b17a1ece"
    assert s._indeed_jk("https://www.linkedin.com/jobs/view/4427214460/") == ""


def test_a_posting_already_in_the_database_is_adopted(tmp_path, monkeypatch):
    """/viewjob is a hard block — verified 2026-08-06 under xvfb-run with a
    headed browser, cached cookies and stealth, it still answered "Additional
    Verification Required". The nightly reaches the same postings from the
    search listing, so 12 of the 21 pasted Indeed URLs were already scraped.
    Failing on those would discard work already done."""
    db = tmp_path / "_analyzed.json"
    db.write_text(json.dumps([{
        "title": "Product Designer (Platform)", "company": "Revolut",
        "url": "https://uk.indeed.com/viewjob?jk=041cc148b17a1ece&from=serp",
        "description": "x" * 5000, "source": "indeed",
        "match": {"composite_score": 0.81},
    }]))
    monkeypatch.setattr(s, "ANALYZED_PATH", str(db))

    pasted = "https://uk.indeed.com/viewjob?jk=041cc148b17a1ece&hl=en"
    got = s.adopt_from_database([pasted])
    assert len(got) == 1
    assert got[0]["company"] == "Revolut"
    # The pasted URL is kept so a re-run recognises it as already handled.
    assert got[0]["url"] == pasted
    # Scoring is re-derived by run.py on merge; carrying a stale one would
    # make this staging file look authoritative.
    assert "match" not in got[0]


def test_a_posting_not_in_the_database_is_not_invented(tmp_path, monkeypatch):
    db = tmp_path / "_analyzed.json"
    db.write_text(json.dumps([]))
    monkeypatch.setattr(s, "ANALYZED_PATH", str(db))
    assert s.adopt_from_database(["https://uk.indeed.com/viewjob?jk=deadbeef"]) == []


def test_a_database_entry_without_a_description_is_not_adopted(tmp_path, monkeypatch):
    # An empty description is the unscoreable state the pipeline already guards
    # against elsewhere; adopting one would launder it into the staging file.
    db = tmp_path / "_analyzed.json"
    db.write_text(json.dumps([{
        "title": "Ghost", "company": "Nowhere",
        "url": "https://uk.indeed.com/viewjob?jk=041cc148b17a1ece",
        "description": "", "source": "indeed",
    }]))
    monkeypatch.setattr(s, "ANALYZED_PATH", str(db))
    assert s.adopt_from_database(["https://uk.indeed.com/viewjob?jk=041cc148b17a1ece"]) == []


def test_a_missing_database_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "ANALYZED_PATH", str(tmp_path / "nope.json"))
    assert s.adopt_from_database(["https://uk.indeed.com/viewjob?jk=abc123"]) == []
