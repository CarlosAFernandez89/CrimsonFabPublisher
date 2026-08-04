"""Building from a filtered staging copy, so excluded files never reach the build."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from fabpublisher.builder import force_rmtree, stage_plugin
from fabpublisher.models import PluginInfo
from fabpublisher.shipfilter import ShipFilter


def _plugin(root: Path, name: str = "Core") -> PluginInfo:
    plugin_dir = root / name
    for rel, body in (
        (f"{name}.uplugin", "{}"),
        ("Source/Core/Core.Build.cs", "// build rules"),
        ("Source/Core/Public/Core.h", "class FCore {};"),
        ("Content/B_Thing.uasset", "asset"),
        ("README.md", "# docs"),
        ("Docs/guide.md", "# guide"),
        ("Binaries/Win64/Core.dll", "stale"),
        ("Intermediate/Build/x.obj", "stale"),
        (".git/config", "vcs"),
    ):
        target = plugin_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return PluginInfo(
        name=name, path=plugin_dir, uplugin_path=plugin_dir / f"{name}.uplugin"
    )


def _staged(stage_dir: Path) -> set[str]:
    return {
        p.relative_to(stage_dir).as_posix()
        for p in stage_dir.rglob("*")
        if p.is_file()
    }


def test_staging_drops_default_build_artifacts(tmp_path):
    plugin = _plugin(tmp_path)
    stage = tmp_path / "stage"
    stage_plugin(plugin, stage, ShipFilter(), log=lambda _: None)

    files = _staged(stage)
    assert "Core.uplugin" in files
    assert "Source/Core/Public/Core.h" in files
    assert "Content/B_Thing.uasset" in files
    assert not any(f.startswith(("Binaries/", "Intermediate/", ".git/")) for f in files)


def test_staging_drops_user_excluded_patterns_before_the_build(tmp_path):
    """The point of staging: *.md is gone at compile time, not just at zip time."""
    plugin = _plugin(tmp_path)
    stage = tmp_path / "stage"
    stage_plugin(plugin, stage, ShipFilter(["*.md"]), log=lambda _: None)

    files = _staged(stage)
    assert not any(f.endswith(".md") for f in files)
    assert "Source/Core/Public/Core.h" in files


def test_staging_never_touches_the_plugin_source(tmp_path):
    plugin = _plugin(tmp_path)
    before = {p.relative_to(plugin.path).as_posix() for p in plugin.path.rglob("*")}

    stage_plugin(plugin, tmp_path / "stage", ShipFilter(["*.md"]), log=lambda _: None)

    after = {p.relative_to(plugin.path).as_posix() for p in plugin.path.rglob("*")}
    assert before == after
    assert (plugin.path / "README.md").is_file()
    assert (plugin.path / "Binaries" / "Win64" / "Core.dll").is_file()


def test_staging_returns_the_descriptor_to_build(tmp_path):
    plugin = _plugin(tmp_path)
    stage = tmp_path / "stage"
    staged_uplugin = stage_plugin(plugin, stage, ShipFilter(), log=lambda _: None)
    assert staged_uplugin == stage / "Core.uplugin"
    assert staged_uplugin.is_file()


def test_restaging_over_a_read_only_file_from_a_previous_run(tmp_path):
    """Perforce leaves sources read-only; copy2 carries that into the stage.

    Windows then refuses to delete the staged copy, so a second build used to
    fail with `Permission denied` on the leftover file.
    """
    plugin = _plugin(tmp_path)
    readonly_src = plugin.path / "Resources" / "Icon.png"
    readonly_src.parent.mkdir(parents=True, exist_ok=True)
    readonly_src.write_text("icon", encoding="utf-8")
    os.chmod(readonly_src, stat.S_IREAD)

    stage = tmp_path / "stage"
    stage_plugin(plugin, stage, ShipFilter(), log=lambda _: None)
    assert not os.access(stage / "Resources" / "Icon.png", os.W_OK)

    # The second run is the one that used to blow up.
    stage_plugin(plugin, stage, ShipFilter(), log=lambda _: None)
    assert (stage / "Resources" / "Icon.png").is_file()


def test_force_rmtree_removes_read_only_files(tmp_path):
    target = tmp_path / "tree"
    (target / "nested").mkdir(parents=True)
    locked = target / "nested" / "locked.bin"
    locked.write_text("x", encoding="utf-8")
    os.chmod(locked, stat.S_IREAD)

    force_rmtree(target)
    assert not target.exists()


def test_force_rmtree_tolerates_a_missing_path(tmp_path):
    force_rmtree(tmp_path / "never-existed")


def test_staging_replaces_a_previous_run(tmp_path):
    plugin = _plugin(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "leftover.txt").write_text("old", encoding="utf-8")

    stage_plugin(plugin, stage, ShipFilter(), log=lambda _: None)
    assert not (stage / "leftover.txt").exists()
