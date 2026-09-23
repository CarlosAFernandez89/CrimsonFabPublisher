"""Predict the longest path a BuildPlugin run will create, before running it.

UBT refuses any action whose file path is 260 characters or longer on a Windows
host (`ActionGraph.CheckPathLengths`), and it only finds out after UAT has
spent time setting up the host project. Every one of those paths is derivable
from the sources, so the check can run up front instead.

The long paths all live in the throwaway host project, which holds the target
plugin *and* a copy of each suite dependency:

    <work>\\<Job>_Build\\HostProject\\Plugins\\<Plugin>\\Intermediate\\Build\\Win64\\
        x64\\UnrealEditor\\Development\\<Module>\\<File>.cpp.dep.json

Editor/Development is the deepest configuration and `.dep.json` the longest
suffix UBT adds to a compiled file (observed against a real UE 5.8 build).
"""

from __future__ import annotations

from pathlib import Path

#: UBT fails on a path of this length or more.
MAX_PATH = 260

_OBJ_DIR = Path("Intermediate/Build/Win64/x64/UnrealEditor/Development")
_UHT_DIR = Path("Intermediate/Build/Win64/UnrealEditor/Inc")


def _module_name(file: Path, source_root: Path) -> str:
    """The module a source file compiles into: its nearest `*.Build.cs`."""
    for folder in file.parents:
        if folder == source_root or source_root not in folder.parents:
            break
        rules = next(folder.glob("*.Build.cs"), None)
        if rules is not None:
            return rules.name[: -len(".Build.cs")]
    return file.relative_to(source_root).parts[0]


def _has_uht_header(header: Path) -> bool:
    try:
        return '.generated.h"' in header.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def longest_intermediate(plugin_dir: Path) -> str:
    """The longest path UBT will create for this plugin, relative to the
    plugin folder. Empty when the plugin has no code."""
    source = Path(plugin_dir) / "Source"
    if not source.is_dir():
        return ""
    longest = ""
    for file in source.rglob("*"):
        suffix = file.suffix.lower()
        if suffix in (".cpp", ".c"):
            module = _module_name(file, source)
            candidates = [_OBJ_DIR / module / f"{file.name}.dep.json"]
        elif suffix == ".h" and _has_uht_header(file):
            module = _module_name(file, source)
            candidates = [
                _UHT_DIR / module / "UHT" / f"{file.stem}.generated.h",
                _OBJ_DIR / module / f"Module.{module}.gen.cpp.dep.json",
            ]
        else:
            continue
        for rel in map(str, candidates):
            if len(rel) > len(longest):
                longest = rel
    return longest
