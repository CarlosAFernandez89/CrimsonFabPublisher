"""Packaging requirements, one test per rule.

Each case builds the smallest tree that trips exactly one rule, so a failure
names the requirement that broke rather than "the audit changed".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fabpublisher.models import Dependency, DependencyKind
from fabpublisher.listing.pluginaudit import audit_plugin, blocking_dependency_names
from fabpublisher.uplugin import parse_uplugin

from .conftest import _write_uplugin

GOOD_HEADER = "// Copyright 2026 Carlos Fernandez. All rights reserved.\n"


def _plugin(tmp_path: Path, name: str = "Demo", **descriptor):
    """A plugin that passes every rule, ready to be broken one field at a time."""
    path = _write_uplugin(tmp_path / name, name, [], **descriptor)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    data["Modules"] = [
        {"Name": name, "Type": "Runtime", "PlatformAllowList": ["Win64"]}
    ]
    data.setdefault("FabURL", "")
    data["FabURL"] = descriptor.get("fab_url") or "https://www.fab.com/listings/abc"
    path.write_text(json.dumps(data), encoding="utf-8")

    source = tmp_path / name / "Source" / name
    (source / f"{name}.cpp").write_text(GOOD_HEADER + "// code\n")
    (source / f"{name}.Build.cs").write_text(GOOD_HEADER + "// build\n")
    return parse_uplugin(path)


def _keys(issues, level=None):
    return {i.key for i in issues if level is None or i.level == level}


def test_a_well_formed_plugin_reports_nothing(tmp_path):
    assert audit_plugin(_plugin(tmp_path)) == []


def test_missing_folder_is_reported_not_raised(tmp_path):
    plugin = _plugin(tmp_path)
    plugin.path = tmp_path / "gone"

    issues = audit_plugin(plugin)

    assert [i.level for i in issues] == ["error"]


# ------------------------------------------------------------------ descriptor
def test_engine_version_must_be_major_minor_patch(tmp_path):
    plugin = _plugin(tmp_path, engine_version="5.8")

    issues = audit_plugin(plugin)

    assert "EngineVersion" in _keys(issues, "error")
    assert "4.3.6.a" in next(i.message for i in issues if i.key == "EngineVersion")


def test_module_without_platform_list_is_an_error(tmp_path):
    plugin = _plugin(tmp_path)
    plugin.modules[0].platform_allow_list = []

    assert "PlatformAllowList" in _keys(audit_plugin(plugin), "error")


def test_platform_deny_list_also_satisfies_the_rule(tmp_path):
    plugin = _plugin(tmp_path)
    plugin.modules[0].platform_allow_list = []
    plugin.modules[0].platform_deny_list = ["IOS"]

    assert "PlatformAllowList" not in _keys(audit_plugin(plugin))


def test_missing_fab_url_warns_rather_than_blocks(tmp_path):
    """It cannot be filled in before the first submission, so it never blocks."""
    plugin = _plugin(tmp_path)
    plugin.fab_url = ""

    issues = audit_plugin(plugin)
    fab_url = [i for i in issues if i.key == "FabURL"]

    assert [i.level for i in fab_url] == ["warning"]
    assert "after the first submission" in fab_url[0].message


def test_live_listing_missing_fab_url_says_the_id_is_available(tmp_path):
    plugin = _plugin(tmp_path)
    plugin.fab_url = ""
    plugin.marketplace_url = (
        "com.epicgames.launcher://ue/Fab/product/"
        "11111111-2222-3333-4444-555555555555"
    )

    message = next(i.message for i in audit_plugin(plugin) if i.key == "FabURL")

    assert "the listing is live" in message


def test_dependency_on_a_user_made_plugin_is_an_error(tmp_path):
    """Fab 4.3.6.d - the rule that decides whether the suite is submittable."""
    plugin = _plugin(tmp_path)
    plugin.dependencies = [
        Dependency("GameplayAbilities", DependencyKind.ENGINE),
        Dependency("SharedCore", DependencyKind.SUITE),
    ]

    issues = audit_plugin(plugin)
    message = next(i.message for i in issues if i.key == "Plugins")

    assert "SharedCore" in message
    assert "GameplayAbilities" not in message, "engine plugins are explicitly allowed"
    assert blocking_dependency_names(plugin) == ["SharedCore"]


def test_engine_only_dependencies_are_fine(tmp_path):
    plugin = _plugin(tmp_path)
    plugin.dependencies = [Dependency("GameplayAbilities", DependencyKind.ENGINE)]

    assert "Plugins" not in _keys(audit_plugin(plugin))


# ------------------------------------------------------------------------ tree
def test_path_longer_than_the_limit_is_an_error(tmp_path):
    plugin = _plugin(tmp_path)
    deep = plugin.path / "Content" / ("A" * 90) / ("B" * 90)
    deep.mkdir(parents=True)
    (deep / "asset.uasset").write_bytes(b"x")

    assert "path-length" in _keys(audit_plugin(plugin), "error")


def test_build_cs_double_extension_is_not_a_naming_violation(tmp_path):
    """MyModule.Build.cs has two suffixes; stripping one flags every plugin."""
    assert "ascii-names" not in _keys(audit_plugin(_plugin(tmp_path)))


def test_hyphenated_name_is_a_naming_violation(tmp_path):
    plugin = _plugin(tmp_path)
    content = plugin.path / "Content"
    content.mkdir(exist_ok=True)
    (content / "My-Button.uasset").write_bytes(b"x")

    issues = audit_plugin(plugin)

    assert "ascii-names" in _keys(issues, "error")
    assert "My-Button.uasset" in next(
        i.message for i in issues if i.key == "ascii-names"
    )


def test_shipped_executable_is_an_error(tmp_path):
    plugin = _plugin(tmp_path)
    (plugin.path / "Resources").mkdir(exist_ok=True)
    (plugin.path / "Resources" / "tool.exe").write_bytes(b"MZ")

    assert "no-executables" in _keys(audit_plugin(plugin), "error")


def test_plugin_with_no_build_cs_has_no_code_module(tmp_path):
    plugin = _plugin(tmp_path)
    next(plugin.path.rglob("*.Build.cs")).unlink()

    assert "code-module" in _keys(audit_plugin(plugin), "error")


def test_extra_folder_needs_a_filter_plugin_ini(tmp_path):
    plugin = _plugin(tmp_path)
    docs = plugin.path / "Docs"
    docs.mkdir()
    (docs / "diagram.png").write_bytes(b"x")

    assert "filter-plugin-ini" in _keys(audit_plugin(plugin), "warning")


def test_filter_plugin_ini_silences_the_extra_folder_warning(tmp_path):
    plugin = _plugin(tmp_path)
    docs = plugin.path / "Docs"
    docs.mkdir()
    (docs / "diagram.png").write_bytes(b"x")
    config = plugin.path / "Config"
    config.mkdir(exist_ok=True)
    (config / "FilterPlugin.ini").write_text("[FilterPlugin]\n/Docs/...\n")

    assert "filter-plugin-ini" not in _keys(audit_plugin(plugin))


def test_local_folders_are_stripped_before_the_audit_sees_them(tmp_path):
    """Binaries and friends never reach the zip, so they are not findings."""
    plugin = _plugin(tmp_path)
    binaries = plugin.path / "Binaries" / "Win64"
    binaries.mkdir(parents=True)
    (binaries / "Bad-Name.dll").write_bytes(b"x")

    assert audit_plugin(plugin) == []


# ------------------------------------------------------------------- copyright
@pytest.mark.parametrize(
    "header",
    [
        "// Copyright Epic Games, Inc. All Rights Reserved.\n",
        "// Copyright Carlos Fernandez\n",
        "",
    ],
    ids=["epic-boilerplate", "no-year", "none"],
)
def test_source_file_without_a_publisher_notice_is_an_error(tmp_path, header):
    plugin = _plugin(tmp_path)
    source = plugin.path / "Source" / plugin.name / "Extra.h"
    source.write_text(header + "#pragma once\n")

    issues = audit_plugin(plugin)

    assert "copyright-header" in _keys(issues, "error")
    assert "Extra.h" in next(i.message for i in issues if i.key == "copyright-header")


def test_copyright_notice_with_a_year_passes(tmp_path):
    plugin = _plugin(tmp_path)
    (plugin.path / "Source" / plugin.name / "Extra.h").write_text(
        "// (c) 2026 Carlos Fernandez\n#pragma once\n"
    )

    assert "copyright-header" not in _keys(audit_plugin(plugin))
