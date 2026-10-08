"""Read the same application flags as Obsidian, without changing the records."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import yaml

from doc_paths import md_files


def _date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _checked_at(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _flag(value) -> bool:
    return str(value).lower() in {"true", "yes", "on"}


def load_history(output_dir: Path) -> tuple[list[dict], list[str]]:
    """Merge checked reports by exact URL; retain undated jobs in the totals.

    Expiry cache entries describe observations, not the site's closing date.
    A cached live/blocked result cannot date a later manual expired tick.
    """
    warnings = []
    vault = next((parent for parent in (output_dir, *output_dir.parents)
                  if (parent / ".obsidian").is_dir()), None)
    state_path = output_dir / "_expiry_checks.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("expiry state must be an object")
    except FileNotFoundError:
        state = {}
    except (OSError, ValueError):
        state = {}
        warnings.append("期限切れ確認の記録を読み込めませんでした。日付なしで集計しています。")

    jobs = {}
    for path in md_files(output_dir / "00_matches", recursive=True):
        try:
            text = path.read_text(encoding="utf-8")
            front = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
            if not front:
                continue
            # Most reports are unchecked. Avoid parsing their large frontmatter.
            if not re.search(r"^(?:applied|expired):\s*['\"]?(?:true|yes|on)['\"]?\s*$",
                             front[1], re.M | re.I):
                continue
            props = yaml.safe_load(front[1])
            if not isinstance(props, dict):
                continue
        except (OSError, UnicodeError, yaml.YAMLError):
            warnings.append(f"求人ノートを読み込めませんでした: {path.name}")
            continue

        applied, expired = _flag(props.get("applied")), _flag(props.get("expired"))
        if not applied and not expired:
            continue
        url = str(props.get("url") or "").strip()
        key = url or str(path)
        applied_date = _date(props.get("applied_at")) if applied else None
        if key not in jobs:
            jobs[key] = {
                "url": url,
                "company": str(props.get("company") or "会社名不明"),
                "title": str(props.get("title") or path.stem),
                "applied": False, "expired": False,
                "applied_date": None, "expired_checked_at": None,
                "report_paths": [],
                # Vault-relative links also work on synced Macs/phones, where
                # this server's absolute Linux path does not exist.
                "note_uri": "obsidian://open?" + urlencode(
                    {"vault": vault.name, "file": path.relative_to(vault).as_posix()}
                    if vault else {"path": str(path.resolve())}),
            }
        job = jobs[key]
        job["applied"] |= applied
        job["expired"] |= expired
        job["report_paths"].append(str(path))
        # Duplicate reports are one job. Preserve the earliest stored application
        # date rather than counting a regeneration as a second application.
        if applied_date and (job["applied_date"] is None or applied_date < job["applied_date"]):
            job["applied_date"] = applied_date

    for job in jobs.values():
        observed = state.get(job["url"], {})
        if job["expired"] and isinstance(observed, dict) and observed.get("verdict") == "gone":
            job["expired_checked_at"] = _checked_at(observed.get("checked_at"))
    return sorted(jobs.values(), key=lambda j: (j["company"], j["title"], j["url"])), warnings


def history_events(jobs: list[dict], timezone: str = "Asia/Tokyo") -> list[dict]:
    events = []
    tz = ZoneInfo(timezone)
    for job in jobs:
        if job["applied"] and job["applied_date"]:
            events.append({"kind": "applied", "date": job["applied_date"], "job": job})
        if job["expired"] and job["expired_checked_at"]:
            events.append({"kind": "expired", "date": job["expired_checked_at"].astimezone(tz).date(),
                           "job": job})
    return sorted(events, key=lambda e: (e["date"], e["kind"], e["job"]["company"], e["job"]["title"]))


def history_counts(jobs: list[dict], today: date) -> dict[str, int]:
    return {
        "applied": sum(j["applied"] for j in jobs),
        "this_month": sum(j["applied"] and j["applied_date"] is not None
                          and j["applied_date"].strftime("%Y-%m") == today.strftime("%Y-%m") for j in jobs),
        "expired": sum(j["expired"] for j in jobs),
        "applied_undated": sum(j["applied"] and j["applied_date"] is None for j in jobs),
        "expired_undated": sum(j["expired"] and j["expired_checked_at"] is None for j in jobs),
    }


def history_rows(jobs: list[dict], timezone: str = "Asia/Tokyo") -> list[dict]:
    tz = ZoneInfo(timezone)
    return [{
        "会社": j["company"], "職種": j["title"],
        "応募済み": j["applied"], "期限切れ": j["expired"],
        "応募日": j["applied_date"].isoformat() if j["applied_date"] else ("不明" if j["applied"] else "—"),
        "期限切れ確認日時": j["expired_checked_at"].astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
        if j["expired_checked_at"] else ("不明" if j["expired"] else "—"),
        "求人": j["url"] if j["url"].startswith(("http://", "https://")) else None,
        "求人ノート": j["note_uri"],
    } for j in jobs]
