"""One case per validation rule.

Every assertion checks the `key` as well as the level, because a message that
does not name the field to edit sends you hunting.
"""

from __future__ import annotations

import copy

import pytest

from fabpublisher.listing import fabrules
from fabpublisher.listing.validate import check_listing, has_errors

from .test_listing_diff import BASE

GOOD = copy.deepcopy(BASE)
GOOD["description"]["text"] = (
    "What it is. " * 40 + "\n\nHow to use it.\n\nTechnical details and prerequisites."
)
GOOD["description"]["blocks"] = ["what", "how", "technical"]
GOOD["tags"] = ["save", "load", "persistence", "modular", "blueprint"]
GOOD["product_file"] = {
    "name": "Demo.zip",
    "bytes": 1,
    "unzipped_bytes": 2,
    "sha256": "x",
    "has_uplugin": True,
    "has_source_build_cs": True,
    "has_content": True,
    "has_config": True,
    "source_modules": ["Demo"],
}


def check(mutate=None, **kwargs):
    listing = copy.deepcopy(GOOD)
    if mutate:
        mutate(listing)
    return check_listing(listing, **kwargs)


def keys(issues, level=None):
    return {i.key for i in issues if level is None or i.level == level}


def message_for(issues, key):
    return next(i.message for i in issues if i.key == key)


def test_a_complete_listing_passes():
    assert check() == []


# --------------------------------------------------------------- typo guard
def test_unknown_authored_key_is_a_hard_error():
    """A misspelled key that silently does nothing is the worst outcome."""
    issues = check(unknown_keys=["tagz"])

    assert "tagz" in keys(issues, "error")
    assert has_errors(issues)


def test_a_stray_brace_outside_media_is_an_error():
    assert "title" in keys(check(stray_braces=["title"]), "error")


def test_an_unreadable_listing_file_short_circuits_everything():
    issues = check(source_error="Demo.json is not valid JSON: line 3")

    assert len(issues) == 1
    assert issues[0].level == "error"


# --------------------------------------------------------------------- title
def test_missing_title_is_an_error():
    assert "title" in keys(check(lambda o: o.__setitem__("title", "")), "error")


def test_title_over_the_hard_limit_is_an_error():
    issues = check(lambda o: o.__setitem__("title", "x" * (fabrules.TITLE_MAX + 1)))

    assert "title" in keys(issues, "error")
    assert str(fabrules.TITLE_MAX) in message_for(issues, "title")


def test_title_over_the_recommended_length_only_warns():
    issues = check(lambda o: o.__setitem__("title", "x" * 40))

    assert keys(issues, "warning") == {"title"}
    assert not has_errors(issues)


def test_camel_case_title_warns_that_the_id_leaked_through():
    issues = check(lambda o: o.__setitem__("title", "MySaveSystem"))

    assert "camelCase" in message_for(issues, "title")


# --------------------------------------------------------------- description
def test_empty_description_is_an_error():
    assert "description" in keys(
        check(lambda o: o["description"].__setitem__("text", "")), "error"
    )


def test_thin_description_warns():
    issues = check(lambda o: o["description"].__setitem__("text", "Short."))

    assert any(i.key == "description" and i.level == "warning" for i in issues)


def test_a_missing_content_area_warns_and_names_the_block():
    issues = check(lambda o: o["description"].__setitem__("blocks", ["what"]))

    assert "description.how" in keys(issues, "warning")


@pytest.mark.parametrize(
    "residue",
    ["`code`", "**unclosed", "[text](url)", "\n### Heading"],
    ids=["backtick", "bold", "link", "heading"],
)
def test_residual_markdown_warns(residue):
    issues = check(
        lambda o: o["description"].__setitem__("text", GOOD["description"]["text"] + residue)
    )

    assert any(
        i.key == "description" and "literally" in i.message for i in issues
    )


def test_supported_markup_does_not_warn():
    text = (
        "## ✨ Features\n\n- **Term** — benefit, see [docs](https://x.dev).\n\n"
        + GOOD["description"]["text"]
    )

    assert check(lambda o: o["description"].__setitem__("text", text)) == []


# ---------------------------------------------------------------------- tags
def test_no_tags_is_an_error():
    assert "tags" in keys(check(lambda o: o.__setitem__("tags", [])), "error")


def test_too_many_tags_is_an_error():
    issues = check(
        lambda o: o.__setitem__("tags", [f"t{i}" for i in range(fabrules.TAGS_MAX + 1)])
    )

    assert "tags" in keys(issues, "error")


def test_few_tags_only_warns():
    issues = check(lambda o: o.__setitem__("tags", ["one"]))

    assert keys(issues, "warning") == {"tags"}
    assert not has_errors(issues)


def test_a_picker_hostile_tag_warns():
    issues = check(lambda o: o["tags"].append("a really quite long tag, with a comma"))

    assert any("picker" in i.message for i in issues if i.key == "tags")


# ------------------------------------------------------------ category/price
def test_missing_category_is_an_error_and_lists_the_options():
    issues = check(lambda o: o.__setitem__("category", ""))

    assert "category" in keys(issues, "error")
    assert "Gameplay Features" in message_for(issues, "category")


def test_an_unknown_category_only_warns():
    """The vocabulary is scraped, not authoritative, and it is instant to fix."""
    issues = check(lambda o: o.__setitem__("category", "Invented"))

    assert keys(issues, "warning") == {"category"}


def test_a_product_type_outside_fabs_list_is_an_error():
    issues = check(lambda o: o.__setitem__("product_type", "Widgets"))

    assert "product_type" in keys(issues, "error")


def test_a_missing_product_type_is_an_error():
    assert "product_type" in keys(
        check(lambda o: o.__setitem__("product_type", "")), "error"
    )


def test_a_bad_license_is_an_error():
    assert "license" in keys(
        check(lambda o: o["license"].__setitem__("type", "Whatever")), "error"
    )


def test_a_missing_price_is_an_error():
    issues = check(lambda o: o["license"].__setitem__("price_personal", None))

    assert "price.personal" in keys(issues, "error")


def test_professional_below_personal_warns():
    issues = check(lambda o: o["license"].__setitem__("price_professional", 1.0))

    assert "price.professional" in keys(issues, "warning")


# ----------------------------------------------------------------- technical
def test_no_engine_versions_is_an_error():
    assert "technical.engine_versions" in keys(
        check(lambda o: o["technical"].__setitem__("engine_versions", [])), "error"
    )


def test_declaring_versions_that_exclude_the_descriptor_warns():
    issues = check(
        lambda o: o["technical"].__setitem__("engine_versions", ["5.6"]),
        descriptor_engine_version="5.8.0",
    )

    assert "technical.engine_versions" in keys(issues, "warning")


def test_empty_platform_lists_are_errors():
    issues = check(lambda o: o["technical"].__setitem__("target_platforms", []))

    assert "technical.target_platforms" in keys(issues, "error")


# --------------------------------------------------------------------- media
def test_a_thumbnail_that_is_not_on_disk_is_an_error():
    issues = check(lambda o: o["media"]["thumbnail"].__setitem__("sha256", ""))

    assert "media.thumbnail" in keys(issues, "error")


def test_an_undersized_thumbnail_is_an_error():
    issues = check(lambda o: o["media"]["thumbnail"].update({"width": 1200, "height": 630}))

    assert "1200x630" in message_for(issues, "media.thumbnail")


def test_an_oversized_thumbnail_is_an_error():
    issues = check(
        lambda o: o["media"]["thumbnail"].__setitem__(
            "bytes", fabrules.THUMBNAIL_MAX_BYTES + 1
        )
    )

    assert "media.thumbnail" in keys(issues, "error")


def test_unreadable_dimensions_only_warn():
    issues = check(lambda o: o["media"]["thumbnail"].update({"width": None, "height": None}))

    assert "media.thumbnail" in keys(issues, "warning")
    assert not has_errors(issues)


def test_a_wrong_thumbnail_extension_is_an_error():
    issues = check(lambda o: o["media"]["thumbnail"].__setitem__("source", "a.gif"))

    assert "media.thumbnail" in keys(issues, "error")


def test_an_empty_gallery_is_an_error():
    issues = check(lambda o: o["media"].__setitem__("gallery", []))

    assert "media.gallery" in keys(issues, "error")


def test_a_gallery_path_missing_on_disk_names_the_path():
    issues = check(lambda o: o["media"].__setitem__("missing", ["g9.png"]))

    assert "g9.png" in message_for(issues, "media.gallery")


def test_too_many_gallery_items_is_an_error():
    def mutate(o):
        o["media"]["gallery"] = [
            {"index": i, "source": f"g{i}.png", "bytes": 1, "sha256": str(i)}
            for i in range(fabrules.GALLERY_MAX_ITEMS + 1)
        ]

    assert "media.gallery" in keys(check(mutate), "error")


def test_an_oversized_gallery_is_an_error():
    issues = check(
        lambda o: o["media"].__setitem__("gallery_bytes", fabrules.GALLERY_MAX_BYTES + 1)
    )

    assert "media.gallery" in keys(issues, "error")


def test_a_gallery_holding_only_the_thumbnail_warns_and_can_be_silenced():
    def mutate(o):
        o["media"]["gallery"] = [dict(o["media"]["thumbnail"], index=1)]

    issues = check(mutate)
    assert any("only the thumbnail" in i.message for i in issues)

    silenced = check(mutate, silence={"gallery_thumbnail_only": True})
    assert not any("only the thumbnail" in i.message for i in silenced)


# -------------------------------------------------------------- product file
def test_no_zip_yet_only_warns():
    issues = check(lambda o: o.__setitem__("product_file", None))

    assert keys(issues, "warning") == {"product_file"}
    assert not has_errors(issues)


def test_a_zip_without_a_root_uplugin_is_an_error():
    assert "product_file" in keys(
        check(lambda o: o["product_file"].__setitem__("has_uplugin", False)), "error"
    )


def test_a_zip_without_a_build_cs_is_an_error():
    assert "product_file" in keys(
        check(lambda o: o["product_file"].__setitem__("has_source_build_cs", False)),
        "error",
    )


def test_missing_content_or_config_warns_and_is_silenceable():
    """Most of the suite legitimately ships without one or both."""
    mutate = lambda o: o["product_file"].update(
        {"has_content": False, "has_config": False}
    )

    assert "product_file" in keys(check(mutate), "warning")
    assert not check(mutate, silence={"missing_content_config": True})


# ----------------------------------------------------------------- forum post
def test_a_forum_post_without_an_epic_url_warns():
    issues = check(lambda o: o["forum_post"].update({"has": True, "url": "https://x.com"}))

    assert "forum_post.url" in keys(issues, "warning")


def test_a_valid_forum_post_passes():
    issues = check(
        lambda o: o["forum_post"].update(
            {"has": True, "url": "https://forums.unrealengine.com/t/thing/1"}
        )
    )

    assert issues == []
