"""Detect which compile targets this machine can actually build."""

from __future__ import annotations

import json
import os
import platform as _host_platform
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import ALL_PLATFORMS, Platform


@dataclass
class PlatformAvailability:
    platform: Platform
    available: bool
    reason: str


def _dir_env(*names: str) -> str | None:
    """Return the first env var whose value is an existing directory."""
    for name in names:
        value = os.environ.get(name)
        if value and Path(value).is_dir():
            return value
    return None


# ------------------------------------------------------- pinned SDK versions
# Engines pin the exact toolchain they were built against in
# Engine/Config/<Platform>/<Platform>_SDK.json. Building with a different one
# fails at link time with errors that point nowhere near the real cause.


@dataclass(frozen=True)
class SdkRequirement:
    main: str = ""
    minimum: str = ""
    maximum: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def known(self) -> bool:
        return bool(self.main)


def read_sdk_requirement(
    engine_root: Path | str | None, platform_dir: str
) -> SdkRequirement:
    """Read an engine's pinned SDK versions. Empty when it cannot be determined."""
    if not engine_root:
        return SdkRequirement()
    path = (
        Path(engine_root)
        / "Engine"
        / "Config"
        / platform_dir
        / f"{platform_dir}_SDK.json"
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return SdkRequirement()
    if not isinstance(data, dict):
        return SdkRequirement()
    main = str(data.get("MainVersion", ""))
    return SdkRequirement(
        main=main,
        minimum=str(data.get("MinVersion", main)),
        maximum=str(data.get("MaxVersion", main)),
        extra=data,
    )


@dataclass(frozen=True)
class ToolchainStatus:
    """How an installed toolchain compares to what the engine wants."""

    root: str = ""
    installed: str = ""
    required: str = ""
    #: False only when a mismatch was positively established.
    ok: bool = True
    detail: str = ""


_TOOLCHAIN_ORDINAL = re.compile(r"^v(\d+)_")


def _ordinal(name: str) -> int | None:
    match = _TOOLCHAIN_ORDINAL.match(name)
    return int(match.group(1)) if match else None


def _within_window(installed: str, req: SdkRequirement) -> bool:
    """UBT compares the leading vNN, so a range wider than one version works."""
    low, high, have = _ordinal(req.minimum), _ordinal(req.maximum), _ordinal(installed)
    if None not in (low, high, have):
        return low <= have <= high
    return installed == req.main


def linux_toolchain_status(engine_root: Path | str | None = None) -> ToolchainStatus | None:
    """None when no toolchain is installed at all."""
    root = _dir_env("LINUX_MULTIARCH_ROOT")
    if root is None:
        return None
    # Path() drops the trailing separator Epic's installer leaves behind.
    installed = Path(root).name
    req = read_sdk_requirement(engine_root, "Linux")
    if not req.known:
        # Never block on a guess — an engine layout we cannot read is treated
        # as "fine", exactly as it was before this check existed.
        return ToolchainStatus(root=root, installed=installed, detail=f"Toolchain: {root}")
    if _within_window(installed, req):
        return ToolchainStatus(
            root=root,
            installed=installed,
            required=req.main,
            detail=f"Toolchain {installed} matches this engine",
        )
    return ToolchainStatus(
        root=root,
        installed=installed,
        required=req.main,
        ok=False,
        detail=f"{installed} installed, this engine needs {req.main}",
    )


def android_ndk_status(engine_root: Path | str | None = None) -> ToolchainStatus | None:
    """NDK revision check. Informational: engines accept a range here."""
    root = _dir_env("NDKROOT", "NDK_ROOT", "ANDROID_NDK_ROOT", "ANDROID_NDK_HOME")
    if root is None:
        return None
    installed = ""
    try:
        for line in (Path(root) / "source.properties").read_text(
            encoding="utf-8-sig"
        ).splitlines():
            if line.startswith("Pkg.Revision"):
                installed = line.split("=", 1)[1].strip()
                break
    except OSError:
        pass

    expected = str(read_sdk_requirement(engine_root, "Android").extra.get("ndk", ""))
    if not installed or not expected:
        return ToolchainStatus(root=root, installed=installed, detail=f"NDK: {root}")
    if installed == expected:
        return ToolchainStatus(
            root=root,
            installed=installed,
            required=expected,
            detail=f"NDK {installed} matches this engine",
        )
    # Still buildable — the engine declares a supported range — so only note it.
    return ToolchainStatus(
        root=root,
        installed=installed,
        required=expected,
        detail=f"NDK {installed} installed, this engine ships with {expected}",
    )


def detect_platform_availability(
    engine_root: Path | str | None = None,
) -> dict[Platform, PlatformAvailability]:
    """Heuristic per-platform availability with a human-readable reason.

    Unreal exposes no clean API for this, so we probe the environment the same
    way UnrealBuildTool does when it decides whether a target is buildable.
    Pass `engine_root` to also check the installed toolchain against the version
    that engine pins — the same toolchain can be right for one engine and
    rejected by another.
    """
    is_windows = os.name == "nt"
    is_mac = _host_platform.system() == "Darwin"
    results: dict[Platform, PlatformAvailability] = {}

    # Win64: native on a Windows host (engine ships the MSVC toolchain hookup).
    results[Platform.WIN64] = PlatformAvailability(
        Platform.WIN64,
        is_windows,
        "Available (Windows host toolchain)" if is_windows else "Requires a Windows host",
    )

    # Linux: cross-compiled via the UE clang toolchain, pinned per engine.
    linux = linux_toolchain_status(engine_root)
    results[Platform.LINUX] = PlatformAvailability(
        Platform.LINUX,
        linux is not None and linux.ok,
        linux.detail
        if linux is not None
        else "Set LINUX_MULTIARCH_ROOT to the UE cross-compile toolchain",
    )

    # Android: needs the NDK (and typically the SDK).
    android = android_ndk_status(engine_root)
    results[Platform.ANDROID] = PlatformAvailability(
        Platform.ANDROID,
        android is not None,
        android.detail
        if android is not None
        else "Set NDKROOT/ANDROID_HOME (install the Android NDK/SDK)",
    )

    # Mac / iOS: cannot be cross-compiled from a non-macOS host.
    for plat, label in ((Platform.MAC, "Mac"), (Platform.IOS, "iOS")):
        results[plat] = PlatformAvailability(
            plat,
            is_mac,
            "Available (macOS host)" if is_mac else f"{label} builds require a macOS host",
        )

    return results


@dataclass(frozen=True)
class SetupGuide:
    """How to turn an unavailable target on."""

    title: str
    summary: str  # one line — the hover tooltip
    steps: list[str]
    env_vars: tuple[str, ...] = ()
    doc_url: str = ""
    #: False when nothing the user does on this machine can enable it.
    possible: bool = True


#: Read once per process, so an installer that sets a system variable is not
#: visible until the app is restarted. Every guide says so.
_RESTART = (
    "Restart CrimsonFabPublisher. Environment variables are read once at "
    "launch, so a newly installed toolchain will not appear until then."
)

_LINUX_DOCS = (
    "https://dev.epicgames.com/documentation/en-us/unreal-engine/"
    "linux-development-requirements-for-unreal-engine"
)
_ANDROID_DOCS = (
    "https://dev.epicgames.com/documentation/en-us/unreal-engine/"
    "set-up-android-sdk-and-ndk-for-your-unreal-engine-development-environment"
)


def setup_guide(
    platform: Platform, engine_root: Path | str | None = None
) -> SetupGuide | None:
    """Setup instructions for a target, or None if it needs no explanation."""
    if platform is Platform.LINUX:
        req = read_sdk_requirement(engine_root, "Linux")
        status = linux_toolchain_status(engine_root)
        wanted = (
            f"This engine pins {req.main} — that exact version, not merely a newer one."
            if req.known
            else "Each engine release pins one exact toolchain version; check the "
            "Linux requirements page for the one your engine expects."
        )
        steps = [
            "Unreal cross-compiles Linux binaries on Windows using a clang "
            "toolchain that Epic distributes separately from the engine.",
            wanted,
        ]
        if status is not None and not status.ok:
            steps.append(
                f"You currently have {status.installed} at {status.root}. Install "
                f"{req.main} as well — they coexist happily under "
                "C:\\UnrealToolchains\\ — then point LINUX_MULTIARCH_ROOT at "
                "whichever one matches the engine you are building with."
            )
        else:
            steps.append(
                "Download that toolchain's installer and run it. It sets "
                "LINUX_MULTIARCH_ROOT for you, usually to a folder under "
                "C:\\UnrealToolchains\\."
            )
        steps.append(_RESTART)
        summary = (
            f"This engine needs {req.main}."
            if status is not None and not status.ok
            else "Install Epic's clang cross-compile toolchain, then restart."
        )
        return SetupGuide(
            title="Building for Linux from Windows",
            summary=summary,
            steps=steps,
            env_vars=("LINUX_MULTIARCH_ROOT",),
            doc_url=_LINUX_DOCS,
        )

    if platform is Platform.ANDROID:
        script = "<engine>\\Engine\\Extras\\Android\\SetupAndroid.bat"
        if engine_root:
            script = str(Path(engine_root) / "Engine" / "Extras" / "Android" / "SetupAndroid.bat")
        return SetupGuide(
            title="Building for Android",
            summary="Run the engine's SetupAndroid script, then restart.",
            steps=[
                "Install Android Studio. The engine's setup script drives its SDK "
                "manager, so it has to be present first.",
                f"Run {script}. It installs the exact SDK, NDK and JDK versions "
                "your engine expects and sets the environment variables — do not "
                "pick versions by hand, Unreal is strict about them.",
                _RESTART,
            ],
            env_vars=("NDKROOT", "NDK_ROOT", "ANDROID_NDK_ROOT", "ANDROID_NDK_HOME"),
            doc_url=_ANDROID_DOCS,
        )

    if platform in (Platform.MAC, Platform.IOS):
        name = "Mac" if platform is Platform.MAC else "iOS"
        return SetupGuide(
            title=f"Building for {name}",
            summary=f"{name} binaries can only be produced on a macOS machine.",
            steps=[
                f"Apple's toolchain is macOS-only, so {name} targets cannot be "
                "cross-compiled from Windows.",
                "Unreal can drive a networked Mac for iOS through its Remote Build "
                "options, but that is configured per project in the editor and is "
                "not something this app sets up — it builds on the local host only.",
                f"To ship {name}, run the packaging step on a Mac with Xcode "
                "installed and the same engine version.",
            ],
            possible=False,
        )

    if platform is Platform.WIN64:
        return SetupGuide(
            title="Building for Windows",
            summary="Win64 builds require a Windows host.",
            steps=["Run this app on Windows with the engine installed."],
            possible=False,
        )
    return None


def available_mask(engine_root: Path | str | None = None) -> Platform:
    mask = Platform.NONE
    for plat, info in detect_platform_availability(engine_root).items():
        if info.available and plat in ALL_PLATFORMS:
            mask |= plat
    return mask
