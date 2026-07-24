"""Classify plugin dependencies and compute build order / resubmission impact."""

from __future__ import annotations

from collections.abc import Iterable
from graphlib import TopologicalSorter

from .models import Dependency, DependencyKind, PluginInfo


def classify_dependencies(
    plugins: list[PluginInfo], engine_builtins: set[str]
) -> list[PluginInfo]:
    """Populate each plugin's `dependencies` with a resolved kind.

    SUITE   -> another plugin in this folder (drives build order)
    ENGINE  -> ships with the selected engine
    EXTERNAL-> neither; must be installed separately (surfaced as a warning)
    """
    suite_names = {p.name for p in plugins}
    for plugin in plugins:
        resolved: list[Dependency] = []
        for name in plugin.dependency_names:
            if name in suite_names:
                kind = DependencyKind.SUITE
            elif name in engine_builtins:
                kind = DependencyKind.ENGINE
            else:
                kind = DependencyKind.EXTERNAL
            resolved.append(Dependency(name=name, kind=kind))
        plugin.dependencies = resolved
    return plugins


def _suite_dep_map(plugins: list[PluginInfo]) -> dict[str, set[str]]:
    """name -> set of sibling-plugin names it depends on."""
    suite_names = {p.name for p in plugins}
    return {
        p.name: {n for n in p.dependency_names if n in suite_names} for p in plugins
    }


def topological_order(plugins: list[PluginInfo]) -> list[str]:
    """Plugin names in build order (dependencies before dependents).

    Raises `graphlib.CycleError` if the suite dependency graph has a cycle.
    """
    sorter = TopologicalSorter(_suite_dep_map(plugins))
    return list(sorter.static_order())


def transitive_dependents(
    plugins: list[PluginInfo], changed: Iterable[str]
) -> set[str]:
    """All plugins downstream of `changed` (transitive), excluding `changed`."""
    changed = set(changed)
    dep_map = _suite_dep_map(plugins)
    dependents: dict[str, set[str]] = {p.name: set() for p in plugins}
    for name, deps in dep_map.items():
        for dep in deps:
            if dep in dependents:
                dependents[dep].add(name)

    result: set[str] = set()
    stack = list(changed)
    while stack:
        current = stack.pop()
        for downstream in dependents.get(current, ()):
            if downstream not in result and downstream not in changed:
                result.add(downstream)
                stack.append(downstream)
    return result


def transitive_dependencies(
    plugins: list[PluginInfo], roots: Iterable[str]
) -> set[str]:
    """All suite plugins `roots` depend on (transitive), including `roots` itself.

    The forward mirror of `transitive_dependents`. Names not present in
    `plugins` are ignored. Safe on a cyclic graph.
    """
    dep_map = _suite_dep_map(plugins)
    result: set[str] = set()
    stack = [name for name in roots if name in dep_map]
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(dep for dep in dep_map[current] if dep not in result)
    return result


def resubmit_set(
    plugins: list[PluginInfo], changed: Iterable[str]
) -> dict[str, str]:
    """Map plugin name -> reason, for everything that must be rebuilt/resubmitted.

    Reason is "changed" for directly-modified plugins and "dependency" for
    plugins that only need a rebuild because something they depend on changed.
    """
    changed = set(changed)
    out: dict[str, str] = {name: "changed" for name in changed}
    for name in transitive_dependents(plugins, changed):
        out.setdefault(name, "dependency")
    return out
