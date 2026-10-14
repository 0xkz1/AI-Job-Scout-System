"""Regression for the bare-name PDF getting silently overwritten by later versions.

_version_filename() documents v1 as living at the bare stem.pdf name
("backward compatible"), and _pdf_versions() treats that file as the
permanent version-1 slot. But _convert_pdf_versioned() used to also copy
every later version's bytes onto that same bare-name file — both when
minting a new version and when reusing an unchanged one — so stem.pdf
silently became a mirror of "whatever is latest" instead of staying frozen
as v1. Nothing else in the codebase reads the bare-name file expecting
"latest" (checked email_outreach.py, cv_generator.py, every other PDF_DIR
use), so that mirroring served no purpose except destroying v1's history.
"""
import re

import pdf_core


def _write_cv(md_path, body):
    md_path.write_text(f"---\ntitle: x\n---\n{body}", encoding="utf-8")


def test_bare_name_pdf_is_frozen_once_a_new_version_exists(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "pdfs"
    monkeypatch.setattr(pdf_core, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(pdf_core, "_PDF_VERSIONS_META", pdf_dir / ".pdf_versions.json")
    monkeypatch.setattr(pdf_core, "_md_to_pdf_bytes", lambda md_path: md_path.read_bytes())
    # The renderer above hands back markdown, not a PDF, so the page-count gate
    # in _convert_pdf_versioned has nothing real to read. Versioning is what is
    # under test here; the budget has its own tests.
    monkeypatch.setattr(pdf_core, "_pdf_page_count", lambda pdf_bytes: 2)

    md_path = tmp_path / "TestCo_Role_CV.md"
    bare = pdf_dir / f"{pdf_core.APPLICANT_NAME_PREFIX}_{md_path.stem}.pdf"

    _write_cv(md_path, "version one content")
    p1, v1, is_new1 = pdf_core._convert_pdf_versioned(md_path)
    assert (v1, is_new1) == (1, True)
    assert p1 == bare
    v1_bytes = bare.read_bytes()

    _write_cv(md_path, "version two content, changed")
    p2, v2, is_new2 = pdf_core._convert_pdf_versioned(md_path)
    assert (v2, is_new2) == (2, True)
    assert p2 != bare
    assert bare.read_bytes() == v1_bytes, "v1 must stay frozen once v2 is minted"

    _write_cv(md_path, "version three content, changed again")
    p3, v3, is_new3 = pdf_core._convert_pdf_versioned(md_path)
    assert (v3, is_new3) == (3, True)
    assert bare.read_bytes() == v1_bytes, "v1 must still be frozen after a second new version"

    # Reusing the unchanged v3 source must not touch the bare v1 file either.
    p3b, v3b, is_new3b = pdf_core._convert_pdf_versioned(md_path)
    assert (p3b, v3b, is_new3b) == (p3, 3, False)
    assert bare.read_bytes() == v1_bytes
