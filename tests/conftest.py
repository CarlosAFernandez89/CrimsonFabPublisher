"""Shared fixtures: build a tiny fake plugin suite on disk."""

from __future__ import annotations

import json
import struct
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
    description: str = "",
    category: str = "",
    fab_url: str = "",
    marketplace_url: str = "",
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
        "Description": description,
        "Category": category,
        "FabURL": fab_url,
        "MarketplaceURL": marketplace_url,
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


def write_png(path: Path, width: int = 1920, height: int = 1080) -> Path:
    """A file with a real PNG header, which is all the size reader looks at."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ihdr = struct.pack(">II", width, height) + bytes([8, 6, 0, 0, 0])
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + ihdr
        + bytes(4)          # CRC, never checked
        + bytes(64)         # filler, so the file has a plausible size
    )
    return path


@pytest.fixture
def listings(tmp_path: Path) -> Path:
    """A listings workspace holding a thumbnail for each `suite` plugin."""
    root = tmp_path / "listings"
    (root / "media").mkdir(parents=True)
    for name in ("Common", "Ability", "Core"):
        write_png(root / "media" / name / "thumbnail.png")
    return root
