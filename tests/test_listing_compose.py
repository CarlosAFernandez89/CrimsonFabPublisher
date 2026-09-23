"""Precedence, provenance and - above all - determinism."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from fabpublisher.dependencies import classify_dependencies
from fabpublisher.discovery import discover_plugins
from fabpublisher.listing import schema
from fabpublisher.listing.compose import (
    AUTHORED,
    DEFAULT,
    DERIVED,
    compose,
    is_publishable,
    major_minor,
    spaced,
    tier_of,
)
from fabpublisher.listing.diffing import leaf_paths
from fabpublisher.listing.requires import Requirements


@pytest.fixture
def plugins(suite: Path):
    found = discover_plugins(suite)
    classify_dependencies(found, {"GameplayAbilities"})
    return {p.name: p for p in found}


def _compose(
    plugins, listings, authored=None, defaults=None, name="Common", requirements=None
):
    return compose(
        plugins[name],
        authored or {},
        defaults or {},
        listings / "media",
        dev_platforms=["Windows"],
        requirements=requirements,
    )


# ------------------------------------------------------------------- helpers
@pytest.mark.parametrize(
    "plugin_id,expected",
    [
        ("MySaveSystem", "My Save System"),
        ("AcmeHitDetection", "Acme Hit Detection"),
        # Acronyms must survive: splitting on every capital gives "My Plugin U I".
        ("MyPluginUI", "My Plugin UI"),
        ("AcmeOnlineSubsystem", "Acme Online Subsystem"),
    ],
)
def test_spaced_splits_only_on_lower_to_upper(plugin_id, expected):
    assert spaced(plugin_id) == expected


def test_major_minor():
    assert major_minor("5.8.0") == "5.8"
    assert major_minor("nonsense") == "nonsense"


# -------------------------------------------------------------- determinism
def test_composing_twice_is_byte_identical(plugins, listings):
    """Verification #1. Without this every diff is dirty and nothing works."""
    authored = {"tags": ["a", "b"], "category": "Engine Tools"}
    first, _ = _compose(plugins, listings, authored)
    second, _ = _compose(plugins, listings, authored)

    assert json.dumps(first, indent=2) == json.dumps(second, indent=2)


def test_keys_are_emitted_in_schema_order(plugins, listings):
    listing, _ = _compose(plugins, listings)

    assert tuple(listing) == schema.KEY_ORDER


def test_sets_are_sorted_so_input_order_cannot_fake_a_change(plugins, listings):
    a, _ = _compose(plugins, listings, {"tags": ["zebra", "apple"]})
    b, _ = _compose(plugins, listings, {"tags": ["apple", "zebra"]})

    assert a["tags"] == b["tags"] == ["apple", "zebra"]


def test_no_absolute_paths_leak_into_the_listing(plugins, listings, tmp_path):
    listing, _ = _compose(plugins, listings)

    blob = json.dumps(listing)
    assert str(tmp_path) not in blob
    assert "\\\\" not in blob, "a Windows path separator means a path leaked in"
    source = listing["media"]["thumbnail"]["source"]
    assert not source.startswith("/") and ":" not in source


def test_every_emitted_path_is_classified(plugins, listings):
    """The fail-safe guard: a new field must be classified, or CI fails."""
    listing, _ = _compose(plugins, listings)

    unclassified = [
        path
        for path in leaf_paths(listing, schema.SPECS)
        if schema.spec_for(path) is None
    ]
    assert unclassified == []


# --------------------------------------------------------------- precedence
def test_authored_beats_derived(plugins, listings):
    listing, provenance = _compose(plugins, listings, {"title": "Hand Written"})

    assert listing["title"] == "Hand Written"
    assert provenance["title"].kind == AUTHORED


def test_derived_is_used_when_nothing_is_authored(plugins, listings):
    listing, provenance = _compose(plugins, listings)

    assert listing["title"] == "Common"
    assert provenance["title"].kind == DERIVED
    assert "Common" in provenance["title"].detail


def test_defaults_beat_derived_but_lose_to_authored(plugins, listings):
    defaults = {"category": "Engine Tools"}
    listing, provenance = _compose(plugins, listings, {}, defaults)
    assert listing["category"] == "Engine Tools"
    assert provenance["category"].kind == DEFAULT

    listing, provenance = _compose(
        plugins, listings, {"category": "Physics"}, defaults
    )
    assert listing["category"] == "Physics"
    assert provenance["category"].kind == AUTHORED


@pytest.mark.parametrize("empty", [None, "", []], ids=["null", "blank", "empty-list"])
def test_an_empty_authored_value_falls_through(plugins, listings, empty):
    """null/""/[] mean "I have not set this", not "set it to nothing"."""
    listing, provenance = _compose(plugins, listings, {"title": empty})

    assert listing["title"] == "Common"
    assert provenance["title"].kind == DERIVED


def test_zero_and_false_are_real_values_not_absence(plugins, listings):
    """A free plugin's price and an unticked declaration must survive."""
    authored = {"price": {"personal": 0, "professional": 0}, "tier": "free"}
    listing, provenance = _compose(plugins, listings, authored)

    assert listing["license"]["price_personal"] == 0.0
    assert provenance["license.price_personal"].kind == AUTHORED

    listing, _ = _compose(plugins, listings, {"declarations": {"no_ai": False}})
    assert listing["declarations"]["no_ai"] is False


def test_free_tier_prices_at_zero_without_being_authored(plugins, listings):
    listing, provenance = _compose(plugins, listings, {"tier": "free"})

    assert listing["license"]["price_personal"] == 0.0
    assert provenance["license.price_personal"].kind == DERIVED


# ---------------------------------------------------------------- derivation
def test_engine_version_becomes_major_minor(plugins, listings):
    listing, _ = _compose(plugins, listings)

    assert listing["technical"]["engine_versions"] == ["5.8"]


def test_technical_block_names_required_plugins(plugins, listings):
    """Fab 1.8.4.b - the technical text has to state the prerequisites."""
    requirements = Requirements(suite=("Common",), engine=("GameplayAbilities",))
    listing, _ = _compose(
        plugins, listings, name="Ability", requirements=requirements
    )

    text = listing["description"]["text"]
    assert "Required plugins (install these first): Common" in text
    assert "Engine plugins used: GameplayAbilities" in text
    assert "Unreal Engine 5.8" in text
    assert listing["technical"]["required_plugins"] == ["Common"]
    assert listing["technical"]["engine_plugins"] == ["GameplayAbilities"]


def test_engine_plugins_can_be_left_out_of_the_description(plugins, listings):
    """Some reviewers want every plugin; some publishers would rather not."""
    requirements = Requirements(suite=("Common",), engine=("GameplayAbilities",))
    listing, _ = _compose(
        plugins,
        listings,
        {"technical": {"include_engine_plugins": False}},
        name="Ability",
        requirements=requirements,
    )

    text = listing["description"]["text"]
    assert "Required plugins (install these first): Common" in text
    assert "Engine plugins used" not in text
    # Still recorded, so turning it back on needs no re-scan.
    assert listing["technical"]["engine_plugins"] == ["GameplayAbilities"]


def test_a_plugin_with_no_prerequisites_says_so(plugins, listings):
    listing, _ = _compose(plugins, listings, requirements=Requirements())

    assert "Required plugins: none beyond Unreal Engine itself." in (
        listing["description"]["text"]
    )


def test_authored_technical_text_is_kept_and_the_generated_block_appended(
    plugins, listings
):
    listing, provenance = _compose(
        plugins, listings, {"description": {"technical": "Needs C++17."}}
    )

    assert "Needs C++17." in listing["description"]["text"]
    assert "Unreal Engine 5.8" in listing["description"]["text"]
    assert provenance["description.technical"].kind == AUTHORED


def test_description_blocks_record_which_areas_are_present(plugins, listings):
    listing, _ = _compose(plugins, listings, {"description": {"how": "Use it."}})

    assert listing["description"]["blocks"] == ["how", "technical"]
    assert listing["description"]["chars"] == len(listing["description"]["text"])


def test_description_ranges_recover_each_block_with_its_paragraphs(plugins, listings):
    how = "## 🛠️ Getting Started\n\n- Add it.\n- Use it."
    listing, _ = _compose(
        plugins, listings, {"description": {"what": "One.\n\nTwo.", "how": how}}
    )

    description = listing["description"]
    blocks = {
        name: description["text"][start:end]
        for name, (start, end) in zip(description["blocks"], description["ranges"])
    }
    assert blocks["what"] == "One.\n\nTwo."
    assert blocks["how"] == how


def test_media_id_token_resolves_to_the_plugin_id(plugins, listings):
    listing, _ = _compose(
        plugins, listings, {"media": {"thumbnail": "{id}/thumbnail.png"}}
    )

    assert listing["media"]["thumbnail"]["source"] == "Common/thumbnail.png"
    assert listing["media"]["thumbnail"]["width"] == 1920


def test_a_missing_gallery_file_is_recorded_rather_than_dropped(plugins, listings):
    """Validation needs to name the wrong path, not just say "empty"."""
    listing, _ = _compose(
        plugins, listings, {"media": {"gallery": ["Common/nope.png"]}}
    )

    assert listing["media"]["missing"] == ["Common/nope.png"]
    assert listing["media"]["gallery"] == []


def test_gallery_falls_back_to_the_thumbnail(plugins, listings):
    listing, provenance = _compose(plugins, listings)

    assert listing["media"]["gallery_count"] == 1
    assert provenance["media.gallery"].kind == DERIVED


def test_live_listing_fields_come_from_the_descriptor(plugins, listings):
    plugin = plugins["Common"]
    plugin.marketplace_url = (
        "com.epicgames.launcher://ue/Fab/product/"
        "11111111-2222-3333-4444-555555555555"
    )
    listing, _ = _compose(plugins, listings)

    assert listing["fab"]["is_live"] is True
    assert listing["fab"]["product_id"] == "11111111-2222-3333-4444-555555555555"


# ------------------------------------------------------------------- opt-out
def test_publish_false_opts_a_plugin_out(plugins, listings):
    assert is_publishable({}, {}) is True
    assert is_publishable({"publish": False}, {}) is False
    assert is_publishable({}, {"publish": False}) is False
    assert is_publishable({"publish": True}, {"publish": False}) is True


def test_tier_falls_back_through_defaults(plugins, listings):
    assert tier_of({}, {}) == "premium"
    assert tier_of({}, {"tier": "free"}) == "free"
    assert tier_of({"tier": "premium"}, {"tier": "free"}) == "premium"


def test_compose_does_not_mutate_its_inputs(plugins, listings):
    authored = {"tags": ["a"], "description": {"how": "x"}}
    before = copy.deepcopy(authored)

    _compose(plugins, listings, authored)

    assert authored == before
