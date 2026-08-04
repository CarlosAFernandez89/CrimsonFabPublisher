"""Core data types shared across the app."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path


class Platform(enum.Flag):
    """Compile targets, usable as a bitwise mask."""

    NONE = 0
    WIN64 = enum.auto()
    LINUX = enum.auto()
    ANDROID = enum.auto()
    MAC = enum.auto()
    IOS = enum.auto()


# Single-bit platforms in a stable display order.
ALL_PLATFORMS: list[Platform] = [
    Platform.WIN64,
    Platform.LINUX,
    Platform.ANDROID,
    Platform.MAC,
    Platform.IOS,
]

# Name passed to RunUAT -TargetPlatforms.
_UAT_NAMES: dict[Platform, str] = {
    Platform.WIN64: "Win64",
    Platform.LINUX: "Linux",
    Platform.ANDROID: "Android",
    Platform.MAC: "Mac",
    Platform.IOS: "IOS",
}


def platform_uat_name(platform: Platform) -> str:
    return _UAT_NAMES[platform]


def platforms_to_list(mask: Platform) -> list[Platform]:
    """Expand a bitmask into its individual platforms, in display order."""
    return [p for p in ALL_PLATFORMS if p in mask]


class DependencyKind(enum.Enum):
    """How a `.uplugin` dependency resolves against the current context."""

    SUITE = "suite"        # another plugin in the managed folder -> drives build order
    ENGINE = "engine"      # ships with the selected engine
    EXTERNAL = "external"  # neither -> must be installed separately, warn


class PluginStatus(enum.Enum):
    UNKNOWN = "unknown"
    UP_TO_DATE = "up-to-date"
    CHANGED = "changed"
    NEEDS_RESUBMIT = "needs resubmit (dep)"
    MISSING_DEP = "missing dep"
    QUEUED = "queued"
    BUILDING = "building"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class ModuleInfo:
    name: str
    type: str
    loading_phase: str


@dataclass
class Dependency:
    name: str
    kind: DependencyKind = DependencyKind.EXTERNAL


@dataclass
class PluginInfo:
    name: str
    path: Path
    uplugin_path: Path
    friendly_name: str = ""
    version_name: str = ""
    engine_version: str = ""
    can_contain_content: bool = False
    modules: list[ModuleInfo] = field(default_factory=list)
    dependency_names: list[str] = field(default_factory=list)
    # Populated after classification / analysis:
    dependencies: list[Dependency] = field(default_factory=list)
    #: Fab submission-form counts, filled in by the scan.
    blueprint_count: int = 0
    cpp_class_count: int = 0
    status: PluginStatus = PluginStatus.UNKNOWN
    order: int = 0

    @property
    def suite_dependency_names(self) -> list[str]:
        return [d.name for d in self.dependencies if d.kind == DependencyKind.SUITE]


@dataclass
class EngineInfo:
    identifier: str
    version: str
    root: Path
    is_source_build: bool = False

    @property
    def runuat_path(self) -> Path:
        return self.root / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"

    @property
    def label(self) -> str:
        tag = " (source)" if self.is_source_build else ""
        return f"UE_{self.version}{tag}"


@dataclass
class BuildResult:
    plugin_name: str
    success: bool
    zip_path: Path | None = None
    message: str = ""
    exit_code: int | None = None
