"""Build the listing object, and record where every value came from.

Precedence is authored, then derived from the plugin, then the suite default,
then empty. `compose` returns the object and a parallel provenance map, because
knowing a field ended up wrong is only half useful without knowing which of
those four produced it.

Two invariants this module exists to hold:

* **Determinism.** Nothing here reads a clock, an absolute path or an mtime,
  keys are emitted in `schema.KEY_ORDER`, and every set is sorted. Two runs
  over unchanged inputs must serialise byte-for-byte identically.
* **No per-plugin special cases.** There is no `if plugin_id == ...` anywhere.
  Everything a single plugin needs differently lives in its authored file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..models import PluginInfo
from . import schema, source
from .imagefacts import ImageFacts, read_image
from .requires import Requirements
from .zipfacts import ZipFacts

SCHEMA_VERSION = 1

AUTHORED = "authored"
DERIVED = "derived"
DEFAULT = "default"
EMPTY = "empty"

#: Split a CamelCase id into words on a lower-to-upper boundary only, so
#: acronyms survive: MyPluginUI -> "My Plugin UI", not "My Plugin U I".
_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


@dataclass(frozen=True)
class Origin:
    kind: str
    detail: str = ""


def spaced(plugin_id: str) -> str:
    """"MySaveSystem" -> "My Save System"."""
    return _WORD_BOUNDARY.sub(" ", plugin_id)


def _present(value: object) -> bool:
    """True when an authored value is a real value rather than "fall through".

    null, "" and [] all mean "I have not set this". False and 0 are real
    values - a free plugin's price and an unticked declaration must not be
    mistaken for absence.
    """
    return value is not None and value != "" and value != [] and value != {}


def _nested(data: dict, path: str) -> object:
    node: object = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def major_minor(version: str) -> str:
    """"5.8.0" -> "5.8"; anything unparseable comes back unchanged."""
    parts = (version or "").split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else version


class _Composer:
    """Picks each field and remembers which source won."""

    def __init__(self, authored: dict, defaults: dict):
        self.authored = authored
        self.defaults = defaults
        self.provenance: dict[str, Origin] = {}

    def pick(
        self,
        path: str,
        *,
        authored_key: str | None = None,
        derived: object = None,
        derived_detail: str = "",
        fallback: object = None,
        fallback_detail: str = "",
    ) -> object:
        key = authored_key if authored_key is not None else path
        value = _nested(self.authored, key)
        if _present(value):
            self.provenance[path] = Origin(AUTHORED, f"{key} in the listing file")
            return value

        value = _nested(self.defaults, key)
        if _present(value):
            self.provenance[path] = Origin(
                DEFAULT, f"{key} in {source.DEFAULTS_FILENAME}"
            )
            return value

        if _present(derived):
            self.provenance[path] = Origin(DERIVED, derived_detail)
            return derived

        if _present(fallback):
            self.provenance[path] = Origin(DEFAULT, fallback_detail)
            return fallback

        self.provenance[path] = Origin(EMPTY, "nothing supplied a value")
        return derived if derived is not None else fallback

    def record(self, path: str, kind: str, detail: str) -> None:
        self.provenance[path] = Origin(kind, detail)


def _technical_block(
    plugin: PluginInfo,
    requirements: Requirements | None,
    include_engine_plugins: bool,
) -> str:
    """The technical area Fab 1.8.4.b requires, composed from the plugin.

    Always generated rather than authored, so it cannot drift from the plugin
    it describes. Anything extra the author wants goes in their own technical
    text, which is appended before this.

    Prerequisites get their own labelled line rather than being buried in
    prose, because that is what a reviewer looks for. Engine plugins are listed
    too by default: some reviewers ask for every plugin used, not only the
    third-party ones, and an over-complete list has never cost anyone a review.
    """
    lines = ["Engine version: Unreal Engine " + major_minor(plugin.engine_version)]

    modules = [m for m in plugin.modules if m.name]
    if modules:
        described = ", ".join(f"{m.name} ({m.type})" for m in modules)
        lines.append(f"Modules: {described}")

    required = sorted(requirements.suite + requirements.unknown) if requirements else []
    engine_plugins = sorted(requirements.engine) if requirements else []

    if required:
        lines.append(
            "Required plugins (install these first): " + ", ".join(required)
        )
    else:
        lines.append("Required plugins: none beyond Unreal Engine itself.")
    if include_engine_plugins and engine_plugins:
        lines.append("Engine plugins used: " + ", ".join(engine_plugins))

    lines.append(
        f"Contains {plugin.cpp_class_count} C++ class(es) and "
        f"{plugin.blueprint_count} Blueprint(s)."
    )
    return "\n".join(lines)


def _description(
    composer: _Composer,
    plugin: PluginInfo,
    requirements: Requirements | None,
    include_engine_plugins: bool,
) -> dict:
    what = composer.pick(
        "description.what",
        derived=plugin.description,
        derived_detail=f'Description in {plugin.name}.uplugin',
    )
    how = composer.pick("description.how")

    extra = composer.pick("description.technical")
    generated = _technical_block(plugin, requirements, include_engine_plugins)
    technical = f"{extra}\n\n{generated}" if _present(extra) else generated
    composer.record(
        "description.technical",
        AUTHORED if _present(extra) else DERIVED,
        "authored text plus the generated technical block"
        if _present(extra)
        else "generated from the descriptor, modules and dependencies",
    )

    blocks = [
        (name, text)
        for name, text in (("what", what), ("how", how), ("technical", technical))
        if _present(text)
    ]
    bodies = [str(body).strip() for _, body in blocks]
    text = "\n\n".join(bodies)
    # Where each block sits in `text`. A block has paragraphs of its own, so
    # splitting the text on blank lines cannot recover them.
    ranges, start = [], 0
    for body in bodies:
        ranges.append([start, start + len(body)])
        start += len(body) + 2
    return {
        "text": text,
        "chars": len(text),
        "blocks": [name for name, _ in blocks],
        "ranges": ranges,
    }


def _media(
    composer: _Composer, plugin_id: str, media_root: Path
) -> tuple[dict, ImageFacts | None, list[ImageFacts]]:
    thumbnail_rel = str(
        composer.pick(
            "media.thumbnail",
            derived=f"{plugin_id}/thumbnail.png",
            derived_detail="the conventional per-plugin thumbnail path",
        )
    )
    thumbnail_rel = source.resolve_id_token(thumbnail_rel, plugin_id)

    gallery_raw = composer.pick(
        "media.gallery",
        derived=[thumbnail_rel],
        derived_detail="falls back to the thumbnail as the single gallery item",
    )
    gallery_rel = [
        source.resolve_id_token(str(item), plugin_id)
        for item in (gallery_raw if isinstance(gallery_raw, list) else [])
    ]

    thumbnail = read_image(Path(media_root) / thumbnail_rel, thumbnail_rel)
    gallery = [
        facts
        for rel in gallery_rel
        if (facts := read_image(Path(media_root) / rel, rel)) is not None
    ]

    def entry(facts: ImageFacts) -> dict:
        return {
            "source": facts.source,
            "bytes": facts.bytes,
            "width": facts.width,
            "height": facts.height,
            "sha256": facts.sha256,
        }

    media = {
        # A missing file records its path with no facts, so validation can say
        # which path is wrong instead of just "gallery is empty".
        "thumbnail": entry(thumbnail)
        if thumbnail
        else {"source": thumbnail_rel, "bytes": 0, "width": None, "height": None, "sha256": ""},
        "gallery": [
            {"index": i, **entry(facts)} for i, facts in enumerate(gallery, start=1)
        ],
        "missing": sorted(
            {rel for rel in gallery_rel if not (Path(media_root) / rel).is_file()}
        ),
        "gallery_bytes": sum(f.bytes for f in gallery),
        "gallery_count": len(gallery),
    }
    return media, thumbnail, gallery


def _prices(composer: _Composer, tier: str) -> tuple[float, float]:
    free = tier == "free"
    personal = composer.pick(
        "license.price_personal",
        authored_key="price.personal",
        derived=0.0 if free else None,
        derived_detail="the free tier prices at zero",
    )
    professional = composer.pick(
        "license.price_professional",
        authored_key="price.professional",
        derived=0.0 if free else None,
        derived_detail="the free tier prices at zero",
    )
    return (
        float(personal) if isinstance(personal, (int, float)) else 0.0,
        float(professional) if isinstance(professional, (int, float)) else 0.0,
    )


def compose(
    plugin: PluginInfo,
    authored: dict,
    defaults: dict,
    media_root: Path,
    *,
    dev_platforms: list[str] | None = None,
    zip_facts: ZipFacts | None = None,
    requirements: Requirements | None = None,
) -> tuple[dict, dict[str, Origin]]:
    """The listing object for one plugin, plus where each value came from."""
    c = _Composer(authored, defaults)
    plugin_id = plugin.name

    title = c.pick(
        "title",
        derived=spaced(plugin_id),
        derived_detail=f"spaced from the plugin id {plugin_id}",
        fallback=plugin.friendly_name,
        fallback_detail=f"FriendlyName in {plugin_id}.uplugin",
    )
    tier = str(c.pick("tier", derived="premium", derived_detail="assumed premium"))

    product_type = c.pick(
        "product_type",
        derived=schema.PRODUCT_TYPE,
        derived_detail="a code plugin is always Tools & Plugins",
    )
    category = c.pick("category", derived="")

    include_engine_plugins = c.pick(
        "technical.include_engine_plugins",
        derived=True,
        derived_detail="reviewers may ask for every plugin used, not just third-party",
    )
    license_type = c.pick(
        "license.type",
        authored_key="license",
        derived=schema.LICENSES[0],
        derived_detail="the standard license, which allows free and paid",
    )
    price_personal, price_professional = _prices(c, tier)

    description = _description(
        c, plugin, requirements, bool(include_engine_plugins)
    )
    tags = c.pick("tags", derived=[])

    engine_versions = c.pick(
        "technical.engine_versions",
        derived=[major_minor(plugin.engine_version)] if plugin.engine_version else [],
        derived_detail=f"EngineVersion {plugin.engine_version} in the descriptor",
    )
    target_platforms = c.pick(
        "technical.target_platforms",
        derived=list(plugin.supported_target_platforms),
        derived_detail="SupportedTargetPlatforms in the descriptor",
    )
    dev = c.pick(
        "technical.dev_platforms",
        derived=list(dev_platforms or []),
        derived_detail="the platforms selected on the Build page",
    )
    distribution = c.pick(
        "technical.distribution",
        derived=schema.DISTRIBUTION,
        derived_detail="a code plugin is always distributed as a plugin",
    )

    c.record(
        "technical.required_plugins",
        DERIVED,
        "the descriptor's Plugins list plus every module its .Build.cs files use",
    )
    c.record(
        "technical.engine_plugins",
        DERIVED,
        "engine plugins traced from the .Build.cs module dependencies",
    )
    c.record("stats.blueprints", DERIVED, "counted from the plugin's .uasset files")
    c.record("stats.cpp_classes", DERIVED, "counted from the plugin's headers")

    media, _, _ = _media(c, plugin_id, media_root)

    c.record(
        "product_file",
        DERIVED if zip_facts else EMPTY,
        "the submission zip in the output folder"
        if zip_facts
        else "no submission zip has been built yet",
    )

    forum_has = c.pick("forum_post.has", derived=False)
    forum_url = c.pick("forum_post.url", derived="")

    declarations = {
        key: bool(c.pick(f"declarations.{key}", derived=default))
        for key, default in (
            ("edc_forum_post", False),
            ("mature", False),
            ("no_ai", True),
            ("generative_ai", False),
            ("promotional", False),
        )
    }

    faq = c.pick("faq", derived=[])
    changelog = c.pick(
        "changelog",
        derived=[{"version": plugin.version_name, "notes": ["Initial release."]}]
        if plugin.version_name
        else [],
        derived_detail=f"VersionName {plugin.version_name} in the descriptor",
    )

    c.record("fab", DERIVED, "the listing URL in the descriptor")

    listing = {
        "schema_version": SCHEMA_VERSION,
        "plugin_id": plugin_id,
        "title": str(title),
        "product_type": str(product_type),
        "category": str(category),
        "license": {
            "type": str(license_type),
            "price_personal": price_personal,
            "price_professional": price_professional,
            "currency": "USD",
        },
        "description": description,
        "tags": sorted({str(t) for t in tags}),
        "technical": {
            "engine_versions": sorted({str(v) for v in engine_versions}),
            "dev_platforms": sorted({str(p) for p in dev}),
            "target_platforms": sorted({str(p) for p in target_platforms}),
            "distribution": str(distribution),
            # Derived, but part of the technical text a reviewer reads, so a
            # change here is a change to the listing.
            "required_plugins": sorted(
                requirements.suite + requirements.unknown
            )
            if requirements
            else [],
            "engine_plugins": sorted(requirements.engine) if requirements else [],
        },
        "stats": {
            "blueprints": plugin.blueprint_count,
            "cpp_classes": plugin.cpp_class_count,
        },
        "media": media,
        "product_file": zip_facts.as_dict() if zip_facts else None,
        "forum_post": {"has": bool(forum_has), "url": str(forum_url or "")},
        "declarations": declarations,
        "faq": list(faq),
        "changelog": list(changelog),
        "fab": {
            "listing_url": plugin.listing_url,
            "product_id": plugin.fab_product_id,
            "is_live": plugin.is_live,
        },
        "plugin_version": plugin.version_name,
    }

    # The key order is the determinism guarantee, so assert it here rather than
    # trusting every future edit to keep the literal above in step.
    assert tuple(listing) == schema.KEY_ORDER, "listing keys drifted from KEY_ORDER"
    return listing, c.provenance


def tier_of(authored: dict, defaults: dict) -> str:
    value = authored.get("tier") or defaults.get("tier") or "premium"
    return str(value)


def is_publishable(authored: dict, defaults: dict) -> bool:
    """False only when a listing file explicitly opts the plugin out."""
    for data in (authored, defaults):
        if "publish" in data:
            return bool(data["publish"])
    return True
