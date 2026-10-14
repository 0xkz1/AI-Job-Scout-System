"""Saving the Scraper tab's settings into config.yaml.

The tab builds its widgets from config.yaml once per browser session, and Save
used to write that whole in-memory copy back: a tab left open reverted every
edit made to the file since it was opened, settings it does not even show
included (the Edinburgh local-work entries added on 2026-10-13 were exposed to
this). Save now writes only what was changed on screen, onto the file as it is
at that moment.
"""
from pathlib import Path

import yaml


def save_settings(path: Path, loaded: dict, settings: dict) -> tuple[dict | None, list[str]]:
    """Write the settings changed since `loaded` onto the config file at `path`.

    `loaded` is the config the screen was built from. A setting still equal to
    its loaded value was not touched on screen, so the file keeps what it holds
    now. A setting changed both on screen and in the file to different values
    is a clash: nothing is written and the clashing keys come back, so the
    screen can ask for a reload instead of picking a winner.

    Returns (config as now on disk, []) or (None, clashing keys).
    """
    current = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    changed = {k: v for k, v in settings.items() if v != loaded.get(k)}
    clashes = sorted(k for k, v in changed.items() if current.get(k) not in (loaded.get(k), v))
    if clashes:
        return None, clashes
    # yaml.dump drops the file's comments, so do not rewrite it for nothing.
    if changed:
        current.update(changed)
        with open(path, "w") as f:
            yaml.dump(current, f, allow_unicode=True)
    return current, []
