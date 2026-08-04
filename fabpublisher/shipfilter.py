"""Gitignore-style exclusion filter applied when composing a submission zip."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable

# Always stripped from a submission regardless of user settings. These are
# build artifacts / VCS metadata that must never ship to FAB, plus markdown:
# authoring notes sit interleaved with shipping content at arbitrary depth
# (Resources/Wiki/Images/<Plugin>/PNGRequirements.md), so matching by
# extension everywhere is the only rule that cannot be outrun by a new file
# in a new folder. Nothing UE loads at runtime is markdown.
DEFAULT_PATTERNS: tuple[str, ...] = (
    "Binaries/",
    "Intermediate/",
    "Saved/",
    "DerivedDataCache/",
    ".git/",
    "*.md",
)


class ShipFilter:
    """Decide whether a plugin-relative path should be excluded from the zip.

    Supported pattern forms (a practical subset of `.gitignore`):
      * ``Docs/``          - directory: excludes anything under a matching dir
      * ``Source/*/x.cpp`` - path glob relative to the plugin root
      * ``*.md`` / ``.DS_Store`` - filename glob, matched at any depth
    Blank lines and lines starting with ``#`` are ignored.
    """

    def __init__(self, patterns: Iterable[str] | None = None):
        self.patterns: list[str] = list(DEFAULT_PATTERNS)
        for raw in patterns or ():
            pat = raw.strip().replace("\\", "/")
            if pat and not pat.startswith("#"):
                self.patterns.append(pat)

    def should_exclude(self, relpath: str) -> bool:
        rel = relpath.replace("\\", "/").strip("/")
        if not rel:
            return False
        parts = rel.split("/")
        name = parts[-1]
        dirs = parts[:-1]

        for pat in self.patterns:
            if pat.endswith("/"):
                # Directory pattern: exclude if any parent dir matches. A
                # multi-segment pattern ("Resources/Wiki/") has to be matched
                # against a run of that many components — testing it against
                # single components can never hit, so it silently excluded
                # nothing.
                dir_glob = pat[:-1]
                span = dir_glob.count("/") + 1
                if any(
                    fnmatch.fnmatch("/".join(dirs[i : i + span]), dir_glob)
                    for i in range(len(dirs) - span + 1)
                ):
                    return True
            elif "/" in pat:
                # Path glob relative to the plugin root.
                if fnmatch.fnmatch(rel, pat):
                    return True
            else:
                # Filename glob at any depth.
                if fnmatch.fnmatch(name, pat):
                    return True
        return False
