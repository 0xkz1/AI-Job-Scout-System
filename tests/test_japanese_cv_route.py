"""The Japanese CV: assembled from authored translations, never model-written.

Every record under career/cv/** carries its English body and a "## 和訳" half
that says the same thing in Japanese, written and checked by hand. The English
CV has always thrown the Japanese away; the ja route reads it instead.

The point of the design is that no Japanese sentence on the CV was produced at
generation time. A model still ranks the projects — that is a judgement about
the posting, not about the prose — but its output is read back as an ORDER and
every paragraph is re-rendered from source. A model asked to echo a Japanese
paragraph verbatim will quietly smooth it, and smoothing a verified translation
is exactly the failure this route exists to prevent (it is how "全工程を自前で
担う" became "全工程を社内で手がける", which reads as an incorporated company).

Four properties carry that, and each is easy to lose in a refactor:

  - the two languages never mix. An entry with no 和訳 is dropped from the ja
    CV, not printed in English.
  - the English CV is untouched by any of it.
  - the model's prose never survives; only its ordering does.
  - the page fit is measured in CHARACTERS. Japanese writes no spaces, so the
    word budget reports a full ja CV as ~200 words and would pad every one of
    them to the maximum.
"""
import cv_generator as cg


JA_ONLY = "_ja_only_entry"


def _entry(pid, en="English body.", ja="日本語の本文。"):
    return {
        "id": pid,
        "title": pid.replace("_", " ").title(),
        "role": "Independent Studio",
        "period": "2026",
        "description": en,
        "description_ja": ja,
        "tags": [],
        "skills": [],
        "url": "",
        "type": "project",
        "cover_letter": True,
    }


# ── the splitter ───────────────────────────────────────────────────────────

def test_split_returns_both_halves_without_the_authors_note():
    body = (
        "\nEnglish body here.\n"
        "\n## 和訳\n"
        "\n（参照用。CVには含まれない — 英文を編集したらここも更新すること）\n"
        "\n日本語の本文。\n"
    )
    en, ja = cg._split_translation(body)
    assert en == "English body here."
    assert ja == "日本語の本文。"
    # The note is addressed to whoever edits the file. A reader must never see it.
    assert "参照用" not in ja


def test_split_reports_missing_translation_as_empty_not_as_english():
    en, ja = cg._split_translation("\nEnglish only, no 和訳 section heading.\n")
    assert en.startswith("English only")
    assert ja == ""


def test_every_shipped_record_has_a_translation():
    """The ja route silently drops an untranslated entry, so a record that
    loses its 和訳 would shrink the CV with no error. This is the alarm."""
    missing = [p["id"] for p in cg._ALL_ENTRIES if not p.get("description_ja")]
    assert missing == [], f"records with no ## 和訳: {missing}"


# ── the two languages never mix ────────────────────────────────────────────

def test_entry_with_no_translation_is_dropped_not_rendered_in_english():
    entry = _entry(JA_ONLY, en="Untranslated English paragraph.", ja="")
    assert cg._entry_description(entry, "ja") == ""

    original = list(cg.PROJECTS)
    try:
        cg.PROJECTS.append(entry)
        rendered = cg._render_entries([JA_ONLY, "taifunome-research-platform"], "ja")
    finally:
        cg.PROJECTS[:] = original

    assert "Untranslated English paragraph." not in rendered
    assert "TAIFUNOME" in rendered


def test_japanese_cv_carries_no_english_section_headers():
    cv = cg.generate_cv(role_type="web_developer", job_title="テスト", company="テスト社", lang="ja")
    for english_header in ("## PROFILE", "## EXPERIENCE", "## SELECTED PROJECTS",
                           "## TECHNICAL TOOLKIT", "## EDUCATION & LANGUAGES"):
        assert english_header not in cv
    for ja_header in ("## プロフィール", "## 職務経験", "## プロジェクト", "## 技術スタック"):
        assert ja_header in cv


def test_japanese_cv_uses_the_authored_translation_verbatim():
    cv = cg.generate_cv(role_type="web_developer", job_title="テスト", company="テスト社", lang="ja")
    taifunome = next(p for p in cg.EMPLOYMENT if p["id"] == "taifunome_studio")
    assert taifunome["description_ja"] in cv
    # ...and not the English it was translated from.
    assert "Runs the whole chain in-house" not in cv


# ── the English CV is untouched ────────────────────────────────────────────

def test_english_cv_still_discards_the_translation():
    cv = cg.generate_cv(role_type="web_developer", job_title="Test Role", company="Test Co")
    assert "和訳" not in cv
    assert "参照用" not in cv
    assert "## PROFILE" in cv


def test_english_is_the_default_language():
    assert cg.get_profile("web_developer") == cg.get_profile("web_developer", "en")
    assert cg._entry_description(_entry("x"), ) == "English body."


# ── the model ranks; it does not write ─────────────────────────────────────

def test_ranking_is_read_back_and_the_models_prose_is_discarded():
    # The three title shapes the model actually emits: plain, partly bolded,
    # and the prompt's own "[Project Title]" placeholder brackets copied out.
    body = (
        "Portfolio Website Design & Development | Independent Studio | 2026 – Present\n"
        "Prose the model echoed, which must not survive.\n"
        "\n"
        "**TAIFUNOME — Research & Creative Technology Platform** | Independent Studio | 2026 – Present\n"
        "More echoed prose.\n"
        "\n"
        "[Asset Weaver — Obsidian Plugin] | Independent Studio | 2026\n"
        "Yet more.\n"
    )
    ids = cg._ids_from_experience_body(body)
    assert ids == [
        "portfolio_website",
        "taifunome-research-platform",
        "asset-weaver-obsidian-plugin",
    ], "ranking must survive, in the model's order"

    rendered = cg._render_entries(ids, "ja")
    assert "echoed" not in rendered and "Prose the model" not in rendered
    # Each paragraph came from its source file instead.
    for pid in ids:
        source = next(p for p in cg.PROJECTS if p["id"] == pid)
        assert source["description_ja"] in rendered


def test_unrecognised_titles_are_ignored_rather_than_invented():
    body = "A Project That Does Not Exist | Independent Studio | 2026\nBody.\n"
    assert cg._ids_from_experience_body(body) == []


def test_ja_falls_back_to_static_ordering_when_the_model_gave_nothing():
    body = cg._experience_body("", "", "web_developer", "ja")
    assert body == cg._get_static_experience("web_developer", "ja")
    assert body.strip()


# ── the page fit is counted in characters ──────────────────────────────────

def test_japanese_cv_fits_two_pages_worth_of_characters():
    """Word counting cannot see a Japanese CV at all — this is what replaces it.

    The ceiling is measured through the live renderer (see _CV_JA_MAX_CHARS);
    the assertion here is that the trim actually runs, which the word-budget
    branch could never have done.
    """
    for role in ("web_developer", "creative_technologist", "product_designer", "general"):
        cv = cg.generate_cv(role_type=role, job_title="テスト", company="テスト社", lang="ja")
        body = cv.split("---", 2)[2]
        assert len(body) <= cg._CV_JA_MAX_CHARS + cg._ENTRY_LINE_COST_JA, (
            f"{role}: ja CV is {len(body)} chars, over the two-page budget"
        )
        # Words would have reported this same CV as a couple of hundred, i.e.
        # a shortfall of ~900 against _CV_TARGET_WORDS on every single role.
        assert len(body.split()) < cg._CV_TARGET_WORDS


def test_trim_keeps_the_leading_entries_and_never_goes_below_the_floor():
    entries = [f"Entry {i} | Independent Studio | 2026\n" + "あ" * 2000 for i in range(5)]
    trimmed = cg._fit_japanese("\n\n".join(entries), "x" * 20000)
    assert len(cg._split_entries(trimmed)) == cg._CV_MIN_ENTRIES
    assert trimmed.startswith("Entry 0 |"), "the most relevant entry is never the one dropped"


def test_other_projects_label_is_translated_but_titles_are_not():
    line = cg._other_projects_line("", "ja")
    assert line.startswith("**その他のプロジェクト:**")
    # Project names are names. A reader looking one up needs the real title.
    assert "TAIFUNOME" in line
    assert cg._other_projects_line("", "en").startswith("**Other projects:**")
