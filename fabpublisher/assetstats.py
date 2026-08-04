"""Count Blueprints and C++ classes for the Fab submission form.

Fab's "Tools and plugins" section asks for a Blueprint count and a C++ class
count per submission. Both are derived from the plugin on disk so the numbers
stay honest as the plugin changes.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Every Blueprint flavour's generated class ends in this — `UBlueprintGeneratedClass`,
#: `UWidgetBlueprintGeneratedClass`, `UAnimBlueprintGeneratedClass` and friends — so
#: one marker covers them all.
_BP_CLASS_MARKER = b"BlueprintGeneratedClass"

_HEADER_SUFFIXES = (".h", ".hpp")

#: Vendored headers under Source/ThirdParty are not the plugin's own classes.
_EXCLUDED_SOURCE_DIRS = {"thirdparty"}

_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)

#: A class/struct *definition*: optional template header, optional MYPLUGIN_API
#: export macro, then the name followed by a base-class list or an opening brace.
#: A forward declaration (`class UFoo;`) is followed by `;` and so does not match,
#: and `enum class EFoo` cannot match because `enum` precedes `class`.
_CLASS_DEF = re.compile(
    r"^[ \t]*(?:template[ \t]*<[^>\n]*>[ \t\r\n]*)?"
    r"(?:class|struct)[ \t]+"
    r"(?:[A-Z][A-Z0-9_]*_API[ \t]+)?"
    r"[A-Za-z_]\w*"
    r"[ \t]*(?:final[ \t]*)?(?::|\{|$)",
    re.MULTILINE,
)


def _scan_for(path: Path, needles: tuple[bytes, ...], chunk: int = 1 << 20) -> bool:
    """True when every byte string in `needles` appears somewhere in `path`.

    Streamed rather than read whole: a Content folder is mostly textures and
    meshes, and those must not be pulled into memory to answer this question.
    """
    remaining = set(needles)
    overlap = max(len(n) for n in needles) - 1
    tail = b""
    try:
        with path.open("rb") as handle:
            while remaining:
                block = handle.read(chunk)
                if not block:
                    break
                window = tail + block
                remaining = {n for n in remaining if n not in window}
                tail = window[-overlap:] if overlap else b""
    except OSError:
        return False
    return not remaining


def is_blueprint_asset(path: Path) -> bool:
    """Whether a `.uasset` is itself a Blueprint.

    Naming-independent: it reads the package rather than trusting a prefix.

    Requiring `<stem>_C` — the name UE gives a Blueprint's own generated class —
    is what keeps referencing assets out. A DataTable pointing at `B_Manager`
    also carries `BlueprintGeneratedClass` and `B_Manager_C` in its name table,
    but its own stem is `DT_Items`, so it fails the second marker.
    """
    path = Path(path)
    own_class = path.stem.encode("utf-8", "ignore") + b"_C"
    return _scan_for(path, (_BP_CLASS_MARKER, own_class))


def count_blueprints(plugin_path: Path) -> int:
    """Blueprint assets under the plugin's `Content/` folder.

    Levels (`.umap`) are excluded — a map is not a Blueprint, and it would
    otherwise match on the actors it references.
    """
    content = Path(plugin_path) / "Content"
    if not content.is_dir():
        return 0
    return sum(
        1
        for asset in content.rglob("*.uasset")
        if asset.is_file() and is_blueprint_asset(asset)
    )


def count_cpp_classes(plugin_path: Path) -> int:
    """Every class and struct defined in the plugin's headers.

    Counts declarations whether or not they carry a reflection macro, so
    internal helper types are included alongside `UCLASS`/`USTRUCT` types.
    """
    source = Path(plugin_path) / "Source"
    if not source.is_dir():
        return 0

    total = 0
    for header in source.rglob("*"):
        if header.suffix.lower() not in _HEADER_SUFFIXES or not header.is_file():
            continue
        parts = {p.lower() for p in header.relative_to(source).parts[:-1]}
        if parts & _EXCLUDED_SOURCE_DIRS:
            continue
        try:
            text = header.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Strip comments first: a commented-out or illustrative declaration is
        # not a class the plugin ships.
        total += len(_CLASS_DEF.findall(_COMMENTS.sub("", text)))
    return total
