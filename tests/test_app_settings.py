"""Config persistence and the observable settings wrapper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fabpublisher import config as config_module
from fabpublisher.config import Config
from fabpublisher.models import Platform
from fabpublisher.ui.app_settings import AppSettings, patterns_from_text, platform_from_mask


@pytest.fixture(autouse=True)
def app_data(tmp_path: Path, monkeypatch):
    """Redirect config.json into tmp_path for every test in this module."""
    monkeypatch.setattr(config_module, "data_dir", lambda: tmp_path)
    return tmp_path


def test_defaults_when_no_file(app_data: Path):
    settings = AppSettings.load()
    assert settings.plugins_root == ""
    assert settings.platforms == Platform.WIN64  # first-run default
    assert settings.auto_open_output is True
    assert settings.selection == set()


def test_round_trip(app_data: Path):
    settings = AppSettings.load()
    settings.plugins_root = "E:/Dev/Plugins"
    settings.output_dir = "E:/Out"
    settings.engine_id = "UE_5.6"
    settings.platforms = Platform.WIN64 | Platform.LINUX
    settings.ship_patterns = ["*.md", "Docs/"]
    settings.auto_open_output = False
    settings.set_selection_ordered(["Common", "Core"])
    settings.save()

    reloaded = AppSettings.load()
    assert reloaded.plugins_root == "E:/Dev/Plugins"
    assert reloaded.output_dir == "E:/Out"
    assert reloaded.engine_id == "UE_5.6"
    assert reloaded.platforms == Platform.WIN64 | Platform.LINUX
    assert reloaded.ship_patterns == ["*.md", "Docs/"]
    assert reloaded.auto_open_output is False
    assert reloaded.selection == {"Common", "Core"}


def test_setters_emit_only_on_real_change(app_data: Path):
    settings = AppSettings.load()
    seen: list[str] = []
    settings.plugins_root_changed.connect(seen.append)

    settings.plugins_root = "E:/One"
    settings.plugins_root = "E:/One"  # same value
    settings.plugins_root = "  E:/One  "  # same after strip
    assert seen == ["E:/One"]


def test_empty_platform_mask_survives_a_reload(app_data: Path):
    """Unchecking every platform must not silently restore Win64."""
    settings = AppSettings.load()
    settings.platforms = Platform.NONE
    settings.save()
    assert AppSettings.load().platforms == Platform.NONE


def test_missing_file_loads_defaults(app_data: Path):
    assert not (app_data / "config.json").exists()
    assert Config.load().plugins_root == ""


def test_corrupt_file_loads_defaults(app_data: Path):
    (app_data / "config.json").write_text("{not json at all", encoding="utf-8")
    assert Config.load().plugins_root == ""


def test_non_object_json_loads_defaults(app_data: Path):
    (app_data / "config.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert Config.load().plugins_root == ""


def test_out_of_range_platform_mask_does_not_crash(app_data: Path):
    (app_data / "config.json").write_text(
        json.dumps({"platform_mask": 4096}), encoding="utf-8"
    )
    assert AppSettings.load().platforms == Platform.NONE


def test_utf8_bom_does_not_reset_settings(app_data: Path):
    """PowerShell and several editors write a BOM; plain utf-8 would silently
    throw the whole file away."""
    (app_data / "config.json").write_text(
        json.dumps({"plugins_root": "E:/X"}), encoding="utf-8-sig"
    )
    assert Config.load().plugins_root == "E:/X"


def test_unknown_keys_are_ignored(app_data: Path):
    (app_data / "config.json").write_text(
        json.dumps({"plugins_root": "E:/X", "from_the_future": 1}), encoding="utf-8"
    )
    assert Config.load().plugins_root == "E:/X"


def test_save_is_atomic_and_leaves_no_temp_file(app_data: Path):
    cfg = Config(plugins_root="E:/X")
    cfg.save()
    assert (app_data / "config.json").is_file()
    assert list(app_data.glob("*.tmp")) == []
    assert json.loads((app_data / "config.json").read_text())["plugins_root"] == "E:/X"


def test_window_geometry_round_trips_bytes(app_data: Path):
    settings = AppSettings.load()
    settings.window_geometry = b"\x01\x02\xff"
    settings.save()
    assert AppSettings.load().window_geometry == b"\x01\x02\xff"


def test_window_geometry_tolerates_garbage(app_data: Path):
    (app_data / "config.json").write_text(
        json.dumps({"window_geometry": "!!!not base64!!!"}), encoding="utf-8"
    )
    assert AppSettings.load().window_geometry == b""


@pytest.mark.parametrize(
    "value, expected",
    [(0, Platform.NONE), (1, Platform.WIN64), (3, Platform.WIN64 | Platform.LINUX),
     (4096, Platform.NONE), ("nonsense", Platform.NONE), (None, Platform.NONE)],
)
def test_platform_from_mask(value, expected):
    assert platform_from_mask(value) == expected


def test_patterns_from_text_drops_blank_lines():
    assert patterns_from_text("*.md\n\n  \nDocs/\n") == ["*.md", "Docs/"]
