import json
from pathlib import Path

from fabpublisher.discovery import discover_plugins
from fabpublisher.uplugin import parse_uplugin

from .conftest import _write_uplugin


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


def test_reads_fab_listing_metadata(tmp_path):
    """The descriptor keys Fab's listing form and requirements 4.3.6 need."""
    path = _write_uplugin(
        tmp_path / "Save",
        "Save",
        [],
        description="A fragment-based save system.",
        category="Tools",
        marketplace_url=(
            "com.epicgames.launcher://ue/Fab/product/"
            "11111111-2222-3333-4444-555555555555"
        ),
    )
    plugin = parse_uplugin(path)

    assert plugin.description == "A fragment-based save system."
    assert plugin.category == "Tools"
    # No FabURL yet, so the UE-era key still identifies the live listing.
    assert plugin.fab_url == ""
    assert plugin.is_live
    assert plugin.fab_product_id == "11111111-2222-3333-4444-555555555555"


def test_fab_url_wins_over_marketplace_url(tmp_path):
    path = _write_uplugin(
        tmp_path / "Skill",
        "Skill",
        [],
        fab_url="https://www.fab.com/listings/66666666-7777-8888-9999-aaaaaaaaaaaa",
        marketplace_url="com.epicgames.launcher://ue/Fab/product/00000000-0000-0000-0000-000000000000",
    )
    plugin = parse_uplugin(path)

    assert plugin.listing_url.startswith("https://")
    assert plugin.fab_product_id == "66666666-7777-8888-9999-aaaaaaaaaaaa"


def test_no_listing_url_is_not_live(tmp_path):
    plugin = parse_uplugin(_write_uplugin(tmp_path / "New", "New", []))

    assert not plugin.is_live
    assert plugin.fab_product_id == ""


def test_reads_module_platform_lists(tmp_path):
    """Requirements 4.3.6.b; UE4's spelling is accepted too."""
    path = _write_uplugin(tmp_path / "Plat", "Plat", [])
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    data["Modules"] = [
        {"Name": "A", "Type": "Runtime", "PlatformAllowList": ["Win64", "Mac"]},
        {"Name": "B", "Type": "Editor", "WhitelistPlatforms": ["Win64"]},
        {"Name": "C", "Type": "Runtime", "PlatformDenyList": ["IOS"]},
        {"Name": "D", "Type": "Runtime"},
    ]
    path.write_text(json.dumps(data), encoding="utf-8")

    modules = {m.name: m for m in parse_uplugin(path).modules}

    assert modules["A"].platform_allow_list == ["Win64", "Mac"]
    assert modules["B"].platform_allow_list == ["Win64"]
    assert modules["C"].platform_deny_list == ["IOS"]
    assert modules["D"].platform_allow_list == []
