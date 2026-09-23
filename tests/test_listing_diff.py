"""One test per compare mode, plus the classification that the whole feature
hangs on: does this edit cost a Fab review, or not?
"""

from __future__ import annotations

import copy

import pytest

from fabpublisher.listing import schema
from fabpublisher.listing.diffing import (
    CHANGED,
    CLEAN,
    NEW,
    PENDING,
    diff_listing,
    leaf_paths,
)

BASE = {
    "schema_version": 1,
    "plugin_id": "Demo",
    "title": "My Save System",
    "product_type": "Tools & Plugins",
    "category": "Gameplay Features",
    "license": {
        "type": "Standard",
        "price_personal": 39.99,
        "price_professional": 79.99,
        "currency": "USD",
    },
    "description": {"text": "line one\nline two", "chars": 17, "blocks": ["what"]},
    "tags": ["load", "save"],
    "technical": {
        "engine_versions": ["5.8"],
        "dev_platforms": ["Windows"],
        "target_platforms": ["Win64"],
        "distribution": "Plugin",
    },
    "stats": {"blueprints": 0, "cpp_classes": 3},
    "media": {
        "thumbnail": {
            "source": "a.png",
            "bytes": 900_000,
            "width": 1920,
            "height": 1080,
            "sha256": "aaaa1111",
        },
        "gallery": [
            {"index": 1, "source": "g1.png", "bytes": 1, "width": 1, "height": 1, "sha256": "b"},
            {"index": 2, "source": "g2.png", "bytes": 1, "width": 1, "height": 1, "sha256": "c"},
        ],
        "missing": [],
        "gallery_bytes": 2,
        "gallery_count": 2,
    },
    "product_file": None,
    "forum_post": {"has": False, "url": ""},
    "declarations": {
        "edc_forum_post": False,
        "mature": False,
        "no_ai": True,
        "generative_ai": False,
        "promotional": False,
    },
    "faq": [],
    "changelog": [],
    "fab": {"listing_url": "u", "product_id": "p", "is_live": True},
    "plugin_version": "1.0",
}


def changed(mutate, **kwargs):
    nxt = copy.deepcopy(BASE)
    mutate(nxt)
    return diff_listing(BASE, nxt, is_live=True, **kwargs)


def only(report):
    assert len(report.changes) == 1, [c.path for c in report.changes]
    return report.changes[0]


# ------------------------------------------------------------------- statuses
def test_no_snapshot_is_new():
    assert diff_listing(None, BASE).status == NEW


def test_snapshot_but_not_live_is_pending():
    """Recorded but not yet on Fab. Information, not an error."""
    assert diff_listing(BASE, BASE, is_live=False).status == PENDING


def test_identical_live_listing_is_clean():
    assert diff_listing(BASE, copy.deepcopy(BASE), is_live=True).status == CLEAN


def test_a_change_on_a_live_listing_is_changed():
    assert changed(lambda o: o["tags"].append("new")).status == CHANGED


# --------------------------------------------------------------- compare modes
def test_scalar_reports_before_and_after():
    change = only(changed(lambda o: o.__setitem__("title", "My Save & Load")))

    assert change.compare == "scalar"
    assert "My Save System" in change.summary
    assert "My Save & Load" in change.summary


def test_set_reports_additions_and_removals():
    def mutate(o):
        o["tags"] = ["save", "persistence"]

    change = only(changed(mutate))

    assert change.compare == "set"
    assert "+persistence" in change.summary
    assert "-load" in change.summary


def test_text_reports_line_counts_and_samples_without_dumping_the_body():
    def mutate(o):
        o["description"]["text"] = "line one CHANGED\nline two\nline three"

    change = only(changed(mutate))

    assert change.compare == "text"
    assert change.summary == "+2 / -1 lines"
    assert len(change.detail) <= 3


def test_a_huge_text_change_stays_short():
    """A report you have to scroll is a report you stop reading."""

    def mutate(o):
        o["description"]["text"] = "\n".join(f"brand new line {i}" for i in range(400))

    change = only(changed(mutate))

    assert len(change.summary) + sum(len(d) for d in change.detail) < 400


def test_digest_reports_the_hash_and_size_move():
    def mutate(o):
        o["media"]["thumbnail"].update({"sha256": "ffff9999", "bytes": 950_000})

    change = only(changed(mutate))

    assert change.compare == "digest"
    assert "aaaa1111" in change.summary and "ffff9999" in change.summary
    assert "KB" in change.summary


def test_list_reports_an_addition_with_its_position():
    def mutate(o):
        o["media"]["gallery"].insert(
            1,
            {"index": 2, "source": "g3.png", "bytes": 1, "width": 1, "height": 1, "sha256": "d"},
        )

    change = only(changed(mutate))

    assert change.summary == "2 -> 3 items"
    assert any("g3.png" in d and "#2" in d for d in change.detail)


def test_reordering_a_gallery_is_a_move_not_an_add_and_a_remove():
    change = only(changed(lambda o: o["media"]["gallery"].reverse()))

    assert "reordered" in change.summary
    assert all(not d.startswith("+") and not d.startswith("-") for d in change.detail)
    assert any("moved" in d for d in change.detail)


# ------------------------------------------------------------- classification
def test_tags_are_instant_and_do_not_trigger_review():
    report = changed(lambda o: o["tags"].append("persistence"))

    assert only(report).review is False
    assert report.triggers_review is False
    assert len(report.instant_changes) == 1


def test_description_triggers_review():
    report = changed(lambda o: o["description"].__setitem__("text", "totally new"))

    assert only(report).review is True
    assert report.triggers_review is True


@pytest.mark.parametrize(
    "path,mutate,review",
    [
        ("title", lambda o: o.__setitem__("title", "Other"), True),
        ("media.thumbnail", lambda o: o["media"]["thumbnail"].__setitem__("sha256", "z"), True),
        ("technical.engine_versions", lambda o: o["technical"].__setitem__("engine_versions", ["5.9"]), True),
        ("category", lambda o: o.__setitem__("category", "Physics"), False),
        ("license.price_personal", lambda o: o["license"].__setitem__("price_personal", 34.99), False),
        ("technical.target_platforms", lambda o: o["technical"].__setitem__("target_platforms", ["Mac"]), False),
        ("declarations.mature", lambda o: o["declarations"].__setitem__("mature", True), False),
    ],
)
def test_each_field_lands_in_the_class_fab_documents(path, mutate, review):
    change = only(changed(mutate))

    assert change.path == path
    assert change.review is review


def test_an_unspecified_field_is_unclassified_and_counted_as_review():
    """Fail-safe. Guessing "probably instant" is the expensive mistake."""

    def mutate(o):
        o["some_new_field"] = "surprise"

    change = only(changed(mutate))

    assert change.unclassified is True
    assert change.review is True
    assert changed(mutate).triggers_review is True


def test_derived_fields_never_report_a_change_on_their_own():
    def mutate(o):
        o["description"]["chars"] = 9999
        o["media"]["gallery_count"] = 99
        o["fab"]["listing_url"] = "somewhere else"
        o["plugin_version"] = "2.0"

    assert changed(mutate).changes == ()


# ----------------------------------------------------------- switchable specs
@pytest.mark.parametrize("field_name", ["faq", "changelog"])
def test_undocumented_fields_default_to_review_and_can_be_flipped(field_name):
    def mutate(o):
        o[field_name] = [{"version": "2.0", "q": "New?", "a": "Yes", "notes": ["x"]}]

    assert only(changed(mutate)).review is True

    relaxed = schema.build_specs(faq_review=False, changelog_review=False)
    assert only(changed(mutate, specs=relaxed)).review is False


def test_leaf_paths_stops_at_a_specified_subtree():
    """media.thumbnail is one digest, not four separate scalars."""
    paths = leaf_paths(BASE, schema.SPECS)

    assert "media.thumbnail" in paths
    assert "media.thumbnail.sha256" not in paths
    assert "description.chars" not in paths, "ignored paths must be dropped"
