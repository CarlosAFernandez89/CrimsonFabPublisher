from pathlib import Path

import pytest

from fabpublisher.dependencies import (
    classify_dependencies,
    resubmit_set,
    topological_order,
    transitive_dependencies,
    transitive_dependents,
)
from fabpublisher.discovery import discover_plugins
from fabpublisher.models import DependencyKind, PluginInfo


def _load(suite: Path) -> list[PluginInfo]:
    plugins = discover_plugins(suite)
    classify_dependencies(plugins, engine_builtins={"GameplayAbilities", "EnhancedInput"})
    return plugins


def test_classification(suite: Path):
    plugins = {p.name: p for p in _load(suite)}
    kinds = {d.name: d.kind for d in plugins["Ability"].dependencies}
    assert kinds["Common"] == DependencyKind.SUITE
    assert kinds["GameplayAbilities"] == DependencyKind.ENGINE
    assert kinds["ThirdParty"] == DependencyKind.EXTERNAL


def test_topological_order_deps_before_dependents(suite: Path):
    order = topological_order(_load(suite))
    assert order.index("Common") < order.index("Ability")
    assert order.index("Ability") < order.index("Core")


def test_transitive_dependents(suite: Path):
    plugins = _load(suite)
    # Changing Common must flag both Ability and Core downstream.
    assert transitive_dependents(plugins, ["Common"]) == {"Ability", "Core"}
    # Changing Ability flags only Core.
    assert transitive_dependents(plugins, ["Ability"]) == {"Core"}


def test_transitive_dependencies(suite: Path):
    plugins = _load(suite)
    # Building Core pulls in everything it needs, itself included.
    assert transitive_dependencies(plugins, ["Core"]) == {"Core", "Ability", "Common"}
    assert transitive_dependencies(plugins, ["Ability"]) == {"Ability", "Common"}
    assert transitive_dependencies(plugins, ["Common"]) == {"Common"}


def test_transitive_dependencies_ignores_unknown_names(suite: Path):
    plugins = _load(suite)
    # Engine/external deps are not suite members and must not appear as jobs.
    assert transitive_dependencies(plugins, ["Ability", "ThirdParty"]) == {
        "Ability",
        "Common",
    }
    assert transitive_dependencies(plugins, []) == set()


def test_transitive_dependencies_terminates_on_a_cycle(tmp_path: Path):
    import json

    root = tmp_path / "Plugins"
    for a, b in (("A", "B"), ("B", "A")):
        d = root / a
        (d / "Source").mkdir(parents=True)
        (d / f"{a}.uplugin").write_text(
            json.dumps({"Modules": [], "Plugins": [{"Name": b}]}), encoding="utf-8"
        )
    plugins = discover_plugins(root)
    assert transitive_dependencies(plugins, ["A"]) == {"A", "B"}


def test_resubmit_set_reasons(suite: Path):
    plugins = _load(suite)
    result = resubmit_set(plugins, ["Common"])
    assert result["Common"] == "changed"
    assert result["Ability"] == "dependency"
    assert result["Core"] == "dependency"


def test_cycle_detection(tmp_path: Path):
    import json

    root = tmp_path / "Plugins"
    for a, b in (("A", "B"), ("B", "A")):
        d = root / a
        (d / "Source").mkdir(parents=True)
        (d / f"{a}.uplugin").write_text(
            json.dumps({"Modules": [], "Plugins": [{"Name": b}]}), encoding="utf-8"
        )
    plugins = discover_plugins(root)
    with pytest.raises(Exception):
        topological_order(plugins)
