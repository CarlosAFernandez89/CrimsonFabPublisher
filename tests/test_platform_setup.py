"""Setup guidance for unavailable compile targets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fabpublisher.models import ALL_PLATFORMS, Platform
from fabpublisher.platforms import (
    detect_platform_availability,
    linux_toolchain_status,
    read_sdk_requirement,
    setup_guide,
)


def _engine(tmp_path: Path, name: str, sdk: dict, platform_dir: str = "Linux") -> Path:
    root = tmp_path / name
    config = root / "Engine" / "Config" / platform_dir
    config.mkdir(parents=True)
    (config / f"{platform_dir}_SDK.json").write_text(json.dumps(sdk))
    return root


def _toolchain(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "UnrealToolchains" / name
    path.mkdir(parents=True)
    return path


V25 = "v25_clang-18.1.0-rockylinux8"
V26 = "v26_clang-20.1.8-rockylinux8"


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
def test_every_platform_has_a_guide(platform):
    """A new Platform member without guidance must fail here, not in the UI."""
    guide = setup_guide(platform)
    assert guide is not None
    assert guide.title and guide.summary and guide.steps


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
def test_summary_is_short_enough_for_a_tooltip(platform):
    assert len(setup_guide(platform).summary) <= 90


def test_linux_guide_names_the_variable_and_the_restart():
    guide = setup_guide(Platform.LINUX)
    assert guide.possible is True
    assert guide.env_vars == ("LINUX_MULTIARCH_ROOT",)
    assert "epicgames.com" in guide.doc_url
    assert any("Restart" in step for step in guide.steps)


def test_android_guide_points_at_the_engine_setup_script():
    guide = setup_guide(Platform.ANDROID, Path("F:/Epic Games/UE_5.6"))
    joined = " ".join(guide.steps)
    assert "SetupAndroid.bat" in joined
    # The concrete path for the selected engine, not a placeholder.
    assert "Epic Games" in joined and "<engine>" not in joined
    assert "NDKROOT" in guide.env_vars


def test_android_guide_falls_back_to_a_placeholder_without_an_engine():
    assert "<engine>" in " ".join(setup_guide(Platform.ANDROID).steps)


@pytest.mark.parametrize("platform", [Platform.MAC, Platform.IOS])
def test_apple_targets_are_marked_impossible_on_windows(platform):
    guide = setup_guide(platform)
    assert guide.possible is False
    assert guide.env_vars == ()
    # No doc link, because there is no local action to take.
    assert guide.doc_url == ""


### toolchain version checking ###############################################


def test_reads_pinned_versions(tmp_path: Path):
    root = _engine(
        tmp_path, "UE_5.6", {"MainVersion": V25, "MinVersion": V25, "MaxVersion": V25}
    )
    req = read_sdk_requirement(root, "Linux")
    assert req.known and req.main == V25 and req.minimum == V25


def test_unreadable_engine_config_is_not_a_requirement(tmp_path: Path):
    assert read_sdk_requirement(tmp_path / "nope", "Linux").known is False
    assert read_sdk_requirement(None, "Linux").known is False

    broken = tmp_path / "Broken" / "Engine" / "Config" / "Linux"
    broken.mkdir(parents=True)
    (broken / "Linux_SDK.json").write_text("{ not json")
    assert read_sdk_requirement(tmp_path / "Broken", "Linux").known is False


def test_matching_toolchain_is_available(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LINUX_MULTIARCH_ROOT", str(_toolchain(tmp_path, V25)))
    root = _engine(
        tmp_path, "UE_5.6", {"MainVersion": V25, "MinVersion": V25, "MaxVersion": V25}
    )
    status = linux_toolchain_status(root)
    assert status is not None and status.ok
    assert detect_platform_availability(root)[Platform.LINUX].available is True


def test_mismatched_toolchain_blocks_the_target(tmp_path: Path, monkeypatch):
    """The real case: v26 installed, UE 5.6 pins v25 with no tolerance."""
    monkeypatch.setenv("LINUX_MULTIARCH_ROOT", str(_toolchain(tmp_path, V26)))
    root = _engine(
        tmp_path, "UE_5.6", {"MainVersion": V25, "MinVersion": V25, "MaxVersion": V25}
    )
    status = linux_toolchain_status(root)
    assert status is not None and status.ok is False
    assert status.installed == V26 and status.required == V25

    info = detect_platform_availability(root)[Platform.LINUX]
    assert info.available is False
    assert V26 in info.reason and V25 in info.reason


def test_same_toolchain_can_be_valid_for_another_engine(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LINUX_MULTIARCH_ROOT", str(_toolchain(tmp_path, V26)))
    ue57 = _engine(
        tmp_path, "UE_5.7", {"MainVersion": V26, "MinVersion": V26, "MaxVersion": V26}
    )
    assert detect_platform_availability(ue57)[Platform.LINUX].available is True


def test_trailing_separator_from_the_installer_is_handled(tmp_path: Path, monkeypatch):
    """Epic's installer sets the variable with a trailing backslash."""
    monkeypatch.setenv("LINUX_MULTIARCH_ROOT", str(_toolchain(tmp_path, V25)) + "\\")
    root = _engine(
        tmp_path, "UE_5.6", {"MainVersion": V25, "MinVersion": V25, "MaxVersion": V25}
    )
    assert linux_toolchain_status(root).installed == V25


def test_version_window_wider_than_one_release(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LINUX_MULTIARCH_ROOT", str(_toolchain(tmp_path, V26)))
    root = _engine(
        tmp_path, "UE_X", {"MainVersion": V26, "MinVersion": V25, "MaxVersion": V26}
    )
    assert linux_toolchain_status(root).ok is True


def test_unknown_requirement_never_blocks(tmp_path: Path, monkeypatch):
    """Bias to permissive: an engine layout we cannot read must not disable a
    target the user could otherwise build."""
    monkeypatch.setenv("LINUX_MULTIARCH_ROOT", str(_toolchain(tmp_path, V26)))
    status = linux_toolchain_status(tmp_path / "UnknownEngine")
    assert status is not None and status.ok is True
    assert detect_platform_availability(None)[Platform.LINUX].available is True


def test_no_toolchain_installed_reports_none(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LINUX_MULTIARCH_ROOT", raising=False)
    assert linux_toolchain_status(tmp_path) is None
    info = detect_platform_availability(tmp_path)[Platform.LINUX]
    assert info.available is False
    assert "LINUX_MULTIARCH_ROOT" in info.reason


def test_guide_names_the_required_version_on_a_mismatch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LINUX_MULTIARCH_ROOT", str(_toolchain(tmp_path, V26)))
    root = _engine(
        tmp_path, "UE_5.6", {"MainVersion": V25, "MinVersion": V25, "MaxVersion": V25}
    )
    guide = setup_guide(Platform.LINUX, root)
    assert V25 in guide.summary
    joined = " ".join(guide.steps)
    assert V26 in joined and V25 in joined
    assert "coexist" in joined  # tells them they can keep both


def test_guides_cover_every_unavailable_reason_on_this_host():
    """Anything the UI shows a warning for must have something to click."""
    for platform, info in detect_platform_availability().items():
        if not info.available:
            assert setup_guide(platform) is not None
