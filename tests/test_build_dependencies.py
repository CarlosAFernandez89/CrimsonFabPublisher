"""Suite dependencies must reach BuildPlugin, or its host project can't resolve them."""

from __future__ import annotations

from pathlib import Path

from fabpublisher.builder import build_command
from fabpublisher.models import EngineInfo, Platform, PluginInfo
from fabpublisher.ui.build_worker import BuildWorker

ENGINE = EngineInfo(identifier="UE_5.8", version="5.8", root=Path("F:/UE_5.8"))
ROOT = Path("F:/Plugins")


def _plugin(name: str, deps: list[str] | None = None, order: int = 0) -> PluginInfo:
    return PluginInfo(
        name=name,
        path=ROOT / name,
        uplugin_path=ROOT / name / f"{name}.uplugin",
        dependency_names=deps or [],
        order=order,
    )


def test_no_dependencies_adds_no_flag():
    cmd = build_command(ENGINE, _plugin("Core"), Path("E:/out"), Platform.WIN64)
    assert not any(a.startswith("-Dependencies=") for a in cmd)


def test_each_dependency_gets_its_own_flag():
    deps = [Path("E:/w/Common_Staged/Common.uplugin"), Path("E:/w/Core_Staged/Core.uplugin")]
    cmd = build_command(
        ENGINE, _plugin("Editor"), Path("E:/out"), Platform.WIN64, None, deps
    )
    assert f"-Dependencies={deps[0]}" in cmd
    assert f"-Dependencies={deps[1]}" in cmd
    # -TargetPlatforms stays last; the flags go before it.
    assert cmd[-1].startswith("-TargetPlatforms=")


def _worker(jobs, all_plugins):
    return BuildWorker(
        engine=ENGINE,
        jobs=jobs,
        platforms=Platform.WIN64,
        work_root=Path("E:/w"),
        ship_patterns=[],
        output_dir=Path("E:/out"),
        all_plugins=all_plugins,
    )


def test_dependency_resolved_even_when_not_selected():
    """Building only the dependent must still stage what it depends on."""
    common = _plugin("Common", order=0)
    editor = _plugin("Editor", ["Common"], order=1)
    worker = _worker([editor], [common, editor])
    assert [p.name for p in worker._dependencies_for(editor)] == ["Common"]


def test_dependencies_are_transitive_and_in_build_order():
    common = _plugin("Common", order=0)
    core = _plugin("Core", ["Common"], order=1)
    editor = _plugin("Editor", ["Core"], order=2)
    worker = _worker([editor], [common, core, editor])
    assert [p.name for p in worker._dependencies_for(editor)] == ["Common", "Core"]


def test_engine_and_external_deps_are_not_passed():
    """Only suite plugins are staged; engine plugins resolve on their own."""
    editor = _plugin("Editor", ["GameplayAbilities", "CommonUI"], order=0)
    worker = _worker([editor], [editor])
    assert worker._dependencies_for(editor) == []


def test_plugin_is_not_its_own_dependency():
    solo = _plugin("Solo", order=0)
    worker = _worker([solo], [solo])
    assert worker._dependencies_for(solo) == []
