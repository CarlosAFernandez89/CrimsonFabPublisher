"""Predicting UBT's 260-character path limit before a build starts."""

from __future__ import annotations

from pathlib import Path

from fabpublisher.config import Config
from fabpublisher.models import EngineInfo, Platform, PluginInfo
from fabpublisher.pathlength import MAX_PATH, longest_intermediate
from fabpublisher.ui.app_settings import AppSettings, default_work_dir
from fabpublisher.ui.build_controller import overlong_build_paths, preflight

ENGINE = EngineInfo(identifier="UE_5.8", version="5.8", root=Path("E:/UE_5.8"))
OBJ = Path("Intermediate/Build/Win64/x64/UnrealEditor/Development")


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _plugin(name: str, tail: str = "", deps: list[str] | None = None) -> PluginInfo:
    return PluginInfo(
        name=name,
        path=Path("E:/Plugins") / name,
        uplugin_path=Path("E:/Plugins") / name / f"{name}.uplugin",
        dependency_names=deps or [],
        longest_intermediate=tail,
    )


def test_cpp_lands_under_its_module_with_the_dep_json_suffix(tmp_path: Path):
    _write(tmp_path / "Source/Core/Core.Build.cs")
    _write(tmp_path / "Source/Core/Private/Deep/Folder/SomeLongFileName.cpp")
    assert longest_intermediate(tmp_path) == str(
        OBJ / "Core" / "SomeLongFileName.cpp.dep.json"
    )


def test_module_is_the_nearest_build_cs_not_the_first_folder(tmp_path: Path):
    _write(tmp_path / "Source/Group/CoreEditorModule/CoreEditorModule.Build.cs")
    _write(tmp_path / "Source/Group/CoreEditorModule/Private/A.cpp")
    assert longest_intermediate(tmp_path) == str(
        OBJ / "CoreEditorModule" / "A.cpp.dep.json"
    )


def test_only_uht_headers_count(tmp_path: Path):
    _write(tmp_path / "Source/M/M.Build.cs")
    _write(tmp_path / "Source/M/Public/AVeryLongPlainHeaderNameWithNoReflection.h")
    assert longest_intermediate(tmp_path) == ""

    _write(
        tmp_path / "Source/M/Public/AVeryLongReflectedHeaderName.h",
        '#include "AVeryLongReflectedHeaderName.generated.h"',
    )
    assert longest_intermediate(tmp_path) == str(
        Path("Intermediate/Build/Win64/UnrealEditor/Inc/M/UHT")
        / "AVeryLongReflectedHeaderName.generated.h"
    )


def test_no_source_means_nothing_to_check(tmp_path: Path):
    assert longest_intermediate(tmp_path) == ""


def test_matches_a_real_ue58_build():
    """CrimsonUI's host project, as recorded in a real UAT log: UBT wrote a
    238-character `.cpp.obj.rsp`, so the `.dep.json` beside it is 239."""
    # Same length as the real one; only the user name is changed.
    work = Path(r"C:\Users\user1\AppData\Local\Temp\CrimsonFabPublisher_Work")
    tail = str(
        OBJ / "CrimsonCommonNodes" / "K2Node_AsyncAction_WaitForCrimsonSystemReady.cpp.dep.json"
    )
    jobs = [_plugin("CrimsonUI", deps=["CrimsonCommon"])]
    plugins = jobs + [_plugin("CrimsonCommon", tail)]
    assert overlong_build_paths(work, jobs, plugins) == []

    longer = work.parent / ("x" * (MAX_PATH - 239 + len(work.name)))
    [issue] = overlong_build_paths(longer, jobs, plugins)
    assert f"reach {MAX_PATH} characters" in issue.message
    assert "at least 1 characters shorter" in issue.message


def test_a_dependency_path_counts_against_the_job():
    jobs = [_plugin("Small", "x", deps=["Big"])]
    plugins = jobs + [_plugin("Big", "y" * 300)]
    [issue] = overlong_build_paths(Path("C:/W"), jobs, plugins)
    assert issue.message.startswith("Small:")
    assert "Big" in issue.message


def test_preflight_blocks_only_when_given_a_work_root():
    job = _plugin("Core", "y" * 300)
    assert preflight(ENGINE, Platform.WIN64, {"Core"}, [job]).ok
    checks = preflight(ENGINE, Platform.WIN64, {"Core"}, [job], work_root=Path("C:/W"))
    assert not checks.ok
    assert "work folder" in checks.blockers[0].message


def test_work_dir_defaults_to_temp_and_can_be_changed():
    settings = AppSettings(Config())
    assert settings.effective_work_dir() == default_work_dir()
    seen: list[str] = []
    settings.work_dir_changed.connect(seen.append)
    settings.work_dir = "  C:/UEWork  "
    assert settings.effective_work_dir() == Path("C:/UEWork")
    assert seen == ["C:/UEWork"]
