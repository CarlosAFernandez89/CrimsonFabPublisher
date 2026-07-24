"""Shared fixtures: build a tiny fake plugin suite on disk."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_uplugin(
    plugin_dir: Path,
    name: str,
    deps: list[str],
    *,
    engine_version: str = "5.8.0",
    can_contain_content: bool = False,
    bom: bool = False,
) -> Path:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "Source" / name).mkdir(parents=True, exist_ok=True)
    (plugin_dir / "Source" / name / f"{name}.cpp").write_text("// code\n")
    data = {
        "FileVersion": 3,
        "FriendlyName": name,
        "VersionName": "1.0",
        "EngineVersion": engine_version,
        "CanContainContent": can_contain_content,
        "Modules": [{"Name": name, "Type": "Runtime", "LoadingPhase": "Default"}],
        "Plugins": [{"Name": d, "Enabled": True} for d in deps],
    }
    encoding = "utf-8-sig" if bom else "utf-8"
    path = plugin_dir / f"{name}.uplugin"
    path.write_text(json.dumps(data, indent=2), encoding=encoding)
    return path


@pytest.fixture
def suite(tmp_path: Path) -> Path:
    """A small suite: Common <- Ability <- Core, plus engine/external deps.

    Dependency edges (X depends on Y):
      Ability -> Common, GameplayAbilities(engine), ThirdParty(external)
      Core    -> Common, Ability
      Common  -> (none in-suite)
    """
    root = tmp_path / "Plugins"
    _write_uplugin(root / "Common", "Common", [], bom=True)
    _write_uplugin(
        root / "Ability", "Ability", ["Common", "GameplayAbilities", "ThirdParty"]
    )
    _write_uplugin(root / "Core", "Core", ["Common", "Ability"], can_contain_content=True)
    return root
