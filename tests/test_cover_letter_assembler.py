"""Assembled cover letters: block selection, the one model-written block, and
the gates around it. Every LLM call is mocked."""

import cover_letter_generator as cl


def _facts():
    return [
        {"source_id": "taifunome-research-platform", "fact": "Building TAIFUNOME meant owning the design system and the data engine.",
         "tier": "core", "group": "taifunome", "roles": ["product_designer", "general"],
         "keywords": ["design system", "cms"]},
        {"source_id": "taifunome_studio", "fact": "I have run TAIFUNOME as an independent studio since 2023.",
         "tier": "core", "group": "taifunome", "roles": ["product_designer", "general"],
         "keywords": ["design system", "research"]},
        {"source_id": "web3-node-ops", "fact": "I ran blockchain nodes on Linux with Docker and monitored them with Prometheus.",
         "tier": "operational", "group": "", "roles": ["technical_support"],
         "keywords": ["linux", "docker"]},
        {"source_id": "portfolio_website", "fact": "I built kazukiyunome.com with semantic HTML and no build tools.",
         "tier": "technical", "group": "", "roles": ["product_designer", "general"],
         "keywords": ["html", "frontend"]},
    ]


def _bank():
    return [
        {"id": "E01", "source_id": "taifunome-research-platform",
         "title": "TAIFUNOME — Research & Creative Technology Platform",
         "role": "Independent Studio", "period": "2026 – Present",
         "kind": "self-directed project", "facts": "..."},
        {"id": "E02", "source_id": "taifunome_studio",
         "title": "Independent Creative Technologist", "role": "TAIFUNOME",
         "period": "2023 – Present", "kind": "employment", "facts": "..."},
        {"id": "E03", "source_id": "web3-node-ops", "title": "Web3 Node Ops",
         "role": "Independent Studio", "period": "2025",
         "kind": "self-directed project", "facts": "..."},
        {"id": "E04", "source_id": "portfolio_website",
         "title": "Portfolio Website Design & Development",
         "role": "Independent Studio", "period": "2026 – Present",
         "kind": "self-directed project", "facts": "..."},
    ]


def _use_fixtures(monkeypatch):
    monkeypatch.setattr(cl, "_load_letter_facts", _facts)
    monkeypatch.setattr(cl, "_load_evidence_bank", _bank)


# --- evidence selection ----------------------------------------------------

def test_selection_is_deterministic_for_the_same_posting(monkeypatch):
    _use_fixtures(monkeypatch)
    posting = "We need a design system and a CMS."

    first = cl._select_evidence("Product Designer", posting, "product_designer")
    second = cl._select_evidence("Product Designer", posting, "product_designer")

    assert [f["source_id"] for f in first] == [f["source_id"] for f in second]


def test_selection_is_gated_by_role(monkeypatch):
    _use_fixtures(monkeypatch)

    selected = cl._select_evidence("Support Engineer", "Linux and Docker.", "technical_support")

    assert [f["source_id"] for f in selected] == ["web3-node-ops"]


def test_selection_takes_at_most_one_fact_per_group(monkeypatch):
    """Both TAIFUNOME records outrank the portfolio site on keywords. Taking the
    top two by score alone spent two paragraphs on the platform the canonical
    narrative had already named."""
    _use_fixtures(monkeypatch)

    selected = cl._select_evidence("Product Designer", "design system", "product_designer")

    assert [f["source_id"] for f in selected] == ["taifunome-research-platform"]


def test_a_technical_block_joins_only_when_the_posting_asks_for_it(monkeypatch):
    """The CV carries the stack. A letter that repeats it has spent a paragraph
    saying nothing the reader did not already have."""
    _use_fixtures(monkeypatch)

    without = cl._select_evidence("Product Designer", "design system", "product_designer")
    with_ask = cl._select_evidence("Product Designer", "design system, frontend html",
                                   "product_designer")

    assert "portfolio_website" not in [f["source_id"] for f in without]
    assert [f["source_id"] for f in with_ask] == [
        "taifunome-research-platform", "portfolio_website"]


def test_the_first_block_is_always_a_core_one(monkeypatch):
    """Method and ownership are what the letter is for; implementation detail
    is what the CV is for."""
    _use_fixtures(monkeypatch)

    selected = cl._select_evidence("Product Designer", "frontend html frontend html",
                                   "product_designer")

    assert selected[0]["tier"] == "core"


def test_a_fact_whose_cv_entry_is_gone_is_not_selectable(monkeypatch):
    """Deleting a CV entry, or marking it cover_letter: false, has to withdraw
    its letter fact — otherwise the letter keeps citing work the CV no longer
    claims."""
    monkeypatch.setattr(cl, "_load_letter_facts", _facts)
    monkeypatch.setattr(cl, "_load_evidence_bank",
                        lambda: [r for r in _bank() if r["source_id"] != "web3-node-ops"])

    selected = cl._select_evidence("Support Engineer", "Linux and Docker.", "technical_support")

    assert "web3-node-ops" not in [f["source_id"] for f in selected]


# --- the canonical narrative ----------------------------------------------

def test_canonical_narrative_excludes_the_authoring_guidance_and_translation():
    text = cl._load_canonical_narrative()

    assert text
    assert "word_budget" not in text
    assert "和訳" not in text
    assert "参照用" not in text
    # Hard wrapping belongs to the source file, not to the letter.
    assert not any(len(line) < 90 and line.endswith(("and", "the", "a"))
                   for line in text.splitlines())


# --- bridge normalisation and gates ---------------------------------------

def test_normalise_strips_bold_and_folds_the_two_sentences_into_one_paragraph():
    raw = "**TAIFUNOME** shows one thing.\n\nI would bring the same to you."

    assert cl._normalise_bridge(raw) == \
        "TAIFUNOME shows one thing. I would bring the same to you."


def test_bridge_rejects_an_exit_plan(monkeypatch):
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)

    ok, reason = cl._vet_bridge(
        "I would bring the same working method to your team. It is a step toward "
        "an independent venture of my own.",
        "", "Product Designer", "A posting.")

    assert not ok
    assert reason == "mentions an exit plan"


def test_a_style_ban_is_forgiven_when_the_posting_uses_the_word(monkeypatch):
    """The employer's own vocabulary for their own product is quotation, not
    filler. Rejecting it dropped otherwise good letters onto the static bridge."""
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)
    bridge = ("You build scalable services, which is the part I want to work on "
              "next. I would bring the way I structure a system so new parts fit "
              "without a rewrite.")

    assert cl._vet_bridge(bridge, "", "Engineer", "We build scalable services.")[0]
    assert not cl._vet_bridge(bridge, "", "Engineer", "We build services.")[0]


def test_flattery_is_never_forgiven_even_when_the_posting_says_it(monkeypatch):
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)

    ok, reason = cl._vet_bridge(
        "I am passionate about the problem you are solving. I would bring the "
        "way I structure a system so new parts fit without a rewrite.",
        "", "Engineer", "We want someone passionate about our mission.")

    assert not ok
    assert "passionate about" in reason


def test_bridge_may_not_open_by_calling_the_candidates_method_the_readers(monkeypatch):
    """Five of six bridges written against real postings opened this way. "your"
    is the employer, so the sentence hands them their own focus and the
    candidate disappears from it."""
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)

    ok, reason = cl._vet_bridge(
        "Your focus on translating complex systems into clear structures feels "
        "relevant to Pine Tree Barn's work of guiding customers. I would help "
        "turn abstract ideas into executable plans.",
        "", "Designer", "A posting.")

    assert not ok
    assert reason.startswith("opens by calling the candidate's own method theirs")


def test_addressing_the_reader_after_the_opening_is_still_allowed(monkeypatch):
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)

    ok, reason = cl._vet_bridge(
        "Example's interest in research tooling feels relevant to the way I "
        "built my own platform. I would bring that approach to your team.",
        "", "Engineer", "A posting.")

    assert ok, reason


def test_bridge_rejects_handing_the_candidates_own_project_to_the_reader(monkeypatch):
    """"work" is absent from _CANDIDATE_ATTRIBUTES because "your work at X"
    legitimately addresses the reader. It stops being ambiguous once the
    sentence also names a project that is the candidate's."""
    monkeypatch.setattr(cl, "_load_evidence_bank", _bank)
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)
    evidence = [_facts()[0]]

    ok, reason = cl._vet_bridge(
        "Example builds research tooling, which is the part I want next. I would "
        "bring your work on modular systems, like TAIFUNOME, to that team.",
        "", "Engineer", "A posting.", evidence)

    assert not ok
    assert "own project" in reason


def test_bridge_rejects_align_in_every_form(monkeypatch):
    """Told not to write "aligns with", the model produced "aligned", then
    "alignment". The check is a stem for that reason."""
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)

    for variant in ("aligns with", "aligned", "alignment"):
        ok, reason = cl._vet_bridge(
            f"Your roadmap and my direction are in {variant} on the same problem. "
            "I would bring the way I structure a system so new parts fit.",
            "", "Engineer", f"We value {variant} across teams.")
        assert not ok, variant
        assert "align" in reason


def test_bridge_rejects_the_posting_quoted_back(monkeypatch):
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)
    posting = ("We believe human judgment and machine intelligence reinforce "
               "each other in every product we ship.")

    ok, reason = cl._vet_bridge(
        "You hold that human judgment and machine intelligence reinforce each "
        "other, which is the part I want next. I would bring the way I "
        "structure a system so new parts fit.",
        "", "Engineer", posting)

    assert not ok
    assert reason.startswith("quotes the posting back")


def test_shared_vocabulary_alone_is_not_quoting(monkeypatch):
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)
    posting = "You will build design systems and ship prototypes every week."

    ok, reason = cl._vet_bridge(
        "You build design systems, which is the part I want to work on next. I "
        "would bring the way I structure prototypes so new parts fit.",
        "", "Engineer", posting)

    assert ok, reason


def test_naming_a_project_alongside_the_readers_team_is_allowed(monkeypatch):
    monkeypatch.setattr(cl, "_load_evidence_bank", _bank)
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)
    evidence = [_facts()[0]]

    ok, reason = cl._vet_bridge(
        "You ship products where structure decides the pace, which is the part I "
        "want next. I would bring what I built in TAIFUNOME to your team.",
        "", "Engineer", "A posting.", evidence)

    assert ok, reason


# --- assembly --------------------------------------------------------------

def test_assembly_orders_the_blocks_and_ends_on_the_bridge():
    """No sign-off line after the bridge. A stock "I would welcome the chance to
    talk" was a third sentence saying nothing the two before it had not."""
    body = cl._assemble_letter_body(
        "Product Designer", "Example", "Identity paragraph.",
        [{"fact": "Evidence one."}, {"fact": "Evidence two."}], "Bridge sentence.")

    assert body.splitlines()[0] == \
        "I am writing to apply for the Product Designer position at Example."
    assert body.split("\n\n") == [
        "I am writing to apply for the Product Designer position at Example.",
        "Identity paragraph.", "Evidence one.", "Evidence two.", "Bridge sentence."]


def test_bridge_may_not_name_a_tool(monkeypatch):
    """The CV lists the stack. Spending the letter's last two sentences on a
    toolbar is what "prototype AI-assisted UX flows in Cursor and Claude Code"
    did."""
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)

    ok, reason = cl._vet_bridge(
        "You build research tools, which is the part I want next. I would "
        "prototype those flows in Figma and refine them from there.",
        "", "Engineer", "A posting.")

    assert not ok
    assert "figma" in reason


def test_bridge_must_be_two_sentences(monkeypatch):
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)

    ok, reason = cl._vet_bridge(
        "You build research tools. That is the part I want next. I would bring "
        "the way I structure a system so new parts fit.",
        "", "Engineer", "A posting.")

    assert not ok
    assert reason == "3 sentences, must be 2"


def test_the_body_never_carries_framing_the_master_template_supplies():
    """The predecessor prepended its own "Dear Hiring Team," to a body that
    MASTER_COVER_LETTER already greets, and every legacy letter went out with
    the greeting twice."""
    letter, _ = cl.generate_cover_letter("Product Designer", "Example", "London, England", "")

    assert letter.count("Dear Hiring Team,") == 1
    assert letter.count("Yours sincerely,") == 1
    assert "Hiring Team\nExample\nLondon" in letter


def test_a_thin_posting_gets_the_static_bridge_and_says_so(monkeypatch):
    def fail(*_a, **_k):
        raise AssertionError("a thin posting must not reach the model")
    monkeypatch.setattr(cl, "_generate_context_bridge", fail)

    letter, source = cl.generate_cover_letter("Product Designer", "Example", "London", "Too short.")

    assert source == "assembled-static"
    assert "I am applying to Example because" in letter


def test_a_vetted_bridge_is_used_and_reported_as_written(monkeypatch):
    bridge = ("You build research tools, which is the part I want to work on next. "
              "I would bring the way I structure a system so new parts fit without "
              "a rewrite.")
    monkeypatch.setattr(cl, "_generate_context_bridge", lambda *a, **k: bridge)
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)

    letter, source = cl.generate_cover_letter(
        "Product Designer", "Example", "London", "A detailed posting. " * 60)

    assert source == "assembled"
    assert bridge in letter


def test_a_bridge_that_cannot_pass_falls_back_without_failing_the_letter(monkeypatch):
    monkeypatch.setattr(cl, "_generate_context_bridge",
                        lambda *a, **k: "I am passionate about your mission. I would help.")
    monkeypatch.setattr(cl, "_verify_opening_claims", lambda *a, **k: None)

    letter, source = cl.generate_cover_letter(
        "Product Designer", "Example", "London", "A detailed posting. " * 60)

    assert source == "assembled-static"
    assert "passionate about" not in letter


def test_assembled_letters_stay_within_the_one_page_budget():
    for title in ("Product Designer", "Graphic Designer", "Technical Support Engineer",
                  "Camera Assistant", "Web Developer"):
        letter, _ = cl.generate_cover_letter(title, "Example", "London", "")
        body = letter.split("Dear Hiring Team,")[1].rsplit("Yours sincerely,")[0]
        ok, reason = cl._vet_letter_body(body.strip())
        assert ok, f"{title}: {reason}"
