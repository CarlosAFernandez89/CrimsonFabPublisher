"""Core data types shared across the app."""

from __future__ import annotations

import enum
import re
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


#: A Fab product id: the UUID at the end of a listing URL.
_PRODUCT_ID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


@dataclass
class ModuleInfo:
    name: str
    type: str
    loading_phase: str
    #: Fab technical requirements 4.3.6.b: every module must declare one of
    #: these. UE4 spelled them WhitelistPlatforms / BlacklistPlatforms.
    platform_allow_list: list[str] = field(default_factory=list)
    platform_deny_list: list[str] = field(default_factory=list)


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
    # Descriptor metadata the Fab listing form and its technical requirements
    # need. Absent from a descriptor simply means "not set".
    description: str = ""
    category: str = ""
    created_by: str = ""
    created_by_url: str = ""
    docs_url: str = ""
    support_url: str = ""
    #: 4.3.6.c names FabURL as the required key. The suite still writes the
    #: UE-era MarketplaceURL, so both are read and FabURL wins.
    fab_url: str = ""
    marketplace_url: str = ""
    supported_target_platforms: list[str] = field(default_factory=list)
    # Populated after classification / analysis:
    dependencies: list[Dependency] = field(default_factory=list)
    #: Fab submission-form counts, filled in by the scan.
    blueprint_count: int = 0
    cpp_class_count: int = 0
    #: The longest path UBT will write for this plugin, relative to its folder.
    longest_intermediate: str = ""
    status: PluginStatus = PluginStatus.UNKNOWN
    order: int = 0

    @property
    def suite_dependency_names(self) -> list[str]:
        return [d.name for d in self.dependencies if d.kind == DependencyKind.SUITE]

    @property
    def listing_url(self) -> str:
        """The plugin's Fab product URL, whichever key carries it."""
        return self.fab_url or self.marketplace_url

    @property
    def is_live(self) -> bool:
        """True when a Fab listing already exists — update it, never re-create."""
        return bool(self.listing_url)

    @property
    def fab_product_id(self) -> str:
        """The product UUID trailing the listing URL, or "" if there is none.

        Fab writes the launcher scheme
        (`com.epicgames.launcher://ue/Fab/product/<uuid>`) as well as plain
        https, so match the UUID itself rather than parsing the scheme.
        """
        match = _PRODUCT_ID.search(self.listing_url)
        return match.group(0) if match else ""


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
