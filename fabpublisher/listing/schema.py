"""The shape of a generated listing, and how each field diffs.

Two jobs, both load-bearing:

`KEY_ORDER` fixes the key order of the generated object. Python dicts keep
insertion order, so composing in this order and never sorting keys is what
makes two builds of unchanged inputs byte-identical - without which every diff
is dirty and the whole feature is worthless.

`SPECS` says, per field, whether editing it sends the listing back through Fab
review and how to describe a change to it. A path with no spec is treated as
review-triggering and reported UNCLASSIFIED: guessing "probably instant" is the
expensive mistake, so the table has to be updated rather than silently trusted.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fabrules import (  # re-exported: the limits belong to the rule table
    DESCRIPTION_THIN,
    GALLERY_MAX_BYTES,
    GALLERY_MAX_ITEMS,
    TAG_CHARS_MAX,
    TAGS_MAX,
    TAGS_THIN,
    THUMBNAIL_FORMATS,
    THUMBNAIL_MAX_BYTES,
    THUMBNAIL_MIN_HEIGHT,
    THUMBNAIL_MIN_WIDTH,
    TITLE_MAX,
    TITLE_RECOMMENDED,
)

__all__ = [
    "FieldSpec",
    "KEY_ORDER",
    "SPECS",
    "IGNORED",
    "build_specs",
    "spec_for",
    "PRODUCT_TYPE",
    "PRODUCT_TYPES",
    "CATEGORIES",
    "LICENSES",
    "DISTRIBUTION",
    "DEV_PLATFORMS",
    "TARGET_PLATFORMS",
    "DESCRIPTION_BLOCKS",
    "TITLE_MAX",
    "TITLE_RECOMMENDED",
    "TAGS_MAX",
    "TAGS_THIN",
    "TAG_CHARS_MAX",
    "DESCRIPTION_THIN",
    "THUMBNAIL_FORMATS",
    "THUMBNAIL_MAX_BYTES",
    "THUMBNAIL_MIN_WIDTH",
    "THUMBNAIL_MIN_HEIGHT",
    "GALLERY_MAX_ITEMS",
    "GALLERY_MAX_BYTES",
]

# --------------------------------------------------------------- vocabularies

#: Fab's Product type picker, read off the form itself. A code plugin is
#: always the last one, but the field exists and has to be set.
PRODUCT_TYPES: tuple[str, ...] = (
    "3D",
    "Animation",
    "Audio",
    "Game Systems",
    "Game Templates",
    "HDRI",
    "Materials & Textures",
    "Sprites & Flipbooks",
    "Tools & Plugins",
    "Tutorials & Examples",
    "UI",
    "VFX",
)

PRODUCT_TYPE = "Tools & Plugins"

#: Fab's Category picker - one value, not several. Scraped from the public
#: channel filter rather than the form, so an unrecognised value is suspicious
#: rather than wrong, and category is an instant-class edit anyway.
CATEGORIES: tuple[str, ...] = (
    "Animations",
    "Artificial Intelligence",
    "Automations",
    "Dialog Systems",
    "Engine Tools",
    "Game Mechanics",
    "Gameplay Features",
    "Modeling",
    "Network & Multiplayer",
    "Physics",
    "Procedural Systems",
    "Tutorials & Examples",
)

LICENSES: tuple[str, ...] = ("Standard", "CC BY 4.0")
DISTRIBUTION = "Plugin"
DEV_PLATFORMS: tuple[str, ...] = ("Windows", "Mac", "Linux")
TARGET_PLATFORMS: tuple[str, ...] = (
    "Win64",
    "Mac",
    "Linux",
    "Android",
    "IOS",
)

#: The three areas Fab asks a description to cover, in the order they read.
DESCRIPTION_BLOCKS: tuple[str, ...] = ("what", "how", "technical")

# ------------------------------------------------------------------ key order

#: Top-level keys of the generated listing, in the order they are written.
KEY_ORDER: tuple[str, ...] = (
    "schema_version",
    "plugin_id",
    "title",
    "product_type",
    "category",
    "license",
    "description",
    "tags",
    "technical",
    "stats",
    "media",
    "product_file",
    "forum_post",
    "declarations",
    "faq",
    "changelog",
    "fab",
    "plugin_version",
)

# ----------------------------------------------------------------- diff specs

#: Derived or discovered values, not edits. Dropped before diffing so they can
#: never report a change on their own.
IGNORED: frozenset[str] = frozenset(
    {
        "schema_version",
        "plugin_id",
        "plugin_version",
        "fab",
        "description.chars",
        "description.blocks",
        "media.missing",
        "media.gallery_bytes",
        "media.gallery_count",
    }
)


@dataclass(frozen=True)
class FieldSpec:
    path: str
    #: True when editing this field sends the listing back through Fab review.
    review: bool
    #: How to describe a change: scalar | set | list | text | digest.
    compare: str
    required: bool = False


#: Fab publishes which edits re-enter review. Anything it does not mention is
#: classified conservatively here, and the two genuinely unknown cases (faq,
#: changelog) are switchable - see `build_specs`.
_BASE: tuple[FieldSpec, ...] = (
    # Re-triggers review.
    FieldSpec("title", True, "scalar", required=True),
    FieldSpec("description.text", True, "text", required=True),
    FieldSpec("technical.engine_versions", True, "set", required=True),
    FieldSpec("technical.distribution", True, "scalar", required=True),
    FieldSpec("technical.required_plugins", True, "set"),
    FieldSpec("technical.engine_plugins", True, "set"),
    FieldSpec("stats.blueprints", True, "scalar"),
    FieldSpec("stats.cpp_classes", True, "scalar"),
    FieldSpec("media.thumbnail", True, "digest", required=True),
    FieldSpec("media.gallery", True, "list", required=True),
    FieldSpec("product_file", True, "digest"),
    # Applies instantly.
    FieldSpec("product_type", False, "scalar", required=True),
    FieldSpec("category", False, "scalar", required=True),
    FieldSpec("license.type", False, "scalar", required=True),
    FieldSpec("license.price_personal", False, "scalar", required=True),
    FieldSpec("license.price_professional", False, "scalar", required=True),
    FieldSpec("license.currency", False, "scalar"),
    FieldSpec("tags", False, "set", required=True),
    FieldSpec("technical.dev_platforms", False, "set", required=True),
    FieldSpec("technical.target_platforms", False, "set", required=True),
    FieldSpec("forum_post.has", False, "scalar"),
    FieldSpec("forum_post.url", False, "scalar"),
    FieldSpec("declarations.edc_forum_post", False, "scalar"),
    FieldSpec("declarations.mature", False, "scalar"),
    FieldSpec("declarations.no_ai", False, "scalar"),
    FieldSpec("declarations.generative_ai", False, "scalar"),
    FieldSpec("declarations.promotional", False, "scalar"),
)


def build_specs(
    faq_review: bool = True, changelog_review: bool = True
) -> dict[str, FieldSpec]:
    """The spec table.

    Fab's documentation says nothing about FAQ or changelog edits, so both
    default to review-triggering. Each is one boolean to flip once the real
    behaviour has been observed.
    """
    specs = {spec.path: spec for spec in _BASE}
    specs["faq"] = FieldSpec("faq", faq_review, "list")
    specs["changelog"] = FieldSpec("changelog", changelog_review, "list")
    return specs


SPECS: dict[str, FieldSpec] = build_specs()


def spec_for(path: str, specs: dict[str, FieldSpec] | None = None) -> FieldSpec | None:
    """The spec for a leaf path, or None - which the differ treats as REVIEW."""
    return (specs if specs is not None else SPECS).get(path)


def is_ignored(path: str) -> bool:
    """True for paths that are derived rather than edited."""
    if path in IGNORED:
        return True
    return any(path.startswith(f"{prefix}.") for prefix in IGNORED)
