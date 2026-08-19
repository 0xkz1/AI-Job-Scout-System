"""Remote Japanese postings: one site's search, invisible to every other.

The candidate is a Japanese national living in the UK, so a FULLY REMOTE
Japanese role is holdable and an on-site Tokyo one is not — the same rule the
EU countries already follow. reed, guardian and adzuna are UK job boards, so
"Remote (Japan)" would spend one of their rationed searches on a string they
read as a town name; the location therefore lives under `site_only_locations`
and reaches exactly one scraper.

Four things have to hold, and each is easy to lose:

  - a caller that does not name a site sees the pairs it always saw. The
    per-site cron budget (44 pairs against a 1500s timeout) is counted from
    that list, and a Japan pair costs reed nothing.
  - remote is asked for in the KEYWORD. LinkedIn's f_WT=2 filter is measured
    not to work on the guest endpoint (2026-08-19), so a search that trusts it
    returns Tokyo commutes that look filtered.
  - only full remote survives. "リモート可" is permission to work from home
    some days, which is an office job with a benefit.
  - the filters can read Japanese. The relevance filter cut 19 of 22 remote
    postings on the first pass, purely because they were written in Japanese.
"""

import pytest

import selection
import scraper_linkedin_guest as lg


CONFIG = {
    "keywords": ["Web Developer", "QA Analyst"],
    "locations": ["Edinburgh", "Remote"],
    "keyword_locations": {"QA Analyst": ["Glasgow", "Remote"]},
    "site_only_locations": {"linkedin": ["Remote (Japan)"]},
}


# --- who sees the location ---

def test_a_caller_that_names_no_site_sees_no_japan_pair():
    pairs = selection.search_pairs(CONFIG)
    assert ("Web Developer", "Remote (Japan)") not in pairs
    assert all("Japan" not in loc for _kw, loc in pairs)


def test_uk_boards_are_unaffected():
    """reed and guardian pass their own name, and must get the old list."""
    baseline = selection.search_pairs(CONFIG)
    assert selection.search_pairs(CONFIG, site="reed") == baseline
    assert selection.search_pairs(CONFIG, site="guardian") == baseline


def test_linkedin_gets_the_japan_pair_for_every_keyword():
    pairs = selection.search_pairs(CONFIG, site="linkedin")
    japan = [kw for kw, loc in pairs if loc == "Remote (Japan)"]
    assert japan == ["Web Developer", "QA Analyst"]


def test_the_japan_pair_is_added_and_nothing_is_taken_away():
    baseline = selection.search_pairs(CONFIG)
    pairs = selection.search_pairs(CONFIG, site="linkedin")
    assert [p for p in pairs if p[1] != "Remote (Japan)"] == baseline
    assert len(pairs) == len(baseline) + len(CONFIG["keywords"])


def test_a_location_already_listed_is_not_searched_twice():
    config = dict(CONFIG, site_only_locations={"linkedin": ["Remote"]})
    pairs = selection.search_pairs(config, site="linkedin")
    assert len(pairs) == len(set(pairs))
    assert pairs == selection.search_pairs(config)


def test_no_site_only_locations_is_the_previous_behaviour():
    config = {k: v for k, v in CONFIG.items() if k != "site_only_locations"}
    assert selection.search_pairs(config, site="linkedin") == selection.search_pairs(config)


# --- what LinkedIn is actually asked ---

def test_remote_japan_does_not_claim_a_filter_linkedin_ignores():
    """f_WT=2 is measured NOT to work on the guest endpoint for a country search
    (2026-08-19: same postings with and without it, one titled "Web Developer
    onsite Tokyo"). Writing it anyway would read as a guarantee that the results
    do not keep, and would hide the gate that is doing the real work."""
    params = lg._location_params("Remote (Japan)")
    assert params == {"location": "Japan"}
    assert "f_WT" not in params


def test_remote_is_asked_for_in_the_keyword_instead():
    """The full-text index is the part the guest endpoint does serve."""
    assert lg._search_keyword("Web Developer", "Remote (Japan)") == "Web Developer リモート"


def test_the_japanese_term_is_used_not_a_translation_of_remote():
    """A posting written in Japanese says リモート; "remote" finds the
    English-language listings, which is a smaller and different market."""
    asked = lg._search_keyword("QA Analyst", "Remote (Japan)")
    assert "リモート" in asked
    assert asked.startswith("QA Analyst")


def test_a_uk_search_keyword_is_untouched():
    assert lg._search_keyword("Web Developer", "Remote") == "Web Developer"
    assert lg._search_keyword("Web Developer", "Edinburgh") == "Web Developer"


def test_bare_remote_still_means_the_uk():
    assert lg._location_params("Remote") == {"location": "United Kingdom", "f_WT": "2"}


def test_a_city_is_still_passed_through_untouched():
    assert lg._location_params("Edinburgh") == {"location": "Edinburgh"}


@pytest.mark.parametrize("written", ["Remote (Japan)", "remote (japan)", " Remote (Japan) "])
def test_the_spelling_of_the_pseudo_location_is_forgiving(written):
    assert lg._location_params(written) == {"location": "Japan"}
    assert lg._search_keyword("Designer", written).endswith("リモート")


def test_a_bare_country_is_not_a_pseudo_location():
    """"Japan" in `locations` would be an on-site search, and would silently
    skip both the remote keyword and the gate below."""
    assert lg._location_params("Japan") == {"location": "Japan"}
    assert lg._search_keyword("Designer", "Japan") == "Designer"


# --- the full-remote gate ---

@pytest.mark.parametrize("text", [
    "【フルリモート】QAエンジニア。全国どこからでも勤務可能。",
    "完全リモートで働けます",
    "This is a fully remote position",
    "100% remote, work from anywhere in Japan",
])
def test_a_stated_full_remote_posting_is_kept(text):
    jobs = lg._drop_partial_remote([{"description": text, "search_location": "Remote (Japan)"}])
    assert len(jobs) == 1


@pytest.mark.parametrize("text", [
    "リモート可。週2回の出社があります。",           # permission, not a location
    "リモート勤務可（月4回出社）",
    "東京オフィス勤務。リモートワーク制度あり。",     # a benefit, not the job
    "Hybrid: three days in the Tokyo office",
])
def test_partial_remote_is_dropped_before_it_costs_anything(text):
    """Filter-passing jobs go on to LLM enrichment, so a posting that cannot be
    held from the UK has to die here, not after it has been analysed and then
    scored down for its location."""
    assert lg._drop_partial_remote([{"description": text, "search_location": "Remote (Japan)"}]) == []


def test_the_gate_belongs_to_the_search_not_to_the_posting():
    """A UK job says nothing about full remote and must not be judged on it."""
    uk = {"description": "Hybrid, two days in the Edinburgh office", "search_location": "Remote"}
    assert lg._drop_partial_remote([uk]) == [uk]


def test_the_search_tag_never_leaves_the_scraper():
    """`search_location` is bookkeeping. Every job dict here is written to the
    database as-is, so the key has to be gone by the time it is returned."""
    jobs = lg._drop_partial_remote([
        {"description": "フルリモート", "search_location": "Remote (Japan)"},
        {"description": "anything", "search_location": "Edinburgh"},
    ])
    assert len(jobs) == 2
    assert all("search_location" not in j for j in jobs)


# --- the pair reaches the network layer ---

def test_the_scraper_walks_the_japan_search(monkeypatch):
    walked: list[tuple[str, str]] = []
    monkeypatch.setattr(lg, "search", lambda kw, loc, max_pages=3: walked.append((kw, loc)) or [])
    monkeypatch.setattr(lg, "fill_descriptions", lambda jobs, cache=None: None)
    monkeypatch.setattr("scraper_helper.load_description_cache", lambda: {})
    lg.scrape_linkedin_guest_all(dict(CONFIG, max_pages_per_search=1))
    assert ("Web Developer", "Remote (Japan)") in walked


# --- the config on disk ---

def test_the_shipped_config_only_grants_this_to_a_configured_site():
    """A typo'd or retired site name here is silently dead weight: the location
    would belong to a scraper that never runs, and nothing else would say so."""
    config = selection.load_config()
    sites = set(config.get("sites") or [])
    for site in (config.get("site_only_locations") or {}):
        assert site in sites, f"site_only_locations names '{site}', which is not in sites"


def test_every_site_only_location_is_one_this_scraper_knows():
    """An entry the scraper has no spec for is not a narrower search — it is a
    plain text location, searched on-site, with no remote term and no gate. It
    would look like it worked and quietly fill the database with Tokyo commutes."""
    config = selection.load_config()
    for site, locs in (config.get("site_only_locations") or {}).items():
        if site != "linkedin":
            continue
        for loc in locs:
            assert lg._site_location(loc), f"{loc!r} has no entry in _SITE_LOCATIONS"


# --- how a Japanese posting is scored ---

def test_remote_japan_scores_with_the_target_markets_not_as_unknown():
    """Without a branch of its own, Japan falls through to the generic
    non-target country (0.45) or to "location unknown" (0.15) — low enough that
    a scraped Japanese posting could never reach a CV, which would make the
    whole search pointless."""
    import matcher
    verdict = matcher._classify_international_location("tokyo, tokyo, japan", is_remote=True)
    assert verdict is not None
    assert verdict["score"] >= 0.80


def test_on_site_japan_is_out_of_scope():
    import matcher
    verdict = matcher._classify_international_location("minato, tokyo, japan", is_remote=False)
    assert verdict["score"] <= 0.15


@pytest.mark.parametrize("loc", [
    "Tokyo, Tokyo, Japan", "Greater Tokyo Area", "Kanagawa, Japan",
    "Tsukuba, Ibaraki, Japan", "Greater Osaka Area", "Yokohama, Kanagawa, Japan",
])
def test_the_location_strings_linkedin_actually_writes_are_recognised(loc):
    """Measured from a live run: half of these never contain the word "Japan"."""
    import matcher
    assert matcher._classify_international_location(loc.lower(), is_remote=True) is not None


def test_a_uk_location_is_untouched_by_the_japan_branch():
    import matcher
    assert matcher._classify_international_location("edinburgh, scotland, united kingdom",
                                                    is_remote=True) is None


def test_the_timezone_cost_is_stated_rather_than_priced_in_silently():
    """JST is 8-9h ahead of the UK. The score says the market is in scope; the
    note is what tells the reader a synchronous role is a night shift."""
    import matcher
    verdict = matcher._classify_international_location("tokyo, japan", is_remote=True)
    assert any("JST" in n for n in verdict["notes"])


# --- work style, read in Japanese ---

@pytest.mark.parametrize("text,expected", [
    ("フルリモートで全国どこからでも勤務可能", "remote"),
    ("在宅勤務が基本です", "remote"),
    ("リモート可（週2回出社）", "hybrid"),
    ("東京本社に出社していただきます", "onsite"),
])
def test_a_japanese_posting_states_its_work_style_in_japanese(text, expected):
    """Otherwise it lands on "unknown" and buys an Ollama call to be told what
    the text already says."""
    import analyzer
    assert analyzer.classify_work_style("エンジニア", text) == expected


@pytest.mark.parametrize("loc", ["Fukuoka, Japan", "Tsukuba, Ibaraki, Japan",
                                 "Fukushima, Japan"])
def test_a_place_name_containing_uk_is_not_the_united_kingdom(loc):
    """"uk" was matched as a substring, so Fukuoka and Tsukuba were read as the
    United Kingdom: the posting skipped the international branch and was scored
    against the UK city tiers, and its match report said country UK."""
    import matcher
    assert matcher._classify_international_location(loc.lower(), is_remote=True) is not None
    assert matcher._infer_country({"location": loc}) == "Japan"


def test_the_uk_itself_still_reads_as_the_uk():
    import matcher
    for loc in ["Edinburgh, Scotland, United Kingdom", "London, England",
                "Remote, UK", "Glasgow"]:
        assert matcher._classify_international_location(loc.lower(), is_remote=True) is None
        assert matcher._infer_country({"location": loc}) == "UK"


# --- the relevance filter, in the other language ---

def test_search_terms_carry_the_aliases_alongside_the_keywords():
    import scraper_linkedin_guest as lg
    config = dict(CONFIG, keyword_aliases={"QA Analyst": ["QAエンジニア", "品質保証"]})
    terms = lg.search_terms(config)
    assert "QA Analyst" in terms and "Web Developer" in terms
    assert "QAエンジニア" in terms and "品質保証" in terms


def test_a_japanese_posting_survives_the_relevance_filter():
    """MEASURED: 22 postings passed the remote gate and 3 passed this filter,
    because 【フルリモート】QAエンジニア contains no English keyword."""
    import scraper_linkedin_guest as lg
    from scraper_indeed import filter_jobs_by_keywords
    config = dict(CONFIG, keyword_aliases={"QA Analyst": ["QAエンジニア"]})
    job = {"title": "【フルリモート】QAエンジニア", "description": "テスト自動化", "snippet": ""}
    assert filter_jobs_by_keywords([job], config["keywords"]) == []
    assert filter_jobs_by_keywords([job], lg.search_terms(config)) == [job]


def test_an_unrelated_japanese_posting_is_still_cut():
    """The aliases are per keyword so the filter stays as narrow as in English.
    Bare エンジニア is not one of them — it matches the whole market."""
    import scraper_linkedin_guest as lg
    from scraper_indeed import filter_jobs_by_keywords
    config = selection.load_config()
    job = {"title": "SAP FI Consultant", "description": "SAP会計モジュールの導入", "snippet": ""}
    assert filter_jobs_by_keywords([job], lg.search_terms(config)) == []


def test_every_alias_belongs_to_a_keyword_that_exists():
    """An alias under a retired or misspelled keyword is not a narrower filter —
    it is a term with no owner, widening the filter for every keyword at once."""
    config = selection.load_config()
    keywords = set(config.get("keywords") or [])
    for kw in (config.get("keyword_aliases") or {}):
        assert kw in keywords, f"keyword_aliases names '{kw}', which is not a keyword"


def test_the_shipped_aliases_cover_the_keywords_the_japan_search_walks():
    """A keyword with no alias searches Japan and then discards everything it
    finds that is written in Japanese — the failure is silent and total."""
    config = selection.load_config()
    if not (config.get("site_only_locations") or {}).get("linkedin"):
        pytest.skip("no site-only location configured")
    aliases = config.get("keyword_aliases") or {}
    missing = [k for k in (config.get("keywords") or []) if not aliases.get(k)]
    assert not missing, f"no Japanese alias for: {missing}"


def test_the_japan_pairs_are_walked_at_their_own_depth(monkeypatch):
    """Every card costs a description fetch BEFORE the gate can read it, so
    depth is what the Japan search actually spends: 12 searches at depth 1 cost
    278s of the 1500s the whole site gets. Depth 3 would be ~800s."""
    seen: list[tuple[str, int]] = []
    monkeypatch.setattr(lg, "search",
                        lambda kw, loc, max_pages=3: seen.append((loc, max_pages)) or [])
    monkeypatch.setattr(lg, "fill_descriptions", lambda jobs, cache=None: None)
    monkeypatch.setattr("scraper_helper.load_description_cache", lambda: {})
    lg.scrape_linkedin_guest_all(dict(CONFIG, max_pages_per_search=3))
    depths = dict(seen)
    assert depths["Remote (Japan)"] == 1
    assert depths["Edinburgh"] == 3
