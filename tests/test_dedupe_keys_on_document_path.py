"""selection._dedupe must key on the document path, not on (company, title).

The two are not the same key, and the gap between them is silent data loss.
make_safe_name truncates the title at 50 characters, so two postings whose titles
differ only past that point are distinct to a (company, title) key and identical
to the filesystem — both survive selection, both are handed to the generator, and
both write the same file. Whichever runs last wins, while selection ranked by the
other.

Found 2026-09-01 on two real LinkedIn postings: Aquent's "UIデザイナー テクノロジー
やAIを活用した…[AQ-14798]" and the same title ending "[AQ-15555]". Different jobs,
different URLs, composites 0.69 and 0.61, both inside the generation set.

Japanese titles reach the truncation first because the boards write the whole
pitch into the title field, but nothing about this is Japanese-specific — any two
long titles sharing a 50-character prefix collide the same way.
"""
import pytest

from matcher import make_safe_name
from selection import _dedupe

LONG_JA = ("UIデザイナー テクノロジーやAIを活用した次世代型の資産運用サービスを提供する"
           "オンライン証券会社／自社サービスのUI/UX設計から素材制作などデザイン業務")


def _job(title, url, description):
    return {"company": "Aquent", "title": title, "url": url, "description": description}


def test_titles_sharing_a_truncated_prefix_collapse_to_one():
    a = _job(f"{LONG_JA} [AQ-14798]", "https://example.test/1", "A real description. " * 30)
    b = _job(f"{LONG_JA} [AQ-15555]", "https://example.test/2", "A real description. " * 40)
    assert make_safe_name(a["company"], a["title"]) == make_safe_name(b["company"], b["title"])
    assert a["title"] != b["title"]

    kept = _dedupe([a, b])
    assert len(kept) == 1
    # The fuller description survives — the same rule the function already used.
    assert kept[0]["url"] == "https://example.test/2"


def test_distinct_document_paths_are_all_kept():
    """The fix must not collapse postings that would write different files."""
    jobs = [
        _job("Web Designer", "https://example.test/1", "desc " * 60),
        _job("Web Developer", "https://example.test/2", "desc " * 60),
        {"company": "Other Co", "title": "Web Designer", "url": "https://example.test/3",
         "description": "desc " * 60},
    ]
    assert len(_dedupe(jobs)) == 3


def test_the_live_corpus_writes_each_path_once():
    """The property the invariant checks, asserted over the real selection.

    check_one_entry_per_document_path reports this against the stored DB; this
    asserts it against a live _dedupe, so a regression is caught before it reaches
    a generation run.
    """
    from selection import select_top

    try:
        selected = select_top("generation")
    except Exception:  # noqa: BLE001 - no live DB in a clean checkout
        pytest.skip("no live DB")
    if not selected:
        pytest.skip("empty selection")
    paths = [make_safe_name(j.get("company", ""), j.get("title", "")) for j in selected]
    duplicates = {p for p in paths if paths.count(p) > 1}
    assert not duplicates, f"{len(duplicates)} document paths written twice: {list(duplicates)[:3]}"
