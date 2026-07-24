"""Scan pipeline: discovery, classification, build order, change impact.

Returns data; never logs and never raises for user-facing problems. A
dependency cycle comes back as `ScanResult.cycle_error` rather than a dialog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from graphlib import CycleError
from pathlib import Path

from .dependencies import classify_dependencies, resubmit_set, topological_order
from .discovery import discover_plugins, engine_builtin_plugin_names
from .models import DependencyKind, EngineInfo, PluginInfo, PluginStatus
from .state import StateStore, compute_changes
from .validation import Issue, validate_plugin


@dataclass(frozen=True)
class ScanResult:
    """Everything one scan of the plugins folder produced."""

    root: Path
    plugins: list[PluginInfo] = field(default_factory=list)
    hashes: dict[str, str] = field(default_factory=dict)
    changed: set[str] = field(default_factory=set)
    impact: dict[str, str] = field(default_factory=dict)
    issues: dict[str, list[Issue]] = field(default_factory=dict)
    cycle_error: str | None = None
    #: False when the root was unset or not a directory — nothing was looked at.
    scanned: bool = False

    @property
    def resubmit_only(self) -> list[str]:
        """Names that need a rebuild only because a dependency changed."""
        return sorted(n for n, r in self.impact.items() if r == "dependency")

    def names_with_status(self, *statuses: PluginStatus) -> set[str]:
        return {p.name for p in self.plugins if p.status in statuses}


class ScanService:
    """Owns the scan pipeline and the per-engine builtin-plugin cache."""

    def __init__(self, store: StateStore):
        self.store = store
        self._builtin_cache: dict[str, set[str]] = {}

    def engine_builtins(self, engine: EngineInfo | None) -> set[str]:
        if engine is None:
            return set()
        key = str(engine.root)
        if key not in self._builtin_cache:
            self._builtin_cache[key] = engine_builtin_plugin_names(engine.root)
        return self._builtin_cache[key]

    def scan(self, root: Path | str | None, engine: EngineInfo | None) -> ScanResult:
        # Guard the empty root explicitly: Path("") is Path("."), so falling
        # through would silently scan the working directory.
        if not root:
            return ScanResult(root=Path())
        root = Path(root)
        if not root.is_dir():
            return ScanResult(root=root)

        plugins = discover_plugins(root)
        classify_dependencies(plugins, self.engine_builtins(engine))

        cycle_error: str | None = None
        try:
            order_index = {
                name: i for i, name in enumerate(topological_order(plugins))
            }
        except CycleError as exc:
            cycle_error = str(exc)
            order_index = {}

        for plugin in plugins:
            plugin.order = order_index.get(plugin.name, 0)
        plugins.sort(key=lambda p: (p.order, p.name))

        hashes, changed = compute_changes(plugins, self.store)
        impact = resubmit_set(plugins, changed)

        engine_version = engine.version if engine else None
        issues: dict[str, list[Issue]] = {}
        for plugin in plugins:
            plugin.status = _status_for(plugin, impact.get(plugin.name))
            found = validate_plugin(plugin, engine_version)
            if found:
                issues[plugin.name] = found

        return ScanResult(
            root=root,
            plugins=plugins,
            hashes=hashes,
            changed=changed,
            impact=impact,
            issues=issues,
            cycle_error=cycle_error,
            scanned=True,
        )


def _status_for(plugin: PluginInfo, reason: str | None) -> PluginStatus:
    """An unresolvable dependency outranks change state — it predicts a hard failure."""
    if any(d.kind is DependencyKind.EXTERNAL for d in plugin.dependencies):
        return PluginStatus.MISSING_DEP
    if reason == "changed":
        return PluginStatus.CHANGED
    if reason == "dependency":
        return PluginStatus.NEEDS_RESUBMIT
    return PluginStatus.UP_TO_DATE
