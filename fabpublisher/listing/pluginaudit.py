"""Check a plugin folder against Fab's packaging requirements.

This answers "would Fab reject the package itself", which is a different
question from "is the listing copy complete" and is worth knowing long before
any listing copy exists.

Every issue names the requirement that produced it, so a message can be taken
straight to Fab's document and checked. Like the rest of the domain layer this
returns data and never raises for a user-facing problem: an unreadable file
becomes a warning, not a traceback.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import DependencyKind, PluginInfo
from ..shipfilter import ShipFilter
from ..validation import Issue
from . import fabrules

#: Files 4.3.6.1.b calls "source and header files".
SOURCE_SUFFIXES = (".h", ".hpp", ".inl", ".c", ".cc", ".cpp", ".cs")

#: The boilerplate 4.3.6.1.b explicitly rules out.
_EPIC_NOTICE = re.compile(r"copyright\s+epic\s+games", re.I)
_COPYRIGHT = re.compile(r"copyright|\(c\)|©", re.I)
#: A year, so "Copyright MyCompany" alone does not pass.
_YEAR = re.compile(r"\b(19|20)\d{2}\b")

#: 4.3.7.1.c. Checked against the name with every extension removed - the dots
#: before extensions are obviously permitted, and UE uses two of them
#: ("MyModule.Build.cs"), so stripping only the last suffix flags every plugin
#: in the suite.
_ASCII_NAME = re.compile(r"^[A-Za-z0-9_]+$")


#: How many leading lines of a file count as "the header".
_HEADER_LINES = 8

#: Reporting more than this many instances of one rule buries the others.
_MAX_EXAMPLES = 5


def _bare_name(part: str) -> str:
    """A path component with all of its extensions removed."""
    return part.split(".", 1)[0]


def _shipped_files(plugin_path: Path, ship_filter: ShipFilter) -> list[Path]:
    """Every file that would actually end up in the zip."""
    files = []
    for path in plugin_path.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(plugin_path).as_posix()
        if not ship_filter.should_exclude(rel):
            files.append(path)
    return files


def _summarise(paths: list[str]) -> str:
    """List a few offenders and count the rest, so one rule can't flood."""
    shown = ", ".join(paths[:_MAX_EXAMPLES])
    extra = len(paths) - _MAX_EXAMPLES
    return f"{shown} and {extra} more" if extra > 0 else shown


def _has_copyright_header(path: Path) -> bool | None:
    """True/False, or None when the file could not be read."""
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            head = "".join(next(handle, "") for _ in range(_HEADER_LINES))
    except OSError:
        return None
    if _EPIC_NOTICE.search(head):
        return False
    return bool(_COPYRIGHT.search(head) and _YEAR.search(head))


def _descriptor_issues(plugin: PluginInfo) -> list[Issue]:
    issues: list[Issue] = []

    if not re.fullmatch(r"\d+\.\d+\.\d+", plugin.engine_version or ""):
        issues.append(
            Issue(
                "error",
                f"EngineVersion is {plugin.engine_version or 'missing'}; Fab "
                f"expects a full major.minor.patch value such as 5.8.0 "
                f"({fabrules.cite('engine-version')})",
                "EngineVersion",
            )
        )

    bare = [
        m.name
        for m in plugin.modules
        if not m.platform_allow_list and not m.platform_deny_list
    ]
    if bare:
        issues.append(
            Issue(
                "error",
                f"No PlatformAllowList or PlatformDenyList on module(s) "
                f"{_summarise(bare)} ({fabrules.cite('platform-list')})",
                "PlatformAllowList",
            )
        )

    if not plugin.fab_url:
        # Only fillable once the product exists, so this is never a blocker -
        # but a live listing with no FabURL is a real gap worth naming.
        detail = (
            "the listing is live, so its product id is available now"
            if plugin.is_live
            else "fill it in after the first submission"
        )
        issues.append(
            Issue(
                "warning",
                f"No FabURL in the descriptor - {detail} "
                f"({fabrules.cite('fab-url')})",
                "FabURL",
            )
        )

    suite_deps = plugin.suite_dependency_names
    if suite_deps:
        issues.append(
            Issue(
                "error",
                f"Depends on user-made plugin(s) {_summarise(suite_deps)}, which "
                f"Fab does not allow in a submitted plugin "
                f"({fabrules.cite('no-user-plugin-deps')})",
                "Plugins",
            )
        )

    return issues


def _tree_issues(plugin: PluginInfo, files: list[Path]) -> list[Issue]:
    issues: list[Issue] = []
    root = plugin.path

    too_long = [
        rel
        for path in files
        if len(rel := path.relative_to(root).as_posix()) > fabrules.PATH_MAX_CHARS
    ]
    if too_long:
        issues.append(
            Issue(
                "error",
                f"{len(too_long)} path(s) exceed {fabrules.PATH_MAX_CHARS} "
                f"characters: {_summarise(too_long)} "
                f"({fabrules.cite('path-length')})",
                "path-length",
            )
        )

    bad_names = sorted(
        {
            part
            for path in files
            for part in path.relative_to(root).parts
            if not _ASCII_NAME.fullmatch(_bare_name(part))
        }
    )
    if bad_names:
        issues.append(
            Issue(
                "error",
                f"Name(s) outside English alphanumerics and underscores: "
                f"{_summarise(bad_names)} ({fabrules.cite('ascii-names')})",
                "ascii-names",
            )
        )

    executables = [
        path.relative_to(root).as_posix()
        for path in files
        if path.suffix.lower() in (".exe", ".msi")
    ]
    if executables:
        issues.append(
            Issue(
                "error",
                f"Ships executable(s): {_summarise(executables)} "
                f"({fabrules.cite('no-executables')})",
                "no-executables",
            )
        )

    if not any(path.name.endswith(".Build.cs") for path in files):
        issues.append(
            Issue(
                "error",
                f"No *.Build.cs under Source/, so the plugin declares no C++ "
                f"module ({fabrules.cite('code-module')})",
                "code-module",
            )
        )

    extra_folders = sorted(
        {
            path.relative_to(root).parts[0]
            for path in files
            if len(path.relative_to(root).parts) > 1
            and path.relative_to(root).parts[0] not in fabrules.STANDARD_FOLDERS
        }
    )
    if extra_folders and not (root / "Config" / "FilterPlugin.ini").is_file():
        issues.append(
            Issue(
                "warning",
                f"Folder(s) {_summarise(extra_folders)} ship alongside the "
                f"standard ones but there is no Config/FilterPlugin.ini listing "
                f"them ({fabrules.cite('filter-plugin-ini')})",
                "filter-plugin-ini",
            )
        )

    return issues


def _copyright_issues(files: list[Path], root: Path) -> list[Issue]:
    missing: list[str] = []
    unreadable: list[str] = []
    for path in files:
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        result = _has_copyright_header(path)
        rel = path.relative_to(root).as_posix()
        if result is None:
            unreadable.append(rel)
        elif not result:
            missing.append(rel)

    issues: list[Issue] = []
    if missing:
        issues.append(
            Issue(
                "error",
                f"{len(missing)} source file(s) carry no publisher copyright "
                f"notice with a year: {_summarise(missing)} "
                f"({fabrules.cite('copyright-header')})",
                "copyright-header",
            )
        )
    if unreadable:
        issues.append(
            Issue(
                "warning",
                f"Could not read {len(unreadable)} source file(s) to check the "
                f"copyright notice: {_summarise(unreadable)}",
                "copyright-header",
            )
        )
    return issues


def audit_plugin(
    plugin: PluginInfo, ship_filter: ShipFilter | None = None
) -> list[Issue]:
    """Every packaging requirement this plugin currently fails.

    `plugin.dependencies` must already be classified for the user-made-plugin
    check to mean anything; an unclassified plugin simply reports no suite
    dependencies rather than guessing.
    """
    ship_filter = ship_filter or ShipFilter()
    if not plugin.path.is_dir():
        return [
            Issue("error", f"Plugin folder {plugin.path} does not exist", "path")
        ]

    files = _shipped_files(plugin.path, ship_filter)
    return [
        *_descriptor_issues(plugin),
        *_tree_issues(plugin, files),
        *_copyright_issues(files, plugin.path),
    ]


def blocking_dependency_names(plugin: PluginInfo) -> list[str]:
    """Suite dependencies that make this plugin unsubmittable under 4.3.6.d."""
    return [
        dep.name for dep in plugin.dependencies if dep.kind == DependencyKind.SUITE
    ]
