"""A CV's two-page budget is enforced on the rendered PDF, not on a word count.

cv_generator.py caps a CV at _CV_MAX_WORDS words and the ja route at a
character count. Both are proxies for page space, and measurement says they are
not tight ones: of the 75 PDFs on disk on 2026-08-30, three CVs render three
pages and all three pass the word gate — 1077 and 1078 body words against a
1080 target, 1115 against the 1120 maximum. One of the three was sent (Opus 2
Platform Engineer, applied 2026-08-18).

Lowering the ceiling would not have caught them. What overflows is line count,
and an entry title costs page space no word count can see, so the pass/fail has
to be asked of the rendered document.
"""
import pytest

import pdf_core


def _write(md_path, body="body text"):
    md_path.write_text(f"---\ntitle: x\n---\n{body}", encoding="utf-8")


@pytest.fixture
def pdf_dir(tmp_path, monkeypatch):
    """A throwaway PDF_DIR with the renderer stubbed out.

    The renderer is not what is under test here — the gate around it is — so it
    returns fixed bytes and the page count is dictated per test.
    """
    d = tmp_path / "pdfs"
    monkeypatch.setattr(pdf_core, "PDF_DIR", d)
    monkeypatch.setattr(pdf_core, "_PDF_VERSIONS_META", d / ".pdf_versions.json")
    monkeypatch.setattr(pdf_core, "_md_to_pdf_bytes", lambda md_path: b"%PDF-stub")
    return d


def _pages(monkeypatch, n):
    monkeypatch.setattr(pdf_core, "_pdf_page_count", lambda pdf_bytes: n)


def test_three_page_cv_is_refused_and_nothing_is_written(tmp_path, pdf_dir, monkeypatch):
    _pages(monkeypatch, 3)
    md_path = tmp_path / "TestCo_Role_CV.md"
    _write(md_path)

    with pytest.raises(pdf_core.PdfPageCountError) as exc:
        pdf_core._convert_pdf_versioned(md_path)
    assert "3 pages" in str(exc.value)

    # A refused document must not consume a version number, leave a file
    # behind, or be recorded as converted — otherwise the next run reuses it.
    assert not list(pdf_dir.glob("*.pdf"))
    assert pdf_core._load_pdf_meta() == {}


def test_two_page_cv_is_written(tmp_path, pdf_dir, monkeypatch):
    _pages(monkeypatch, 2)
    md_path = tmp_path / "TestCo_Role_CV.md"
    _write(md_path)

    pdf_path, version, is_new = pdf_core._convert_pdf_versioned(md_path)
    assert (version, is_new) == (1, True)
    assert pdf_path.exists()


def test_cover_letter_must_be_one_page(tmp_path, pdf_dir, monkeypatch):
    _pages(monkeypatch, 2)
    md_path = tmp_path / "TestCo_Role_CL.md"
    _write(md_path)

    with pytest.raises(pdf_core.PdfPageCountError):
        pdf_core._convert_pdf_versioned(md_path)


def test_one_page_cover_letter_is_written(tmp_path, pdf_dir, monkeypatch):
    _pages(monkeypatch, 1)
    md_path = tmp_path / "TestCo_Role_CL.md"
    _write(md_path)

    pdf_path, _version, is_new = pdf_core._convert_pdf_versioned(md_path)
    assert is_new and pdf_path.exists()


def test_document_with_no_declared_budget_is_not_blocked(tmp_path, pdf_dir, monkeypatch):
    """Only CVs and cover letters have a page budget; nothing else is refused."""
    _pages(monkeypatch, 7)
    md_path = tmp_path / "TestCo_Role_notes.md"
    _write(md_path)

    pdf_path, _version, is_new = pdf_core._convert_pdf_versioned(md_path)
    assert is_new and pdf_path.exists()


def test_reuse_path_refuses_an_over_budget_pdf_already_on_disk(tmp_path, pdf_dir, monkeypatch):
    """The gate runs on reuse too, not only when a version is minted.

    The three-page CVs on disk predate this check. Reuse is the path that would
    keep handing them back — and stamping them onto the report — in silence.
    """
    _pages(monkeypatch, 2)
    md_path = tmp_path / "TestCo_Role_CV.md"
    _write(md_path)
    pdf_core._convert_pdf_versioned(md_path)

    _pages(monkeypatch, 3)
    with pytest.raises(pdf_core.PdfPageCountError):
        pdf_core._convert_pdf_versioned(md_path)


def test_page_count_reads_a_real_weasyprint_pdf():
    """The counter must work on genuine renderer output.

    Not a formality: scanning the bytes for /Type /Page or /Count — the obvious
    dependency-free implementation — returns nothing at all on WeasyPrint's
    output, because it writes page objects into compressed object streams. That
    approach mismatched pdfinfo on 75 of the 75 PDFs on disk before this landed
    on poppler, so the read-back path is worth testing for real.
    """
    from weasyprint import HTML

    one = HTML(string="<p>page one</p>").write_pdf()
    assert pdf_core._pdf_page_count(one) == 1

    two = HTML(
        string='<p>page one</p><p style="break-before: page">page two</p>'
    ).write_pdf()
    assert pdf_core._pdf_page_count(two) == 2
