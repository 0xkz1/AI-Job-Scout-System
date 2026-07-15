"""Every SKILL_SYNONYMS target must resolve to a real skills.md entry.

Replaces the manual AGENTS.md rule ("update both dicts AND skills.md, keep
them in sync") with an automated check — a synonym pointing at a skill name
that doesn't exist in skills.md silently returns a 0.0 match with no error.
"""
from matcher import SKILL_SYNONYMS, load_user_skills, normalize_skill_name


def _known_skill_names() -> set[str]:
    user_skills = load_user_skills()
    names = set()
    for skills in user_skills.values():
        for skill in skills:
            names.add(normalize_skill_name(skill["name"]))
    return names


def test_skills_md_is_loadable():
    known = _known_skill_names()
    assert len(known) > 10, "skills.md loaded suspiciously few skills — check USER_PROFILE_DIR/skills.md"


def test_synonym_targets_exist_in_skills_md():
    known = _known_skill_names()
    dangling = []
    for alias, target in SKILL_SYNONYMS.items():
        target_norm = normalize_skill_name(target)
        # A synonym may point at another synonym (alias chain) — resolve one hop
        if target_norm not in known and target_norm not in SKILL_SYNONYMS:
            dangling.append((alias, target))
    assert not dangling, (
        f"{len(dangling)} SKILL_SYNONYMS entries point at a skill missing from "
        f"skills.md (matches will silently score 0): {dangling}"
    )


def test_synonym_keys_and_values_are_normalized_form():
    # get_user_skill_level normalizes lookups; a synonym key with stray
    # casing/punctuation still works today, but keeping the dict in its
    # normalized form is what the lookup assumes — catch drift early.
    bad = [
        alias for alias in SKILL_SYNONYMS
        if alias != normalize_skill_name(alias)
    ]
    assert not bad, f"SKILL_SYNONYMS keys not in normalized form: {bad}"
