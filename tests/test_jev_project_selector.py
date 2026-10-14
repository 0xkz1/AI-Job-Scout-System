"""Contract checks for offline fallback, response attribution, and original text."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jev_project_selector import MODEL, editorial_order, render_selected, select_projects

PROJECTS = [
    {"id": "web", "title": "Web", "role": "Studio", "period": "2026",
     "description": "An exact English source.\n• Unchanged.",
     "description_ja": "検証済みの日本語。", "type": "project"},
    {"id": "art", "title": "Art", "role": "Studio", "period": "2025",
     "description": "An art source.", "description_ja": "", "type": "project"},
    {"id": "employer", "title": "Employment", "description": "Must never be selected.",
     "type": "employment"},
]
JOB = {"title": "Web Designer", "description": "Build websites.", "role_type": "general"}


class Client:
    def __init__(self, answers=None, error=None, model=MODEL):
        self.answers, self.error, self.model = answers, error, model
        self.calls = []

    def system_one(self, **request):
        self.calls.append(request)
        if self.error:
            raise self.error
        value = {"model": self.model, "answers": self.answers,
                 "usage": {"input_tokens": 123, "output_tokens": 12}}
        return SimpleNamespace(model_dump=lambda **kw: value)


def answer(level):
    return {"type": "score", "score": level, "confidence": 1,
            "probabilities": {i: float(i == level) for i in range(4)}}


def test_offline_never_imports_sdk_or_calls_an_api():
    result = select_projects(JOB, PROJECTS, ["art", "web", "employer"])
    assert result["source"] == "static"
    assert result["selected_ids"] == ["art", "web"]
    assert result["elapsed_seconds"] == 0


def test_one_call_scores_only_eligible_ids_and_preserves_distribution():
    client = Client({"web": answer(3), "art": answer(0)})
    result = select_projects(JOB, PROJECTS, ["art", "web"], client)
    assert len(client.calls) == 1
    assert set(client.calls[0]["questions"]) == {"web", "art"}
    assert result["selected_ids"] == ["web", "art"]
    assert result["source"] == "jev"
    assert result["scores"]["web"]["probabilities"][3] == 1
    assert result["usage"]["input_tokens"] == 123


@pytest.mark.parametrize("answers", [
    {"web": answer(3)},  # missing ID
    {"web": answer(3), "art": answer(0), "invented": answer(3)},
    {"web": {**answer(3), "score": float("nan")}, "art": answer(0)},
    {"web": {**answer(3), "score": 1}, "art": answer(0)},  # inconsistent distribution
])
def test_invalid_results_restore_static_order(answers):
    result = select_projects(JOB, PROJECTS, ["art", "web"], Client(answers))
    assert result["source"] == "static"
    assert result["selected_ids"] == ["art", "web"]
    assert result["error_type"] == "ValueError"


def test_wrong_model_and_api_failure_are_visible_without_exception_text():
    for client in [Client({"web": answer(3), "art": answer(0)}, model="jev-latest"),
                   Client(error=RuntimeError("credential must not be persisted"))]:
        result = select_projects(JOB, PROJECTS, ["art", "web"], client)
        assert result["source"] == "static"
        assert "error_type" in result
        assert "credential" not in str(result)


def test_source_text_and_language_are_kept_verbatim():
    en = render_selected(PROJECTS, ["web", "art", "web"])
    assert en == ("**Web | Studio | 2026**\nAn exact English source.\n• Unchanged."
                  "\n\n**Art | Studio | 2025**\nAn art source.")
    assert render_selected(PROJECTS, ["web", "art"], "ja") == (
        "**Web | Studio | 2026**\n検証済みの日本語。")
    with pytest.raises(ValueError):
        render_selected(PROJECTS, ["invented"])
    with pytest.raises(ValueError):
        render_selected(PROJECTS, ["employer"])


def test_duplicate_sources_are_rejected_before_any_paid_call():
    client = Client()
    with pytest.raises(ValueError):
        select_projects(JOB, [PROJECTS[0], PROJECTS[0]], [], client)
    assert client.calls == []


def test_ties_keep_the_authored_fallback_order():
    result = select_projects(JOB, PROJECTS, ["art", "web"],
                             Client({"web": answer(2), "art": answer(2)}))
    assert result["selected_ids"] == ["art", "web"]


def test_real_api_rounding_does_not_discard_valid_scores():
    rounded = {"type": "score", "score": .23, "confidence": .8,
               "probabilities": {0: .8, 1: .18, 2: .02, 3: 0}}
    result = select_projects(JOB, PROJECTS, ["art", "web"],
                             Client({"web": rounded, "art": answer(0)}))
    assert result["source"] == "jev"
    assert result["scores"]["web"]["score"] == .23


def test_editorial_rules_are_recorded_separately_from_raw_scores():
    ids = ["feral-bestiary-plate-001", "web3-node-ops", "taifunome-research-platform"]
    scores = {pid: {"score": 2} for pid in ids}
    platform, notes = editorial_order(ids, scores, {"role_type": "platform_engineer"})
    assert platform[:2] == ["taifunome-research-platform", "web3-node-ops"]
    assert notes
    product, _ = editorial_order(ids, scores, {"role_type": "product_designer"})
    assert product[-1] == "feral-bestiary-plate-001"
    art, _ = editorial_order(ids, scores, {"role_type": "product_designer",
                                         "description": "Produce illustrations."})
    assert art.index("feral-bestiary-plate-001") < art.index("web3-node-ops")


@pytest.mark.parametrize("score", [.92, 0])
def test_low_score_cannot_silently_remove_the_authored_taifunome_priority(score):
    taifu = "taifunome-research-platform"
    ids = ["tool-a", "tool-b", "tool-c", "tool-d", taifu]
    scores = {pid: {"score": 3 if pid != taifu else score} for pid in ids}
    ordered, notes = editorial_order(ids, scores, {"role_type": "creative_technologist"})
    assert ordered[0] == taifu
    assert set(ordered) == set(ids)
    assert notes
    reviewed, _ = editorial_order(ids, scores, {"role_type": "creative_technologist"},
                                  taifunome_out_of_scope=True)
    assert reviewed == ids


def test_unreviewed_scope_strings_are_not_accepted_as_boolean_decisions():
    with pytest.raises(ValueError):
        editorial_order(["web"], {"web": {"score": 3}}, JOB,
                        taifunome_out_of_scope="false")


def test_adjacent_project_scores_carry_a_review_note_without_rejecting_the_job():
    result = select_projects(JOB, PROJECTS, ["web", "art"],
                             Client({"web": answer(1), "art": answer(0)}))
    assert result["source"] == "jev" and result["review_required"]
    assert any("direct-evidence" in note for note in result["review_notes"])
    assert result["selected_ids"] == ["web", "art"]
