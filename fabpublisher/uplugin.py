"""Parse `.uplugin` descriptor files."""

from __future__ import annotations

import json
from pathlib import Path

from .models import ModuleInfo, PluginInfo


def _strings(value: object) -> list[str]:
    """Read a descriptor list of strings, tolerating any other shape."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def parse_uplugin(uplugin_path: Path) -> PluginInfo:
    """Read a `.uplugin` file into a PluginInfo.

    `.uplugin` files are UTF-8 and frequently carry a BOM, so decode with
    `utf-8-sig` which transparently strips it when present.
    """
    uplugin_path = Path(uplugin_path)
    data = json.loads(uplugin_path.read_text(encoding="utf-8-sig"))

    modules = [
        ModuleInfo(
            name=m.get("Name", ""),
            type=m.get("Type", ""),
            loading_phase=m.get("LoadingPhase", ""),
            # UE4 spelled these WhitelistPlatforms / BlacklistPlatforms; read
            # both so a 4.x descriptor still reports its platform list.
            platform_allow_list=_strings(
                m.get("PlatformAllowList", m.get("WhitelistPlatforms"))
            ),
            platform_deny_list=_strings(
                m.get("PlatformDenyList", m.get("BlacklistPlatforms"))
            ),
        )
        for m in data.get("Modules", [])
    ]
    dependency_names = [
        p.get("Name") for p in data.get("Plugins", []) if p.get("Name")
    ]

    name = uplugin_path.stem
    return PluginInfo(
        name=name,
        path=uplugin_path.parent,
        uplugin_path=uplugin_path,
        friendly_name=data.get("FriendlyName", name),
        version_name=data.get("VersionName", ""),
        engine_version=data.get("EngineVersion", ""),
        can_contain_content=bool(data.get("CanContainContent", False)),
        modules=modules,
        dependency_names=dependency_names,
        description=data.get("Description", ""),
        category=data.get("Category", ""),
        created_by=data.get("CreatedBy", ""),
        created_by_url=data.get("CreatedByURL", ""),
        docs_url=data.get("DocsURL", ""),
        support_url=data.get("SupportURL", ""),
        fab_url=data.get("FabURL", ""),
        marketplace_url=data.get("MarketplaceURL", ""),
        supported_target_platforms=_strings(data.get("SupportedTargetPlatforms")),
    )
