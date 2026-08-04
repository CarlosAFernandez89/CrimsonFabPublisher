"""Blueprint and C++ class counting for the FAB submission form."""

from __future__ import annotations

from fabpublisher.assetstats import (
    count_blueprints,
    count_cpp_classes,
    is_blueprint_asset,
)


def _uasset(path, *names: str) -> None:
    """A stand-in .uasset whose name table holds `names`.

    Real packages wrap these in a length-prefixed table; only the presence of
    the byte strings matters to the scanner.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    body = b"\xc1\x83\x2a\x9e" + b"".join(n.encode() + b"\x00" for n in names)
    path.write_bytes(body)


def test_blueprint_detected_regardless_of_naming(tmp_path):
    for stem in ("B_Manager", "W_SaveMenu", "AnimBP_Hero", "NoPrefixAtAll"):
        asset = tmp_path / f"{stem}.uasset"
        _uasset(asset, "BlueprintGeneratedClass", f"{stem}_C")
        assert is_blueprint_asset(asset), stem


def test_non_blueprint_assets_are_not_counted(tmp_path):
    material = tmp_path / "M_Glow.uasset"
    _uasset(material, "Material", "MaterialExpressionAdd")
    assert not is_blueprint_asset(material)


def test_asset_merely_referencing_a_blueprint_is_not_counted(tmp_path):
    """A DataTable pointing at B_Manager carries both BP markers but is not a BP."""
    table = tmp_path / "DT_Items.uasset"
    _uasset(table, "DataTable", "BlueprintGeneratedClass", "B_Manager_C")
    assert not is_blueprint_asset(table)


def test_count_blueprints_walks_content_and_skips_levels(tmp_path):
    content = tmp_path / "Content"
    _uasset(content / "B_Manager.uasset", "BlueprintGeneratedClass", "B_Manager_C")
    _uasset(content / "UI" / "W_Menu.uasset", "BlueprintGeneratedClass", "W_Menu_C")
    _uasset(content / "M_Glow.uasset", "Material")
    # A level references its actors' generated classes but is not itself a BP.
    _uasset(content / "L_Test.umap", "BlueprintGeneratedClass", "L_Test_C")
    assert count_blueprints(tmp_path) == 2


def test_count_blueprints_without_content_folder(tmp_path):
    assert count_blueprints(tmp_path) == 0


def _header(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_counts_reflected_and_plain_declarations(tmp_path):
    _header(
        tmp_path / "Source" / "Public" / "Types.h",
        """
        #pragma once

        UCLASS()
        class MYPLUGIN_API UMySubsystem : public UGameInstanceSubsystem
        {
            GENERATED_BODY()
        };

        USTRUCT(BlueprintType)
        struct FMySaveData
        {
            GENERATED_BODY()
        };

        class FMyInternalHelper
        {
        };
        """,
    )
    assert count_cpp_classes(tmp_path) == 3


def test_forward_declarations_and_enums_are_not_classes(tmp_path):
    _header(
        tmp_path / "Source" / "Public" / "Fwd.h",
        """
        class UOtherThing;
        struct FSomethingElse;

        enum class EMyMode : uint8
        {
            First,
        };

        class FReal
        {
            friend class FBuddy;
        };
        """,
    )
    assert count_cpp_classes(tmp_path) == 1


def test_commented_out_declarations_are_ignored(tmp_path):
    _header(
        tmp_path / "Source" / "Public" / "Commented.h",
        """
        // class FOldThing : public FBase {};
        /*
        class FAlsoGone
        {
        };
        */
        class FKept
        {
        };
        """,
    )
    assert count_cpp_classes(tmp_path) == 1


def test_third_party_headers_are_excluded(tmp_path):
    _header(tmp_path / "Source" / "Public" / "Mine.h", "class FMine {};")
    _header(
        tmp_path / "Source" / "ThirdParty" / "vendor" / "lib.h",
        "class VendorThing {};\nstruct VendorData {};",
    )
    assert count_cpp_classes(tmp_path) == 1


def test_cpp_files_are_not_scanned(tmp_path):
    _header(tmp_path / "Source" / "Public" / "Mine.h", "class FMine {};")
    _header(tmp_path / "Source" / "Private" / "Mine.cpp", "class FImplDetail {};")
    assert count_cpp_classes(tmp_path) == 1


def test_count_cpp_classes_without_source_folder(tmp_path):
    assert count_cpp_classes(tmp_path) == 0
