"""Dependent plugins build against published artifacts, and are gated on them."""

from __future__ import annotations

from pathlib import Path

from fabpublisher.builder import (
    BUILT_DIRNAME,
    built_uplugin,
    deposit_built,
    missing_built_dependencies,
    run_build,
)
from fabpublisher.models import EngineInfo, Platform, PluginInfo
from fabpublisher.shipfilter import ShipFilter
from fabpublisher.ui.build_controller import preflight, unbuildable_dependencies

ENGINE = EngineInfo(identifier="UE_5.8", version="5.8", root=Path("F:/UE_5.8"))


def _plugin(name: str, deps: list[str] | None = None, order: int = 0) -> PluginInfo:
    return PluginInfo(
        name=name,
        path=Path("F:/Plugins") / name,
        uplugin_path=Path("F:/Plugins") / name / f"{name}.uplugin",
        dependency_names=deps or [],
        order=order,
    )


def _publish(output_dir: Path, name: str) -> None:
    """Stand in for a completed build of `name`."""
    target = output_dir / BUILT_DIRNAME / name
    (target / "Binaries" / "Win64").mkdir(parents=True, exist_ok=True)
    (target / f"{name}.uplugin").write_text("{}", encoding="utf-8")


# ---- publishing ---------------------------------------------------------
def test_deposit_publishes_the_unfiltered_build(tmp_path):
    """Dependents need Binaries and generated headers, which the zip strips."""
    out = tmp_path / "Core_Build"
    (out / "Binaries" / "Win64").mkdir(parents=True)
    (out / "Binaries" / "Win64" / "Core.dll").write_text("dll", encoding="utf-8")
    (out / "Intermediate" / "Build" / "Inc").mkdir(parents=True)
    (out / "Intermediate" / "Build" / "Inc" / "Core.gen.h").write_text("h", encoding="utf-8")
    (out / "Core.uplugin").write_text("{}", encoding="utf-8")

    deposit_built(out, tmp_path / "sub", "Core", log=lambda _: None)

    published = tmp_path / "sub" / BUILT_DIRNAME / "Core"
    assert (published / "Core.uplugin").is_file()
    assert (published / "Binaries" / "Win64" / "Core.dll").is_file()
    assert (published / "Intermediate" / "Build" / "Inc" / "Core.gen.h").is_file()


def test_deposit_replaces_a_previous_publish(tmp_path):
    out = tmp_path / "Core_Build"
    out.mkdir()
    (out / "Core.uplugin").write_text("{}", encoding="utf-8")
    sub = tmp_path / "sub"

    deposit_built(out, sub, "Core", log=lambda _: None)
    stale = sub / BUILT_DIRNAME / "Core" / "stale.txt"
    stale.write_text("old", encoding="utf-8")

    deposit_built(out, sub, "Core", log=lambda _: None)
    assert not stale.exists()


def test_missing_built_dependencies_lists_only_unpublished(tmp_path):
    _publish(tmp_path, "Common")
    deps = [_plugin("Common"), _plugin("Inventory")]
    assert missing_built_dependencies(tmp_path, deps) == ["Inventory"]


# ---- the gate -----------------------------------------------------------
def test_run_build_refuses_when_a_dependency_is_unbuilt(tmp_path):
    """No RunUAT call at all — the engine path here does not even exist."""
    result = run_build(
        engine=ENGINE,
        plugin=_plugin("Editor", ["Common"]),
        platforms=Platform.WIN64,
        work_root=tmp_path / "work",
        ship_filter=ShipFilter(),
        output_dir=tmp_path / "sub",
        log=lambda _: None,
        dependencies=[_plugin("Common")],
    )
    assert not result.success
    assert "Common" in result.message
    assert BUILT_DIRNAME in result.message


def test_preflight_blocks_a_dependent_whose_dependency_is_unbuilt(tmp_path):
    common = _plugin("Common", order=0)
    editor = _plugin("Editor", ["Common"], order=1)
    checks = preflight(
        ENGINE, Platform.WIN64, {"Editor"}, [editor], None, tmp_path, [common, editor]
    )
    assert not checks.ok
    assert any("Editor needs Common" in b.message for b in checks.blockers)


def test_preflight_allows_it_once_the_dependency_is_published(tmp_path):
    _publish(tmp_path, "Common")
    common = _plugin("Common", order=0)
    editor = _plugin("Editor", ["Common"], order=1)
    checks = preflight(
        ENGINE, Platform.WIN64, {"Editor"}, [editor], None, tmp_path, [common, editor]
    )
    assert checks.ok


def test_building_the_whole_suite_at_once_is_allowed(tmp_path):
    """Nothing is published yet, but the queue is in dependency order."""
    common = _plugin("Common", order=0)
    core = _plugin("Core", ["Common"], order=1)
    editor = _plugin("Editor", ["Core"], order=2)
    plugins = [common, core, editor]
    checks = preflight(
        ENGINE, Platform.WIN64, {p.name for p in plugins}, plugins, None,
        tmp_path, plugins,
    )
    assert checks.ok, [b.message for b in checks.blockers]


def test_dependency_queued_later_does_not_satisfy(tmp_path):
    """Order matters: a dep built after its dependent is no help."""
    common = _plugin("Common", order=5)
    editor = _plugin("Editor", ["Common"], order=1)
    issues = unbuildable_dependencies(tmp_path, [editor, common], [common, editor])
    assert len(issues) == 1
    assert "Editor needs Common" in issues[0].message


def test_engine_dependencies_never_gate(tmp_path):
    editor = _plugin("Editor", ["CommonUI", "GameplayAbilities"], order=0)
    assert unbuildable_dependencies(tmp_path, [editor], [editor]) == []


def test_built_uplugin_path_shape(tmp_path):
    assert built_uplugin(tmp_path, "Core") == tmp_path / BUILT_DIRNAME / "Core" / "Core.uplugin"
