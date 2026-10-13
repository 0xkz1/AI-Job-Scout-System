"""The real generation entrypoints use trial selection and keep legacy mode."""
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cover_letter_generator as cl
import cv_generator as cv
import jev_document_trial as trial

DESC = "Build interactive prototypes and test user feedback on accessible digital experiences. " * 6


def test_mode_is_explicit_and_invalid_modes_fail(monkeypatch):
    monkeypatch.delenv("JIS_DOCUMENT_MODE", raising=False)
    assert not trial.enabled()
    monkeypatch.setenv("JIS_DOCUMENT_MODE", "mistyped")
    with pytest.raises(ValueError):
        trial.enabled()


def test_trial_cv_uses_literal_sources_and_never_calls_generative_selector(monkeypatch):
    monkeypatch.setenv("JIS_DOCUMENT_MODE", "jev")
    monkeypatch.setattr(trial, "make_client", lambda: None)
    monkeypatch.setattr(cv, "_generate_experience_ollama", lambda *a: pytest.fail("legacy CV call"))
    text = cv.generate_cv("creative_technologist", "Creative Technologist", "Example", DESC)
    fm = yaml.safe_load(text.split("---",2)[1])
    assert fm["review_required"] and fm["jev_cv_selection"]["source"] == "static"
    assert all(pid in {p["id"] for p in cv.PROJECTS} for pid in fm["jev_cv_selection"]["selected_ids"])


def test_trial_cl_records_hold_and_preserves_author_text(monkeypatch,tmp_path):
    monkeypatch.setenv("JIS_DOCUMENT_MODE", "jev")
    monkeypatch.setattr(trial, "make_client", lambda: None)
    monkeypatch.setattr(cl, "_build_context_bridge", lambda *a: pytest.fail("legacy CL call"))
    path = Path(cl.save_cover_letter("Creative Technologist", "Example", "London", DESC,
                                    str(tmp_path), match_filename="report", cv_filename="cv"))
    text=path.read_text();fm=yaml.safe_load(text.split("---",2)[1])
    assert fm["review_required"] and fm["needs_new_candidate"]
    assert fm["opening_source"] == "assembled-jev-offline"
    assert cl._load_canonical_narrative() in text
    assert fm["jev_bridge_selection"]["status"] == "offline"


def test_unsupported_trial_cl_does_not_leave_a_letter(monkeypatch,tmp_path):
    monkeypatch.setenv("JIS_DOCUMENT_MODE", "jev")
    monkeypatch.setattr(trial, "make_client", lambda: pytest.fail("scope must precede API"))
    with pytest.raises(RuntimeError,match="withheld"):
        cl.save_cover_letter("Lifeguard", "Example", "London", DESC,str(tmp_path))
    assert not list(tmp_path.glob("*.md"))


def test_legacy_entrypoint_keeps_existing_bridge_route(monkeypatch):
    monkeypatch.setenv("JIS_DOCUMENT_MODE", "legacy")
    monkeypatch.setattr(trial, "make_client", lambda: pytest.fail("legacy must not call Jev"))
    monkeypatch.setattr(cl, "_build_context_bridge",lambda *a:(cl._STATIC_BRIDGE.format(company="Example"),"static"))
    text,source=cl.generate_cover_letter("Creative Technologist","Example","London",DESC)
    assert source == "assembled-static" and "I am writing to apply" in text


@pytest.mark.parametrize("kind",["facts","canonical"])
def test_parallel_first_load_never_publishes_temporary_empty_assets(monkeypatch,tmp_path,kind):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    (tmp_path/"canonical_narrative_v1.md").write_text("---\nversion: test\n---\n## Narrative\nMy authored identity.\n")
    (tmp_path/"letter_facts_v1.md").write_text("---\nfacts:\n  - id: project\n    fact: I built a project.\n    roles: [general]\n---\n")
    monkeypatch.setattr(cl,"_cover_letter_dir",lambda:tmp_path)
    monkeypatch.setattr(cl,"_canonical_narrative_cache",None)
    monkeypatch.setattr(cl,"_letter_facts_cache",None)
    barrier=threading.Barrier(2)
    read=Path.read_text
    def synchronized_read(path,*a,**kw):
        barrier.wait(timeout=2)
        return read(path,*a,**kw)
    monkeypatch.setattr(Path,"read_text",synchronized_read)
    load=cl._load_letter_facts if kind=="facts" else cl._load_canonical_narrative
    with ThreadPoolExecutor(max_workers=2) as pool:
        values=list(pool.map(lambda _:load(),range(2)))
    assert all(values) and values[0]==values[1]
