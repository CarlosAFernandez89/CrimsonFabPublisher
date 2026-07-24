"""Engine detection: registry/manifest sources plus hand-registered roots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fabpublisher import engines as engines_module
from fabpublisher.engines import detect_engines, engine_from_root


def _make_engine(
    root: Path, *, version: tuple[int, int] | None = (5, 6), installed: bool = True
) -> Path:
    """A folder shaped enough like an engine install to be detected."""
    batch = root / "Engine" / "Build" / "BatchFiles"
    batch.mkdir(parents=True, exist_ok=True)
    (batch / "RunUAT.bat").write_text("@echo off\n")
    if version is not None:
        (root / "Engine" / "Build" / "Build.version").write_text(
            json.dumps({"MajorVersion": version[0], "MinorVersion": version[1],
                        "PatchVersion": 3})
        )
    if installed:
        (root / "Engine" / "Build" / "InstalledBuild.txt").write_text("")
    return root


@pytest.fixture(autouse=True)
def no_registry(monkeypatch):
    """Silence the real machine's registry and manifest for these tests."""
    monkeypatch.setattr(engines_module, "_read_hklm_installs", list)
    monkeypatch.setattr(engines_module, "_read_launcher_dat", list)
    monkeypatch.setattr(engines_module, "_read_hkcu_source_builds", list)


def test_engine_from_root_reads_build_version(tmp_path: Path):
    engine = engine_from_root(_make_engine(tmp_path / "UE_5.6"))
    assert engine is not None
    # Major.minor only, so the label matches the auto-detected form.
    assert engine.version == "5.6"
    assert engine.label == "UE_5.6"
    assert engine.is_source_build is False


def test_engine_from_root_falls_back_to_the_folder_name(tmp_path: Path):
    engine = engine_from_root(_make_engine(tmp_path / "UE_5.4", version=None))
    assert engine is not None
    assert engine.version == "5.4"


def test_source_build_detected_by_missing_installed_marker(tmp_path: Path):
    engine = engine_from_root(
        _make_engine(tmp_path / "UnrealEngine", version=(5, 7), installed=False)
    )
    assert engine is not None
    assert engine.is_source_build is True
    assert engine.label == "UE_5.7 (source)"


def test_engine_from_root_rejects_a_non_engine_folder(tmp_path: Path):
    plain = tmp_path / "NotAnEngine"
    plain.mkdir()
    assert engine_from_root(plain) is None
    assert engine_from_root(tmp_path / "does-not-exist") is None


def test_manual_roots_are_included(tmp_path: Path):
    _make_engine(tmp_path / "UE_5.6")
    _make_engine(tmp_path / "UE_5.8", version=(5, 8))
    found = detect_engines([tmp_path / "UE_5.6", tmp_path / "UE_5.8"])
    assert [e.label for e in found] == ["UE_5.6", "UE_5.8"]


def test_manual_roots_are_sorted_by_version(tmp_path: Path):
    for major, minor in ((5, 8), (5, 4), (5, 6)):
        _make_engine(tmp_path / f"UE_{major}.{minor}", version=(major, minor))
    found = detect_engines(
        [tmp_path / "UE_5.8", tmp_path / "UE_5.4", tmp_path / "UE_5.6"]
    )
    assert [e.version for e in found] == ["5.4", "5.6", "5.8"]


def test_bad_manual_root_is_skipped_not_fatal(tmp_path: Path):
    _make_engine(tmp_path / "UE_5.6")
    junk = tmp_path / "junk"
    junk.mkdir()
    found = detect_engines([junk, tmp_path / "UE_5.6", tmp_path / "gone"])
    assert [e.label for e in found] == ["UE_5.6"]


def test_manual_root_duplicating_a_detected_one_keeps_the_detected_entry(
    tmp_path: Path, monkeypatch
):
    from fabpublisher.models import EngineInfo

    root = _make_engine(tmp_path / "UE_5.6")
    detected = EngineInfo(identifier="5.6", version="5.6", root=root)
    monkeypatch.setattr(engines_module, "_read_hklm_installs", lambda: [detected])

    found = detect_engines([root])
    assert len(found) == 1
    # The registry identifier wins, so a previously saved engine_id still resolves.
    assert found[0].identifier == "5.6"


def test_no_sources_and_no_manual_roots_yields_nothing(tmp_path: Path):
    assert detect_engines() == []
    assert detect_engines([]) == []
