"""Detect installed Unreal Engine versions on this machine."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from pathlib import Path

from .models import EngineInfo

try:
    import winreg
except ImportError:  # non-Windows: registry sources are simply unavailable
    winreg = None  # type: ignore[assignment]


def _read_hklm_installs() -> list[EngineInfo]:
    """Epic Launcher installs registered under HKLM."""
    engines: list[EngineInfo] = []
    if winreg is None:
        return engines
    try:
        root = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EpicGames\Unreal Engine"
        )
    except OSError:
        return engines
    with root:
        index = 0
        while True:
            try:
                version = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(root, version) as sub:
                    path, _ = winreg.QueryValueEx(sub, "InstalledDirectory")
            except OSError:
                continue
            engines.append(EngineInfo(identifier=version, version=version, root=Path(path)))
    return engines


def _read_launcher_dat() -> list[EngineInfo]:
    """Fallback source: the Launcher's LauncherInstalled.dat manifest."""
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    dat = Path(program_data) / "Epic" / "UnrealEngineLauncher" / "LauncherInstalled.dat"
    engines: list[EngineInfo] = []
    if not dat.is_file():
        return engines
    try:
        data = json.loads(dat.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return engines
    for item in data.get("InstallationList", []):
        app_name = item.get("AppName", "")
        # The manifest also lists plugins/content at engine roots; keep only engines.
        if not app_name.startswith("UE_"):
            continue
        location = item.get("InstallLocation")
        if not location:
            continue
        version = item.get("AppVersion", "").split("-", 1)[0] or app_name[3:]
        engines.append(EngineInfo(identifier=app_name, version=version, root=Path(location)))
    return engines


def _read_hkcu_source_builds() -> list[EngineInfo]:
    """Custom / source-built engines registered under HKCU\\...\\Builds."""
    engines: list[EngineInfo] = []
    if winreg is None:
        return engines
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Epic Games\Unreal Engine\Builds"
        )
    except OSError:
        return engines
    with key:
        index = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(key, index)
            except OSError:
                break
            index += 1
            engines.append(
                EngineInfo(
                    identifier=name,
                    version=name,
                    root=Path(value),
                    is_source_build=True,
                )
            )
    return engines


def _version_from_root(root: Path) -> str:
    """Major.minor for an engine folder, from Build.version then the folder name.

    Kept to major.minor so a hand-added engine produces the same `UE_5.6` label
    — and therefore the same zip filename — as the auto-detected one.
    """
    try:
        data = json.loads(
            (root / "Engine" / "Build" / "Build.version").read_text(encoding="utf-8-sig")
        )
        major, minor = data["MajorVersion"], data["MinorVersion"]
        return f"{major}.{minor}"
    except (OSError, ValueError, KeyError, TypeError):
        pass
    match = re.search(r"(\d+)\.(\d+)", root.name)
    return f"{match.group(1)}.{match.group(2)}" if match else root.name or "unknown"


def engine_from_root(path: Path | str) -> EngineInfo | None:
    """Build an EngineInfo for a folder the user pointed at.

    Returns None when the folder is not an engine root, which is what the
    Settings UI uses to reject a bad pick.
    """
    root = Path(path)
    candidate = EngineInfo(identifier=str(root), version="", root=root)
    if not candidate.runuat_path.is_file():
        return None
    return EngineInfo(
        # The resolved path is the identifier: unique, and stable across runs
        # so the saved engine selection survives a restart.
        identifier=_root_key(root),
        version=_version_from_root(root),
        root=root,
        # Launcher builds ship this marker; source builds do not.
        is_source_build=not (root / "Engine" / "Build" / "InstalledBuild.txt").is_file(),
    )


def _root_key(root: Path) -> str:
    try:
        return str(root.resolve()).lower()
    except OSError:
        return str(root).lower()


def _version_key(engine: EngineInfo) -> list[int]:
    parts = re.findall(r"\d+", engine.version)
    return [int(p) for p in parts] or [0]


def detect_engines(extra_roots: Iterable[Path | str] = ()) -> list[EngineInfo]:
    """All usable engines, de-duplicated by root.

    Automatic sources are registry/manifest only — nothing is searched for on
    disk. `extra_roots` are folders the user registered by hand, for engines the
    Epic Launcher never recorded (portable copies, unregistered source builds,
    another user profile's installs).
    """
    seen: dict[str, EngineInfo] = {}
    detected = (
        _read_hklm_installs() + _read_launcher_dat() + _read_hkcu_source_builds()
    )
    # Detected first: if a hand-added root duplicates one, keep the cleaner
    # "5.6"-style identifier so existing saved selections still resolve.
    manual = [e for e in (engine_from_root(r) for r in extra_roots) if e is not None]
    for engine in detected + manual:
        root_key = _root_key(engine.root)
        if root_key in seen:
            continue
        if not engine.runuat_path.is_file():
            continue
        seen[root_key] = engine
    return sorted(seen.values(), key=_version_key)
