"""Check a composed listing against Fab's requirements.

Errors block accept and mean the listing is not submittable; warnings report
and let it through. Every message names the authored key that fixes it, so a
report can be worked through without hunting for where a value came from.

The limits all come from `fabrules`, so this module and the drafting prompt
cannot disagree about what Fab will accept.
"""

from __future__ import annotations

import re

from ..validation import Issue
from . import fabrules, markup, schema

#: A camelCase run, i.e. the raw plugin id leaked past the title derivation.
_CAMEL_RUN = re.compile(r"[a-z][A-Z]")

#: Characters that make a tag awkward in Fab's one-at-a-time picker.
_AWKWARD_TAG = re.compile(r"[,\n\r\t]")


def _error(message: str, key: str) -> Issue:
    return Issue("error", message, key)


def _warn(message: str, key: str) -> Issue:
    return Issue("warning", message, key)


def _check_title(listing: dict) -> list[Issue]:
    title = str(listing.get("title") or "")
    if not title:
        return [_error("No title. Set `title` in the listing file.", "title")]

    issues: list[Issue] = []
    if len(title) > fabrules.TITLE_MAX:
        issues.append(
            _error(
                f"Title is {len(title)} characters; the field accepts "
                f"{fabrules.TITLE_MAX} ({fabrules.cite('title-length')}). "
                f"Shorten `title`.",
                "title",
            )
        )
    elif len(title) > fabrules.TITLE_RECOMMENDED:
        issues.append(
            _warn(
                f"Title is {len(title)} characters; Fab recommends "
                f"{fabrules.TITLE_RECOMMENDED} or fewer. Shorten `title`.",
                "title",
            )
        )
    if _CAMEL_RUN.search(title):
        issues.append(
            _warn(
                f"Title {title!r} still reads as a camelCase id. Set `title` "
                f"to the spaced form.",
                "title",
            )
        )
    return issues


def _check_description(listing: dict) -> list[Issue]:
    description = listing.get("description") or {}
    text = str(description.get("text") or "")
    if not text.strip():
        return [
            _error(
                "No description. Fill `description.what`, `description.how` "
                "and `description.technical` in the listing file.",
                "description",
            )
        ]

    issues: list[Issue] = []
    if len(text) < fabrules.DESCRIPTION_THIN:
        issues.append(
            _warn(
                f"Description is {len(text)} characters, which is thin for a "
                f"paid plugin. Expand `description.what` and "
                f"`description.how`.",
                "description",
            )
        )

    missing = [
        block for block in schema.DESCRIPTION_BLOCKS
        if block not in (description.get("blocks") or [])
    ]
    if missing:
        issues.append(
            _warn(
                f"Description does not cover {', '.join(missing)} "
                f"({fabrules.cite('three-content-areas')}). Fill "
                f"`description.{missing[0]}`.",
                f"description.{missing[0]}",
            )
        )

    found = markup.problems(text)
    if found:
        issues.append(
            _warn(
                f"Description contains {', '.join(found)}, which Fab shows "
                f"literally ({fabrules.cite('plain-prose')}). Use only ## "
                f"headings, - bullets, **bold** and [text](https://...) links.",
                "description",
            )
        )
    return issues


def _check_tags(listing: dict) -> list[Issue]:
    tags = listing.get("tags") or []
    if not tags:
        return [_error("No tags. Add at least one to `tags`.", "tags")]

    issues: list[Issue] = []
    if len(tags) > fabrules.TAGS_MAX:
        issues.append(
            _error(
                f"{len(tags)} tags; Fab takes {fabrules.TAGS_MAX} "
                f"({fabrules.cite('tag-count')}). Trim `tags`.",
                "tags",
            )
        )
    elif len(tags) < fabrules.TAGS_THIN:
        issues.append(
            _warn(
                f"Only {len(tags)} tags. Fab allows {fabrules.TAGS_MAX} and "
                f"they drive discovery; add more to `tags`.",
                "tags",
            )
        )

    # Tags are picked from Fab's own list, so these are candidates rather than
    # settings. There is no vocabulary to validate against - inventing one
    # would reject tags that are actually fine - so the check is only about
    # which candidates are plausible enough to be worth trying.
    unlikely = [
        t
        for t in tags
        if len(str(t)) > fabrules.TAG_CHARS_MAX or _AWKWARD_TAG.search(str(t))
    ]
    if unlikely:
        issues.append(
            _warn(
                f"Tag(s) {', '.join(repr(str(t)) for t in unlikely[:3])} are long "
                f"or contain separators, so Fab's picker probably will not "
                f"offer them. Shorten them in `tags`, or drop them once you "
                f"have confirmed they are missing.",
                "tags",
            )
        )
    return issues


def _check_product_type(listing: dict) -> list[Issue]:
    product_type = str(listing.get("product_type") or "")
    if not product_type:
        return [
            _error(
                f"No product type. Set `product_type` to one of: "
                f"{', '.join(schema.PRODUCT_TYPES)}.",
                "product_type",
            )
        ]
    if product_type not in schema.PRODUCT_TYPES:
        return [
            _error(
                f"Product type {product_type!r} is not one of Fab's options: "
                f"{', '.join(schema.PRODUCT_TYPES)}.",
                "product_type",
            )
        ]
    return []


def _check_category(listing: dict) -> list[Issue]:
    category = str(listing.get("category") or "")
    if not category:
        return [
            _error(
                f"No category. Set `category` to one of: "
                f"{', '.join(schema.CATEGORIES)}.",
                "category",
            )
        ]
    if category not in schema.CATEGORIES:
        # The vocabulary was scraped from the public channel filter, not the
        # form's own picker, so an unknown value is suspicious, not wrong.
        return [
            _warn(
                f"Category {category!r} is not in the known list "
                f"({fabrules.cite('relevant-category')}). Confirm it against "
                f"the form's picker.",
                "category",
            )
        ]
    return []


def _check_license(listing: dict) -> list[Issue]:
    license_ = listing.get("license") or {}
    issues: list[Issue] = []
    if license_.get("type") not in schema.LICENSES:
        issues.append(
            _error(
                f"License {license_.get('type')!r} is not one of "
                f"{', '.join(schema.LICENSES)}. Set `license`.",
                "license",
            )
        )
    for field_name, key in (
        ("price_personal", "price.personal"),
        ("price_professional", "price.professional"),
    ):
        value = license_.get(field_name)
        if not isinstance(value, (int, float)) or value < 0:
            issues.append(
                _error(f"{key} must be a number of US dollars.", key)
            )
    if (
        isinstance(license_.get("price_personal"), (int, float))
        and isinstance(license_.get("price_professional"), (int, float))
        and license_["price_professional"] < license_["price_personal"]
    ):
        issues.append(
            _warn(
                "price.professional is below price.personal, which inverts "
                "Fab's seat tiers.",
                "price.professional",
            )
        )
    return issues


def _check_technical(listing: dict, descriptor_engine_version: str = "") -> list[Issue]:
    technical = listing.get("technical") or {}
    issues: list[Issue] = []

    versions = technical.get("engine_versions") or []
    if not versions:
        issues.append(
            _error(
                "No engine versions. Set `technical.engine_versions`.",
                "technical.engine_versions",
            )
        )
    elif descriptor_engine_version:
        declared = ".".join(descriptor_engine_version.split(".")[:2])
        if declared and declared not in versions:
            issues.append(
                _warn(
                    f"The descriptor targets {declared} but "
                    f"`technical.engine_versions` does not list it.",
                    "technical.engine_versions",
                )
            )

    for field_name in ("dev_platforms", "target_platforms"):
        if not technical.get(field_name):
            issues.append(
                _error(
                    f"No {field_name.replace('_', ' ')}. Set "
                    f"`technical.{field_name}`.",
                    f"technical.{field_name}",
                )
            )
    return issues


def _check_media(listing: dict, silence: dict) -> list[Issue]:
    media = listing.get("media") or {}
    thumbnail = media.get("thumbnail") or {}
    gallery = media.get("gallery") or []
    issues: list[Issue] = []

    source_path = thumbnail.get("source") or "?"
    if not thumbnail.get("sha256"):
        issues.append(
            _error(
                f"Thumbnail {source_path!r} is not on disk. Put it under the "
                f"listings media folder or fix `media.thumbnail`.",
                "media.thumbnail",
            )
        )
    else:
        suffix = source_path[source_path.rfind(".") :].lower()
        if suffix not in fabrules.THUMBNAIL_FORMATS:
            issues.append(
                _error(
                    f"Thumbnail is {suffix}; Fab takes "
                    f"{', '.join(fabrules.THUMBNAIL_FORMATS)}. Fix "
                    f"`media.thumbnail`.",
                    "media.thumbnail",
                )
            )
        if thumbnail.get("bytes", 0) > fabrules.THUMBNAIL_MAX_BYTES:
            issues.append(
                _error(
                    f"Thumbnail is "
                    f"{thumbnail['bytes'] / 1024 / 1024:.1f} MB; the limit is "
                    f"{fabrules.THUMBNAIL_MAX_BYTES // (1024 * 1024)} MB "
                    f"({fabrules.cite('thumbnail-spec')}).",
                    "media.thumbnail",
                )
            )
        width, height = thumbnail.get("width"), thumbnail.get("height")
        if width is None or height is None:
            issues.append(
                _warn(
                    f"Could not read the dimensions of {source_path!r}; check "
                    f"it is at least {fabrules.THUMBNAIL_MIN_WIDTH}x"
                    f"{fabrules.THUMBNAIL_MIN_HEIGHT} by hand.",
                    "media.thumbnail",
                )
            )
        elif (
            width < fabrules.THUMBNAIL_MIN_WIDTH
            or height < fabrules.THUMBNAIL_MIN_HEIGHT
        ):
            issues.append(
                _error(
                    f"Thumbnail is {width}x{height}; Fab needs at least "
                    f"{fabrules.THUMBNAIL_MIN_WIDTH}x"
                    f"{fabrules.THUMBNAIL_MIN_HEIGHT} "
                    f"({fabrules.cite('thumbnail-spec')}).",
                    "media.thumbnail",
                )
            )

    for missing in media.get("missing") or []:
        issues.append(
            _error(
                f"Gallery item {missing!r} is not on disk. Add the file or "
                f"remove it from `media.gallery`.",
                "media.gallery",
            )
        )

    if not gallery:
        issues.append(
            _error(
                f"Gallery is empty; Fab needs at least one item "
                f"({fabrules.cite('gallery-spec')}). Add to `media.gallery`.",
                "media.gallery",
            )
        )
    else:
        if len(gallery) > fabrules.GALLERY_MAX_ITEMS:
            issues.append(
                _error(
                    f"{len(gallery)} gallery items; Fab takes "
                    f"{fabrules.GALLERY_MAX_ITEMS}. Trim `media.gallery`.",
                    "media.gallery",
                )
            )
        if media.get("gallery_bytes", 0) > fabrules.GALLERY_MAX_BYTES:
            issues.append(
                _error(
                    f"Gallery images total "
                    f"{media['gallery_bytes'] / 1024 / 1024:.1f} MB; the limit "
                    f"is {fabrules.GALLERY_MAX_BYTES // (1024 * 1024)} MB.",
                    "media.gallery",
                )
            )
        only_thumbnail = len(gallery) == 1 and gallery[0].get("sha256") == thumbnail.get(
            "sha256"
        )
        if only_thumbnail and not silence.get("gallery_thumbnail_only"):
            issues.append(
                _warn(
                    "The gallery holds only the thumbnail. It is legal but "
                    "thin - add a real capture, or set "
                    "`silence.gallery_thumbnail_only`.",
                    "media.gallery",
                )
            )
    return issues


def _check_product_file(listing: dict, silence: dict) -> list[Issue]:
    """Only meaningful once a zip has been built; absence is not an error."""
    zip_facts = listing.get("product_file")
    if not zip_facts:
        return [
            _warn(
                "No submission zip found in the output folder yet; build the "
                "plugin so the product file can be recorded.",
                "product_file",
            )
        ]

    issues: list[Issue] = []
    if not zip_facts.get("has_uplugin"):
        issues.append(
            _error("The zip has no .uplugin at its root.", "product_file")
        )
    if not zip_facts.get("has_source_build_cs"):
        issues.append(
            _error(
                f"The zip has no Source/ module with a *.Build.cs "
                f"({fabrules.cite('code-module')}).",
                "product_file",
            )
        )
    missing = [
        name
        for name, present in (
            ("Content/", zip_facts.get("has_content")),
            ("Config/", zip_facts.get("has_config")),
        )
        if not present
    ]
    if missing and not silence.get("missing_content_config"):
        issues.append(
            _warn(
                f"The zip has no {' or '.join(missing)}. Many plugins ship "
                f"without; set `silence.missing_content_config` to stop asking.",
                "product_file",
            )
        )
    return issues


def _check_forum_post(listing: dict) -> list[Issue]:
    forum = listing.get("forum_post") or {}
    if not forum.get("has"):
        return []
    url = str(forum.get("url") or "")
    if "forums.unrealengine.com" not in url:
        return [
            _warn(
                "`forum_post.has` is set but the URL is missing or is not an "
                "Epic Developer Community thread.",
                "forum_post.url",
            )
        ]
    return []


def check_listing(
    listing: dict,
    *,
    unknown_keys: list[str] | None = None,
    stray_braces: list[str] | None = None,
    silence: dict | None = None,
    descriptor_engine_version: str = "",
    source_error: str = "",
) -> list[Issue]:
    """Every requirement this listing currently fails.

    `unknown_keys` and `stray_braces` come from the authored file rather than
    the composed listing, because by the time a value has been composed a
    typo'd key has already vanished.
    """
    if source_error:
        return [_error(source_error, "listing file")]

    silence = silence or {}
    issues: list[Issue] = []

    for key in unknown_keys or []:
        # A hard error on purpose: a misspelled key that quietly does nothing
        # is worse than one that refuses to load, because it looks like it
        # worked.
        issues.append(
            _error(
                f"Unknown key {key!r} in the listing file. Remove it or "
                f"correct the spelling.",
                key,
            )
        )
    for path in stray_braces or []:
        issues.append(
            _error(
                f"{path} contains a brace. Only {'{id}'} inside `media` is a "
                f"template.",
                path,
            )
        )

    issues.extend(_check_title(listing))
    issues.extend(_check_product_type(listing))
    issues.extend(_check_category(listing))
    issues.extend(_check_license(listing))
    issues.extend(_check_description(listing))
    issues.extend(_check_tags(listing))
    issues.extend(_check_technical(listing, descriptor_engine_version))
    issues.extend(_check_media(listing, silence))
    issues.extend(_check_product_file(listing, silence))
    issues.extend(_check_forum_post(listing))
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.level == "error" for issue in issues)
