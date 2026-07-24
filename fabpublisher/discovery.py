"""Discover plugins in a folder and enumerate engine built-in plugins."""

from __future__ import annotations

from pathlib import Path

from .models import PluginInfo
from .uplugin import parse_uplugin


def discover_plugins(root: Path) -> list[PluginInfo]:
    """Find every `<root>/<PluginName>/<PluginName>.uplugin` under `root`.

    Malformed descriptors are skipped rather than aborting the whole scan.
    """
    root = Path(root)
    plugins: list[PluginInfo] = []
    if not root.is_dir():
        return plugins
    for uplugin in sorted(root.glob("*/*.uplugin")):
        try:
            plugins.append(parse_uplugin(uplugin))
        except (OSError, ValueError):
            continue
    return plugins


def engine_builtin_plugin_names(engine_root: Path) -> set[str]:
    """Set of plugin names that ship inside `<engine>/Engine/Plugins`."""
    engine_plugins = Path(engine_root) / "Engine" / "Plugins"
    names: set[str] = set()
    if not engine_plugins.is_dir():
        return names
    for uplugin in engine_plugins.rglob("*.uplugin"):
        names.add(uplugin.stem)
    return names
