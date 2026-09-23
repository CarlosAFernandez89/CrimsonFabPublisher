"""Working out what a plugin actually needs installed.

The `.uplugin` is not enough on its own: a module can depend on a plugin its
descriptor never mentions, which is exactly the omission a Fab reviewer picks
up on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fabpublisher.models import Dependency, DependencyKind
from fabpublisher.listing.requires import (
    Requirements,
    module_names,
    module_owners,
    modules_used,
    resolve,
)

from .conftest import _write_uplugin

BUILD_CS = """
// Copyright 2026 Example Publisher.
using UnrealBuildTool;

public class Demo : ModuleRules
{
    public Demo(ReadOnlyTargetRules Target) : base(Target)
    {
        PublicDependencyModuleNames.AddRange(new string[]
        {
            "Core",
            "GameplayAbilities",   // TSubclassOf<UGameplayAbility>
            "SharedCore",          // our own shared module
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "AssetRegistry",
        });
        PrivateDependencyModuleNames.Add("Slate");
    }
}
"""


def test_reads_both_add_range_and_add():
    names = module_names(BUILD_CS)

    assert names == {"Core", "GameplayAbilities", "SharedCore", "AssetRegistry", "Slate"}


def test_a_quoted_name_inside_a_comment_is_not_a_dependency():
    """Real Build.cs files annotate every line; a comment must not be parsed."""
    text = '''
        PublicDependencyModuleNames.AddRange(new string[]
        {
            "Core",   // not "Engine", we deliberately avoid it
        });
    '''

    assert module_names(text) == {"Core"}


def test_a_block_comment_is_stripped():
    text = '''
        /* PublicDependencyModuleNames.AddRange(new string[] { "Ghost" }); */
        PublicDependencyModuleNames.AddRange(new string[] { "Core" });
    '''

    assert module_names(text) == {"Core"}


def test_no_dependency_arrays_is_empty_not_an_error():
    assert module_names("public class X : ModuleRules {}") == set()


def test_modules_used_walks_the_source_tree_and_drops_our_own(tmp_path):
    _write_uplugin(tmp_path / "Demo", "Demo", [])
    build = tmp_path / "Demo" / "Source" / "Demo" / "Demo.Build.cs"
    build.write_text(BUILD_CS, encoding="utf-8")

    from fabpublisher.uplugin import parse_uplugin

    plugin = parse_uplugin(tmp_path / "Demo" / "Demo.uplugin")
    used = modules_used(plugin)

    assert "GameplayAbilities" in used
    assert "Demo" not in used, "a plugin does not require itself"


def test_module_owners_maps_modules_back_to_their_plugin(tmp_path):
    path = tmp_path / "Abilities.uplugin"
    path.write_text(
        json.dumps(
            {"Modules": [{"Name": "GameplayAbilities"}, {"Name": "GameplayAbilitiesEditor"}]}
        ),
        encoding="utf-8",
    )

    owners = module_owners([path])

    assert owners["GameplayAbilities"] == "Abilities"
    assert owners["GameplayAbilitiesEditor"] == "Abilities"


def test_module_owners_skips_unreadable_descriptors(tmp_path):
    broken = tmp_path / "Broken.uplugin"
    broken.write_text("{ not json", encoding="utf-8")

    assert module_owners([broken, tmp_path / "missing.uplugin"]) == {}


# ---------------------------------------------------------------- resolution
@pytest.fixture
def plugin(tmp_path):
    from fabpublisher.uplugin import parse_uplugin

    _write_uplugin(tmp_path / "Demo", "Demo", [])
    (tmp_path / "Demo" / "Source" / "Demo" / "Demo.Build.cs").write_text(
        BUILD_CS, encoding="utf-8"
    )
    return parse_uplugin(tmp_path / "Demo" / "Demo.uplugin")


def test_splits_prerequisites_into_suite_engine_and_core(plugin):
    owners = {
        "GameplayAbilities": "GameplayAbilities",
        "SharedCore": "SharedCore",
        # Core, AssetRegistry and Slate belong to no plugin.
    }

    result = resolve(plugin, owners, {"GameplayAbilities"}, {"SharedCore", "Demo"})

    assert result.suite == ("SharedCore",)
    assert result.engine == ("GameplayAbilities",)
    assert "Core" in result.core_modules
    assert "Slate" in result.core_modules


def test_a_build_cs_dependency_the_descriptor_forgot_is_still_found(plugin):
    """The omission a reviewer notices."""
    assert plugin.dependency_names == []

    result = resolve(plugin, {"GameplayAbilities": "GameplayAbilities"}, {"GameplayAbilities"}, {"Demo"})

    assert "GameplayAbilities" in result.engine


def test_descriptor_dependencies_are_honoured_too(plugin):
    plugin.dependencies = [
        Dependency("SharedCore", DependencyKind.SUITE),
        Dependency("Niagara", DependencyKind.ENGINE),
        Dependency("SomeVendorThing", DependencyKind.EXTERNAL),
    ]

    result = resolve(plugin, {}, set(), {"SharedCore", "Demo"})

    assert "SharedCore" in result.suite
    assert "Niagara" in result.engine
    assert "SomeVendorThing" in result.unknown


def test_required_is_everything_a_customer_must_install(plugin):
    result = Requirements(
        suite=("SharedCore",), engine=("Niagara",), unknown=("Vendor",)
    )

    assert result.required == ("Niagara", "SharedCore", "Vendor")


def test_a_plugin_with_no_source_folder_resolves_to_nothing(tmp_path):
    from fabpublisher.uplugin import parse_uplugin

    _write_uplugin(tmp_path / "Bare", "Bare", [])
    import shutil

    shutil.rmtree(tmp_path / "Bare" / "Source")
    plugin = parse_uplugin(tmp_path / "Bare" / "Bare.uplugin")

    assert modules_used(plugin) == set()
    assert resolve(plugin, {}, set(), set()).required == ()
