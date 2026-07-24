from pathlib import Path

from fabpublisher.discovery import discover_plugins
from fabpublisher.uplugin import parse_uplugin


def test_parse_reads_metadata_and_deps(suite: Path):
    plugin = parse_uplugin(suite / "Ability" / "Ability.uplugin")
    assert plugin.name == "Ability"
    assert plugin.engine_version == "5.8.0"
    assert plugin.dependency_names == ["Common", "GameplayAbilities", "ThirdParty"]
    assert plugin.modules[0].name == "Ability"
    assert plugin.modules[0].type == "Runtime"


def test_parse_handles_bom(suite: Path):
    # Common.uplugin is written with a UTF-8 BOM.
    plugin = parse_uplugin(suite / "Common" / "Common.uplugin")
    assert plugin.name == "Common"
    assert plugin.dependency_names == []


def test_discover_finds_all_plugins(suite: Path):
    plugins = discover_plugins(suite)
    assert {p.name for p in plugins} == {"Common", "Ability", "Core"}
