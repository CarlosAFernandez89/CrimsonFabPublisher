"""Fab's published requirements, written down exactly once.

Everything the app claims Fab wants lives in this table. The validator checks
against it and the Ask-Claude prompt is generated from it, so the two cannot
drift into disagreeing about what a passing listing looks like.

Each rule records where it came from. A number quoted from Fab's technical
requirements and a number read off the publisher portal are both useful, but
they are not equally trustworthy and must never look alike in the code - hence
`confidence`. DOCUMENTED rules cite their section; OBSERVED ones cannot,
because the document does not contain them.

Source: https://www.fab.com/o/technical-requirements (last updated 2026-03-17).
"""

from __future__ import annotations

from dataclasses import dataclass

DOCUMENTED = "documented"
OBSERVED = "observed"

#: What a rule constrains - the package on disk, the listing copy, or the
#: media. COPY rules are the ones rendered into the drafting prompt.
PACKAGE = "package"
COPY = "copy"
MEDIA = "media"


@dataclass(frozen=True)
class Rule:
    id: str
    text: str
    applies_to: str
    confidence: str = DOCUMENTED
    #: Section number in the technical requirements. Documented rules always
    #: have one; observed rules never do.
    section: str = ""

    @property
    def citation(self) -> str:
        return f"Fab {self.section}" if self.section else "Fab publisher portal"


RULES: tuple[Rule, ...] = (
    # ---------------------------------------------------------------- package
    Rule(
        "engine-version",
        'The .uplugin must declare an "EngineVersion" naming the major engine '
        "version it installs to, for example 5.8.0.",
        PACKAGE,
        section="4.3.6.a",
    ),
    Rule(
        "platform-list",
        'Every module in the .uplugin must declare a "PlatformAllowList" or '
        '"PlatformDenyList" naming the platforms it is built for.',
        PACKAGE,
        section="4.3.6.b",
    ),
    Rule(
        "fab-url",
        'The .uplugin must declare a "FabURL" whose value is the product id '
        "from the end of the Publisher Portal URL. It can only be filled in "
        "once the product has been submitted.",
        PACKAGE,
        section="4.3.6.c",
    ),
    Rule(
        "no-user-plugin-deps",
        "Plugins may depend on plugins shipped with Unreal Engine, but must "
        "not depend on other user-made Unreal Engine plugins.",
        PACKAGE,
        section="4.3.6.d",
    ),
    Rule(
        "copyright-header",
        "Every source and header file must carry a commented copyright notice "
        "naming the publisher and the year of intended publishing, and not the "
        "auto-generated Epic Games text.",
        PACKAGE,
        section="4.3.6.1.b",
    ),
    Rule(
        "code-module",
        "A plugin must contain at least one module of C++ code.",
        PACKAGE,
        section="4.3.6.1.c",
    ),
    Rule(
        "no-executables",
        "Plugins must not distribute .exe or .msi files.",
        PACKAGE,
        section="4.3.6.1.e",
    ),
    Rule(
        "ascii-names",
        "Folder and file names must contain only English alphanumeric "
        "characters and underscores.",
        PACKAGE,
        section="4.3.7.1.c",
    ),
    Rule(
        "no-local-folders",
        "The submitted plugin folder must not contain unused or local folders "
        "such as Binaries, Build, Intermediate or Saved.",
        PACKAGE,
        section="4.3.7.3.a",
    ),
    Rule(
        "filter-plugin-ini",
        "Any distributed folder other than Config, Content, Resources or "
        "Source must be listed in a Config/FilterPlugin.ini.",
        PACKAGE,
        section="4.3.7.3.b",
    ),
    Rule(
        "path-length",
        "Measured from the plugin folder, every file path must be 170 "
        "characters or fewer.",
        PACKAGE,
        section="4.3.7.3.c",
    ),
    # ------------------------------------------------------------------- copy
    Rule(
        "english",
        "All text must be in English with correct spelling and proper grammar.",
        COPY,
        section="1.8.1.a",
    ),
    Rule(
        "relevant-category",
        "A product must sit in the category most relevant to its functionality "
        "and style.",
        COPY,
        section="1.8.2.a",
    ),
    Rule(
        "technical-fields",
        "All relevant Technical Information fields must be filled out, and the "
        "text must identify any dependencies, prerequisites or other "
        "requirements for use of the asset.",
        COPY,
        section="1.8.4.a/b",
    ),
    Rule(
        "relevant-tags",
        "Tags must be accurate and relevant to the asset.",
        COPY,
        section="1.8.5.a",
    ),
    Rule(
        "blueprint-demo",
        "A Blueprint-based product must include a downloadable demo project or "
        "a video URL in the long description showing what it does.",
        COPY,
        section="4.1.1.c",
    ),
    Rule(
        "plugin-purpose",
        "A plugin must introduce new editor functionality, integrate Unreal "
        "with third-party systems, or expose complex gameplay logic to "
        "Blueprints, and the description should make clear which one it does.",
        COPY,
        section="4.3.6.1.d",
    ),
    Rule(
        "three-content-areas",
        "The description must cover what the product is, how to use it, and "
        "its technical details and prerequisites.",
        COPY,
        confidence=OBSERVED,
    ),
    Rule(
        "plain-prose",
        "The description is rich text, but markdown source is not rendered: "
        "pasted asterisks and backticks appear literally. Use only the app's "
        "description markup - '## ' headings, '- ' bullets, **bold** and "
        "[text](https://...) links - which the app converts to Fab's "
        "formatting when the description is copied.",
        COPY,
        confidence=OBSERVED,
    ),
    Rule(
        "block-structure",
        "The description is entered as structured text blocks, so it must be "
        "written as short sections under headings rather than one continuous "
        "paragraph. Pictures belong to the media gallery, not the description.",
        COPY,
        confidence=OBSERVED,
    ),
    Rule(
        "title-length",
        "The title field accepts up to 80 characters, and Fab recommends 30 or "
        "fewer.",
        COPY,
        confidence=OBSERVED,
    ),
    Rule(
        "tag-count",
        "A listing takes at most 25 tags, entered one at a time.",
        COPY,
        confidence=OBSERVED,
    ),
    Rule(
        "tag-picker",
        "Tags are chosen from Fab's own picker, not typed freely, so suggest "
        "short conventional marketplace terms that a picker is likely to "
        "already contain. Anything the picker does not offer simply cannot be "
        "used.",
        COPY,
        confidence=OBSERVED,
    ),
    # ------------------------------------------------------------------ media
    Rule(
        "media-accurate",
        "Images and models must accurately display the contents of the product.",
        MEDIA,
        section="1.8.6.a",
    ),
    Rule(
        "thumbnail-spec",
        "The thumbnail must be a .png, .jpg or .jpeg of at least 1920x1080 and "
        "no more than 3 MB.",
        MEDIA,
        confidence=OBSERVED,
    ),
    Rule(
        "gallery-spec",
        "The media gallery needs at least one item and takes at most 24 files; "
        "2D images must total under 25 MB.",
        MEDIA,
        confidence=OBSERVED,
    ),
)

_BY_ID = {rule_.id: rule_ for rule_ in RULES}


def rule(rule_id: str) -> Rule:
    """The rule with this id. Raises KeyError, because an unknown id is a typo."""
    return _BY_ID[rule_id]


def cite(rule_id: str) -> str:
    """A short source tag to append to a message, e.g. "Fab 4.3.6.d"."""
    return _BY_ID[rule_id].citation


def rules_for(applies_to: str) -> tuple[Rule, ...]:
    return tuple(r for r in RULES if r.applies_to == applies_to)


# --------------------------------------------------------------------- limits
# The numbers behind the OBSERVED rules above, kept here so the validator and
# the drafting prompt quote the same figures.

TITLE_MAX = 80
TITLE_RECOMMENDED = 30
TAGS_MAX = 25
TAG_CHARS_MAX = 24
TAGS_THIN = 5
DESCRIPTION_THIN = 400

THUMBNAIL_FORMATS = (".png", ".jpg", ".jpeg")
THUMBNAIL_MIN_WIDTH = 1920
THUMBNAIL_MIN_HEIGHT = 1080
THUMBNAIL_MAX_BYTES = 3 * 1024 * 1024

GALLERY_MAX_ITEMS = 24
GALLERY_MAX_BYTES = 25 * 1024 * 1024

#: 4.3.7.3.c, and the one documented limit that is a hard integer.
PATH_MAX_CHARS = 170

#: 4.3.7.3.a - folders that belong in a submitted plugin without needing a
#: FilterPlugin.ini entry (4.3.7.3.b).
STANDARD_FOLDERS = ("Config", "Content", "Resources", "Source")
