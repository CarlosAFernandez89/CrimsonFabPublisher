"""Preflight: the three modal dialogs, as testable data."""

from __future__ import annotations

from pathlib import Path

from fabpublisher.builder import build_command, platform_arg, submission_zip_name
from fabpublisher.models import EngineInfo, Platform, PluginInfo
from fabpublisher.ui.build_controller import preflight
from fabpublisher.validation import Issue

ENGINE = EngineInfo(identifier="UE_5.6", version="5.6", root=Path("E:/UE_5.6"))


def _plugin(name: str) -> PluginInfo:
    return PluginInfo(
        name=name,
        path=Path("E:/Plugins") / name,
        uplugin_path=Path("E:/Plugins") / name / f"{name}.uplugin",
    )


def test_all_clear():
    checks = preflight(ENGINE, Platform.WIN64, {"Core"}, [_plugin("Core")])
    assert checks.ok
    assert checks.blockers == []


def test_no_engine_blocks():
    checks = preflight(None, Platform.WIN64, {"Core"}, [_plugin("Core")])
    assert not checks.ok
    assert "engine" in checks.blockers[0].message.lower()


def test_no_platform_blocks():
    checks = preflight(ENGINE, Platform.NONE, {"Core"}, [_plugin("Core")])
    assert not checks.ok
    assert "platform" in checks.blockers[0].message.lower()


def test_nothing_selected_blocks():
    checks = preflight(ENGINE, Platform.WIN64, set(), [])
    assert not checks.ok
    assert "plugin" in checks.blockers[0].message.lower()


def test_every_blocker_is_reported_at_once():
    """The old UI showed one modal at a time; the page shows the whole list."""
    checks = preflight(None, Platform.NONE, set(), [])
    assert len(checks.blockers) == 3


def test_validation_issues_warn_but_do_not_block():
    issues = {"Core": [Issue("error", "No Source/ directory"), Issue("warning", "hmm")]}
    checks = preflight(ENGINE, Platform.WIN64, {"Core"}, [_plugin("Core")], issues)
    assert checks.ok  # unchanged behaviour: validation never blocked a build
    assert len(checks.warnings) == 2
    assert all(w.message.startswith("Core: ") for w in checks.warnings)


def test_warnings_only_cover_jobs_actually_queued():
    issues = {"Other": [Issue("warning", "not in this run")]}
    checks = preflight(ENGINE, Platform.WIN64, {"Core"}, [_plugin("Core")], issues)
    assert checks.warnings == []


def test_submission_zip_name_matches_the_builder():
    plugin = _plugin("CrimsonCore")
    assert submission_zip_name(plugin, ENGINE) == (
        "CrimsonCore_UE_5.6_Submission.zip"
    )
    source = EngineInfo("src", "5.6", Path("E:/UE"), is_source_build=True)
    assert submission_zip_name(plugin, source) == (
        "CrimsonCore_UE_5.6 (source)_Submission.zip"
    )


def test_platform_arg_uses_uat_names_in_order():
    assert platform_arg(Platform.WIN64) == "Win64"
    assert platform_arg(Platform.LINUX | Platform.WIN64) == "Win64+Linux"
    assert platform_arg(Platform.NONE) == ""


def test_build_command_shape():
    cmd = build_command(ENGINE, _plugin("Core"), Path("E:/work/Core_Build"), Platform.WIN64)
    assert cmd[0].endswith("RunUAT.bat")
    assert cmd[1] == "BuildPlugin"
    assert cmd[-1] == "-TargetPlatforms=Win64"


def test_build_command_disables_pch_and_unity():
    """-StrictIncludes is UE 5.8's only route to -NoPCH -NoSharedPCH -DisableUnity."""
    cmd = build_command(ENGINE, _plugin("Core"), Path("E:/work/Core_Build"), Platform.WIN64)
    assert "-StrictIncludes" in cmd


def test_build_command_drops_flags_ue58_no_longer_parses():
    cmd = build_command(ENGINE, _plugin("Core"), Path("E:/work/Core_Build"), Platform.WIN64)
    assert "-Rocket" not in cmd
    # A subfolder would push the .uplugin out of the zip root, which FAB requires.
    assert "-CreateSubFolder" not in cmd
    assert "-PackageAppendPluginSubdir" not in cmd
    # The editor target must build so editor-only modules are actually validated.
    assert "-NoHostPlatform" not in cmd


def test_build_command_targets_the_staged_descriptor():
    staged = Path("E:/work/Core_Staged/Core.uplugin")
    cmd = build_command(
        ENGINE, _plugin("Core"), Path("E:/work/Core_Build"), Platform.WIN64, staged
    )
    assert f"-Plugin={staged}" in cmd
