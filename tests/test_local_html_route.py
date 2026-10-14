"""The saved-HTML route must actually be reachable.

The WebUI has told the user for months that a blocked Indeed URL can be
rescued by saving the page from a browser into 00_saved/local_html/. On
2026-09-11 that instruction was found to be false in four independent ways at
once: the scraper globbed 00_saved/*.html instead, it imported a package that
is not in requirements.txt and not installed, it POSTed straight to
localhost:11434, and nothing in the chain ever ran it. A user following the
instruction exactly would have seen no error and no job.

These tests pin the route open, not the implementation.
"""
import ast
import json
import pathlib
import re

import pytest

import scraper_local_html as lh

ROOT = pathlib.Path(__file__).resolve().parent.parent


# --- where it looks -------------------------------------------------------

def test_the_webui_and_the_scraper_name_the_same_directory():
    """The whole fault in one assertion. The WebUI told the user to save into
    00_saved/local_html/ and the scraper globbed 00_saved/*.html, and nothing
    held the two together, so the instruction was false for months without
    anything failing.

    Skipped when the WebUI names no such directory at all: the caption may not
    have landed yet, and a missing instruction is a different bug from a
    contradictory one.
    """
    documented = (ROOT / "app.py").read_text(encoding="utf-8")
    named = re.findall(r"00_saved/([A-Za-z0-9_]+)/`", documented)
    if "local_html" not in named:
        pytest.skip("app.py does not name a saved-HTML directory")
    assert pathlib.Path(lh.LOCAL_HTML_DIR).name == "local_html"


def test_it_reads_the_directory_it_advertises(tmp_path, monkeypatch):
    local = tmp_path / "local_html"
    (local / "indeed").mkdir(parents=True)
    (local / "a.html").write_text("<html><body>one</body></html>")
    # Nested, because saving a page per site or per day is the obvious habit.
    (local / "indeed" / "b.html").write_text("<html><body>two</body></html>")
    monkeypatch.setattr(lh, "LOCAL_HTML_DIR", str(local))
    monkeypatch.setattr(lh, "SAVED_DIR", str(tmp_path))

    found = {pathlib.Path(f).name for f in lh.html_files()}
    assert found == {"a.html", "b.html"}


def test_the_assets_directory_of_a_complete_save_is_skipped(tmp_path, monkeypatch):
    """"Web Page, complete" writes every frame beside the page in a _files/
    directory. Extracting those would spend a model call per iframe."""
    local = tmp_path / "local_html"
    (local / "job_files").mkdir(parents=True)
    (local / "job.html").write_text("<html><body>posting</body></html>")
    (local / "job_files" / "frame.html").write_text("<html><body>advert</body></html>")
    monkeypatch.setattr(lh, "LOCAL_HTML_DIR", str(local))

    assert [pathlib.Path(f).name for f in lh.html_files()] == ["job.html"]


# --- the URL, so the row can be joined ------------------------------------

@pytest.mark.parametrize("html, expected", [
    # Chrome and Firefox both stamp this in as the first line of a saved file.
    ('<!-- saved from url=(0052)https://uk.indeed.com/viewjob?jk=abc123 -->',
     'https://uk.indeed.com/viewjob?jk=abc123'),
    ('<link rel="canonical" href="https://uk.indeed.com/viewjob?jk=abc123"/>',
     'https://uk.indeed.com/viewjob?jk=abc123'),
    ('<link href="https://uk.indeed.com/viewjob?jk=abc123" rel="canonical"/>',
     'https://uk.indeed.com/viewjob?jk=abc123'),
    ('<meta property="og:url" content="https://uk.indeed.com/viewjob?jk=abc123">',
     'https://uk.indeed.com/viewjob?jk=abc123'),
])
def test_the_posting_url_is_recovered_from_the_saved_file(html, expected):
    """It used to write url: "" on every job. (company, title) is not a unique
    key — run.py merges on the URL, so without one the row cannot be joined to
    the posting it came from or deduped against a re-save."""
    assert lh.source_url(html) == expected


def test_a_file_with_no_url_does_not_invent_one():
    assert lh.source_url("<html><body>no metadata here</body></html>") == ""


# --- text extraction ------------------------------------------------------

def test_script_bodies_do_not_reach_the_extractor():
    """A saved Indeed page carries tens of kilobytes of inline JavaScript. Left
    in, it fills the extractor's 15,000-character window before the posting
    starts."""
    html = ("<html><body><script>var config={a:1};</script>"
            "<style>.x{color:red}</style>"
            "<h1>Product Designer</h1><p>Edinburgh</p></body></html>")
    text = lh.page_text(html)
    assert "Product Designer" in text and "Edinburgh" in text
    assert "var config" not in text and "color:red" not in text


# --- the faults that made it unreachable ----------------------------------

def test_it_does_not_import_a_package_the_project_does_not_declare():
    """It imported html2text, which is in neither requirements.txt nor the
    venv, so the module died at import before reading a single file."""
    tree = ast.parse((ROOT / "scraper_local_html.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    third_party = imported - set(__import__("sys").stdlib_module_names)
    local = {p.stem for p in ROOT.glob("*.py")}
    for name in sorted(third_party - local):
        __import__(name)  # installed at all?
        assert name.lower() in requirements or name.lower() in {"bs4"}, (
            f"{name} is imported but not declared in requirements.txt"
        )


def test_extraction_goes_through_the_shared_provider_chain():
    """Same fault, same fix as scraper_url_list: a hardcoded POST to Ollama
    ignores FALLBACK_PROVIDERS and key_quarantine."""
    tree = ast.parse((ROOT / "scraper_local_html.py").read_text(encoding="utf-8"))
    # Docstrings excluded: the module's own explains why the endpoint is gone,
    # and naming it there is the point. Only literals the code could use.
    docstrings = {id(ast.get_docstring(n, clean=False))
                  for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef,
                                    ast.AsyncFunctionDef, ast.ClassDef))}
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n.value) not in docstrings]
    offenders = [v for v in literals if "11434" in v or "/api/generate" in v]
    assert not offenders, f"a hardcoded Ollama endpoint is back ({offenders})"

    import scraper_url_list
    assert lh.extract_job_from_text is scraper_url_list.extract_job_from_text, (
        "the saved-HTML route has grown its own extractor again; it must share "
        "the one that goes through call_llm"
    )


def test_the_chain_actually_runs_it():
    """Nothing invoked this module. run.py ingests local_html_jobs.json if it
    happens to exist, which it never did, because no stage wrote it."""
    chain = (ROOT / "run_saved_chain.py").read_text(encoding="utf-8")
    assert "scraper_local_html.py" in chain, (
        "run_saved_chain no longer runs the saved-HTML stage — the WebUI's "
        "workaround for a blocked Indeed URL is dead again"
    )


# --- end to end -----------------------------------------------------------

def _setup(tmp_path, monkeypatch):
    local = tmp_path / "local_html"
    local.mkdir(parents=True)
    monkeypatch.setattr(lh, "LOCAL_HTML_DIR", str(local))
    monkeypatch.setattr(lh, "SAVED_DIR", str(tmp_path))
    monkeypatch.setattr(lh, "OUTPUT_FILE", str(tmp_path / "local_html_jobs.json"))
    return local


def test_a_saved_posting_becomes_a_staged_job(tmp_path, monkeypatch):
    local = _setup(tmp_path, monkeypatch)
    (local / "job.html").write_text(
        '<link rel="canonical" href="https://uk.indeed.com/viewjob?jk=abc123"/>'
        "<html><body><h1>Product Designer</h1>"
        "<p>Edinburgh. Own the design system.</p></body></html>",
        encoding="utf-8")
    monkeypatch.setattr(lh, "extract_job_from_text", lambda t: {
        "title": "Product Designer", "company": "Acme",
        "location": "Edinburgh", "description": "Own the design system."})

    lh.main()

    jobs = json.loads(pathlib.Path(lh.OUTPUT_FILE).read_text(encoding="utf-8"))
    assert len(jobs) == 1
    assert jobs[0]["url"] == "https://uk.indeed.com/viewjob?jk=abc123"
    # Routed by its real URL, not parked under a "local" pseudo-source, so it
    # merges with the same posting reached any other way.
    assert jobs[0]["source"] == "indeed"
    assert jobs[0]["saved_html"] == "local_html/job.html"


def test_a_second_run_does_not_pay_to_extract_the_same_page_twice(tmp_path, monkeypatch):
    local = _setup(tmp_path, monkeypatch)
    (local / "job.html").write_text(
        '<link rel="canonical" href="https://uk.indeed.com/viewjob?jk=abc123"/>'
        "<html><body><h1>Product Designer</h1><p>Edinburgh.</p></body></html>",
        encoding="utf-8")

    calls = []

    def _extract(text):
        calls.append(text)
        return {"title": "Product Designer", "company": "Acme",
                "location": "Edinburgh", "description": "Own the design system."}

    monkeypatch.setattr(lh, "extract_job_from_text", _extract)
    lh.main()
    lh.main()

    assert len(calls) == 1, "the second run re-extracted a page already staged"
    jobs = json.loads(pathlib.Path(lh.OUTPUT_FILE).read_text(encoding="utf-8"))
    assert len(jobs) == 1


def test_a_saved_sign_in_wall_is_refused_before_any_model_call(tmp_path, monkeypatch):
    """Saving the page while signed out saves the wall. Extracting it would
    spend a call to produce the empty object the caller then rejects."""
    local = _setup(tmp_path, monkeypatch)
    (local / "wall.html").write_text(
        "<html><body><p>Ready to take the next step?</p>"
        "<p>Create an account or sign in.</p></body></html>",
        encoding="utf-8")

    def _boom(text):
        raise AssertionError("a model call was made on an interstitial")

    monkeypatch.setattr(lh, "extract_job_from_text", _boom)
    lh.main()

    assert not pathlib.Path(lh.OUTPUT_FILE).exists()
