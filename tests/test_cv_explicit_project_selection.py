"""Explicit, grounded selection must survive the full CV assembly path."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cv_generator as cv


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_explicit_projects_bypass_model_and_page_filling_additions(monkeypatch, lang):
    def forbidden(*args, **kwargs):
        raise AssertionError("Explicit selection must not call the model or add another write-up.")

    projects = [{"id": f"preview-{i}", "title": f"Preview {i}", "role": "Independent",
                 "period": "2026", "type": "project", "skills": [],
                 "description": f"• Exact evidence {i}.", "description_ja": f"• 検証済み実績{i}。"}
                for i in range(5)]
    monkeypatch.setattr(cv, "PROJECTS", projects)
    monkeypatch.setattr(cv, "_generate_experience_ollama", forbidden)
    monkeypatch.setattr(cv, "_pad_experience_body", forbidden)
    selected = ["preview-3", "preview-1", "preview-4"]
    draft = cv.generate_cv(role_type="general", job_title="Preview role", company="Preview",
                           job_description="Do the work.", lang=lang,
                           selected_project_ids=selected)
    assert cv._ids_from_experience_body(draft) == selected
    for pid in selected:
        p = next(p for p in projects if p["id"] == pid)
        assert p["description_ja" if lang == "ja" else "description"] in draft


@pytest.mark.parametrize("ids", [[], ["missing"], ["valid", "valid"], ["employer"],
                                   ["valid", "second", "third", "fourth", "fifth"]])
def test_invalid_explicit_ids_are_rejected_before_generation(monkeypatch, ids):
    monkeypatch.setattr(cv, "PROJECTS", [
        {"id": pid, "type": "project"} for pid in ("valid", "second", "third", "fourth", "fifth")
    ] + [{"id": "employer", "type": "employment"}])
    with pytest.raises(ValueError):
        cv.generate_cv(selected_project_ids=ids)
