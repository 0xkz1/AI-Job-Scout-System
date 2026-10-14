"""The Scraper tab's Save writes only what was changed on screen.

It used to write its whole in-memory copy of config.yaml, loaded when the tab
opened, so a tab left open reverted every edit made to the file since.
"""
import yaml

from config_save import save_settings

BASE = {"keywords": ["Designer"], "min_salary_gbp": 0, "local_job_roles": {}}


def _file(tmp_path, data):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_an_untouched_setting_keeps_the_newer_value_on_disk(tmp_path):
    newer = {**BASE, "keywords": ["Designer", "Warehouse Operative"],
             "local_job_roles": {"warehouse": ["Warehouse Operative"]}}
    path = _file(tmp_path, newer)

    saved, clashes = save_settings(path, BASE, {"keywords": ["Designer"], "min_salary_gbp": 25000})

    assert clashes == []
    on_disk = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert on_disk == saved
    assert on_disk["keywords"] == ["Designer", "Warehouse Operative"]
    assert on_disk["local_job_roles"] == {"warehouse": ["Warehouse Operative"]}
    assert on_disk["min_salary_gbp"] == 25000


def test_a_setting_changed_in_both_places_is_not_saved(tmp_path):
    path = _file(tmp_path, {**BASE, "keywords": ["Designer", "Kitchen Porter"]})
    before = path.read_bytes()

    saved, clashes = save_settings(path, BASE, {"keywords": ["Designer", "Removals"],
                                                "min_salary_gbp": 25000})

    assert saved is None
    assert clashes == ["keywords"]
    assert path.read_bytes() == before


def test_the_same_change_made_in_both_places_is_not_a_clash(tmp_path):
    path = _file(tmp_path, {**BASE, "keywords": ["Designer", "Kitchen Porter"]})

    saved, clashes = save_settings(path, BASE, {"keywords": ["Designer", "Kitchen Porter"]})

    assert clashes == []
    assert saved["keywords"] == ["Designer", "Kitchen Porter"]


def test_saving_with_nothing_changed_leaves_the_file_alone(tmp_path):
    # yaml.dump drops comments; a no-op Save must not cost the file its notes.
    path = tmp_path / "config.yaml"
    path.write_text("# why this keyword is here\nkeywords:\n- Designer\nmin_salary_gbp: 0\n",
                    encoding="utf-8")
    before = path.read_bytes()

    saved, clashes = save_settings(path, {"keywords": ["Designer"], "min_salary_gbp": 0},
                                   {"keywords": ["Designer"], "min_salary_gbp": 0})

    assert clashes == []
    assert saved["keywords"] == ["Designer"]
    assert path.read_bytes() == before
