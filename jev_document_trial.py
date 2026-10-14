"""Opt-in document selection shared by the normal and Hermes JIS entrypoints."""
from __future__ import annotations

import os


def enabled() -> bool:
    mode = os.environ.get("JIS_DOCUMENT_MODE", "legacy")
    if mode not in ("legacy", "jev"):
        raise ValueError("JIS_DOCUMENT_MODE must be legacy or jev")
    return mode == "jev"


def make_client():
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        from pathlib import Path
        from dotenv import dotenv_values
        for path in (Path(__file__).resolve().parent/".env",
                     Path("/media/kz003/atelier/taifunome/.env")):
            if path.is_file():
                key = dotenv_values(path).get("TYPESAFE_API_KEY")
                if key:
                    break
    if not key:
        return None
    from typesafe_sdk import RetryPolicy, TypeSafeClient
    from jev_project_selector import MODEL
    return TypeSafeClient(api_key=key, model=MODEL, timeout=20,
                          retry=RetryPolicy(max_retries=0))


def choose_projects(job: dict) -> dict:
    import cv_generator as cv
    from jev_project_selector import select_projects
    fallback = cv._ids_from_experience_body(cv._get_static_experience(job["role_type"]))
    client = make_client()
    try:
        return select_projects(job, cv.PROJECTS, fallback, client)
    finally:
        if client is not None:
            client.close()


def choose_bridge(job: dict, canonical: str) -> tuple[dict, list[dict], dict]:
    import cover_letter_generator as cl
    import cv_generator as cv
    from jev_letter_bridge_selector import load_bank, select_bridge
    from letter_evidence_selector import choose_letter_evidence
    resolved, evidence = choose_letter_evidence(job)
    if resolved["evidence_scope"] != "covered":
        raise RuntimeError("prepared letter withheld: " + resolved["letter_role_reason"])
    evidence = cl._fit_evidence_to_budget(job["title"], job["company"], canonical, evidence)
    locked = {(f["source_id"], f["fact"]) for f in cl._load_letter_facts()
              if resolved["role_type"] in f["roles"]}
    if not evidence or any((f["source_id"], f["fact"]) not in locked for f in evidence):
        raise ValueError("Prepared evidence is not a role-eligible locked fact")
    prefix = cl._assemble_letter_body(job["title"], job["company"], canonical, evidence, "")
    client = make_client()
    try:
        selection = select_bridge(resolved, prefix, evidence, cv._ALL_ENTRIES, load_bank(), client)
    finally:
        if client is not None:
            client.close()
    selection.update(role_type=resolved["role_type"], letter_focus=resolved["letter_focus"],
                     fact_source_ids=[f["source_id"] for f in evidence])
    return resolved, evidence, selection
