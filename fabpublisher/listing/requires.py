"""Work out which plugins a plugin actually needs.

Fab requires the listing to state its prerequisites, and reviewers have asked
for the full set — not only the other publisher plugins, but the engine ones
too. The `.uplugin` alone does not tell you: a module can depend on
`GameplayAbilities` in its `.Build.cs` while the descriptor never mentions the
plugin that provides it.

So this reads both, and maps module names back to the plugin that owns them by
looking at every `.uplugin` in the engine. A module nobody claims is a core
engine module (`Core`, `Engine`, `UMG`) and is not a plugin at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..models import DependencyKind, PluginInfo

#: `PublicDependencyModuleNames.AddRange(new string[] { "A", "B" })` and the
#: private form. Also matches the `.Add("X")` singular spelling.
_ADD_RANGE = re.compile(
    r"(?:Public|Private)DependencyModuleNames\s*\.\s*AddRange\s*\("
    r".*?\{(?P<body>.*?)\}",
    re.S,
)
_ADD_ONE = re.compile(
    r"(?:Public|Private)DependencyModuleNames\s*\.\s*Add\s*\(\s*\"(?P<name>[^\"]+)\""
)
_STRING = re.compile(r'"([^"]+)"')
#: `//` to end of line, and `/* ... */`. UE Build.cs files annotate heavily.
_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


@dataclass(frozen=True)
class Requirements:
    """Everything the listing needs to say about prerequisites."""

    #: Plugins by another publisher — in this app's terms, the rest of the
    #: suite. These are the ones a reviewer always wants named.
    suite: tuple[str, ...] = ()
    #: Plugins that ship with Unreal. Some reviewers want these listed too.
    engine: tuple[str, ...] = ()
    #: Named in a .Build.cs but owned by no plugin the app can see.
    unknown: tuple[str, ...] = ()
    #: Modules that belong to the engine itself rather than to any plugin.
    core_modules: tuple[str, ...] = field(default=(), repr=False)

    @property
    def required(self) -> tuple[str, ...]:
        """What must be installed before this plugin works."""
        return tuple(sorted({*self.suite, *self.engine, *self.unknown}))


def module_names(build_cs: str) -> set[str]:
    """Module names a `.Build.cs` depends on.

    Comments go first: nearly every line in a real Build.cs carries a trailing
    `// why`, and one of those saying `"Foo"` would otherwise be read as a
    dependency.
    """
    text = _COMMENTS.sub(" ", build_cs)
    names: set[str] = set()
    for match in _ADD_RANGE.finditer(text):
        names.update(_STRING.findall(match.group("body")))
    names.update(match.group("name") for match in _ADD_ONE.finditer(text))
    return names


def modules_used(plugin: PluginInfo) -> set[str]:
    """Every module named across all of a plugin's `.Build.cs` files."""
    names: set[str] = set()
    source = plugin.path / "Source"
    if not source.is_dir():
        return names
    for build_cs in source.rglob("*.Build.cs"):
        try:
            names.update(module_names(build_cs.read_text(encoding="utf-8-sig")))
        except OSError:
            continue
    # A plugin's own modules are not prerequisites.
    return names - {module.name for module in plugin.modules}


def module_owners(uplugin_paths: list[Path]) -> dict[str, str]:
    """Map module name -> owning plugin, from a set of `.uplugin` files.

    Built once per scan and handed in, because rglobbing the engine's plugin
    tree is far too slow to repeat per plugin.
    """
    import json

    owners: dict[str, str] = {}
    for path in uplugin_paths:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        owner = Path(path).stem
        for module in data.get("Modules") or []:
            name = module.get("Name")
            if name:
                owners.setdefault(name, owner)
    return owners


def engine_uplugins(engine_root: Path | None) -> list[Path]:
    """Every `.uplugin` shipped with the engine."""
    if engine_root is None:
        return []
    plugins = Path(engine_root) / "Engine" / "Plugins"
    if not plugins.is_dir():
        return []
    return list(plugins.rglob("*.uplugin"))


def resolve(
    plugin: PluginInfo,
    owners: dict[str, str],
    engine_plugin_names: set[str],
    suite_names: set[str],
) -> Requirements:
    """Split this plugin's prerequisites into suite, engine and unknown.

    Descriptor dependencies and `.Build.cs` module dependencies are merged: the
    descriptor is authoritative about plugins, the Build.cs catches the ones it
    forgot to declare.
    """
    suite: set[str] = set()
    engine: set[str] = set()
    unknown: set[str] = set()
    core: set[str] = set()

    # The descriptor names plugins directly.
    for dependency in plugin.dependencies:
        if dependency.kind == DependencyKind.SUITE:
            suite.add(dependency.name)
        elif dependency.kind == DependencyKind.ENGINE:
            engine.add(dependency.name)
        else:
            unknown.add(dependency.name)
    for name in plugin.dependency_names:
        if not any(d.name == name for d in plugin.dependencies):
            unknown.add(name)

    # Build.cs names modules, which have to be traced back to their plugin.
    for module in modules_used(plugin):
        owner = owners.get(module)
        if owner is None:
            # Nobody claims it, so it is part of the engine proper.
            core.add(module)
        elif owner in suite_names and owner != plugin.name:
            suite.add(owner)
        elif owner in engine_plugin_names:
            engine.add(owner)
        elif owner != plugin.name:
            unknown.add(owner)

    unknown -= suite | engine
    return Requirements(
        suite=tuple(sorted(suite)),
        engine=tuple(sorted(engine)),
        unknown=tuple(sorted(unknown)),
        core_modules=tuple(sorted(core)),
    )
