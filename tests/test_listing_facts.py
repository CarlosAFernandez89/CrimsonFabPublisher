"""Reading facts off real bytes: images and submission zips.

Both readers exist so the app can avoid a dependency, so both are tested
against files built here rather than against mocks.
"""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import pytest

from fabpublisher.listing.imagefacts import read_dimensions, read_image, sha256_file
from fabpublisher.listing.zipfacts import read_zip

from .conftest import write_png


def _jpeg(path: Path, width: int, height: int) -> Path:
    """The smallest byte string with a findable SOF0 marker."""
    path.write_bytes(
        b"\xff\xd8"
        + b"\xff\xe0" + struct.pack(">H", 4) + b"AB"          # APP0, skipped
        + b"\xff\xc0" + struct.pack(">H", 11) + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x01\x11\x00"
    )
    return path


# -------------------------------------------------------------------- images
def test_reads_png_dimensions(tmp_path):
    assert read_dimensions(write_png(tmp_path / "a.png", 1920, 1080)) == (1920, 1080)


def test_reads_jpeg_dimensions(tmp_path):
    assert read_dimensions(_jpeg(tmp_path / "a.jpg", 800, 600)) == (800, 600)


@pytest.mark.parametrize(
    "make",
    [
        lambda p: p.write_bytes(b"not an image at all"),
        lambda p: p.write_bytes(b"\x89PNG\r\n\x1a\n"),  # truncated before IHDR
        lambda p: p.write_bytes(b""),
    ],
    ids=["garbage", "truncated", "empty"],
)
def test_unrecognised_image_returns_none_rather_than_raising(tmp_path, make):
    """The caller degrades to a warning; nothing here may throw."""
    path = tmp_path / "a.png"
    make(path)

    assert read_dimensions(path) is None


def test_a_missing_file_returns_none(tmp_path):
    assert read_image(tmp_path / "nope.png", "nope.png") is None
    assert read_dimensions(tmp_path / "nope.png") is None


def test_image_facts_record_a_relative_source_not_a_path(tmp_path):
    write_png(tmp_path / "deep" / "a.png")

    facts = read_image(tmp_path / "deep" / "a.png", "Demo/a.png")

    assert facts.source == "Demo/a.png"
    assert facts.dimensions_known
    assert len(facts.sha256) == 64


def test_digest_is_stable_across_reads(tmp_path):
    path = write_png(tmp_path / "a.png")

    assert sha256_file(path) == sha256_file(path)


def test_dimensions_unknown_is_reported_not_fatal(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"nonsense but present")

    facts = read_image(path, "a.png")

    assert facts is not None
    assert not facts.dimensions_known


# ---------------------------------------------------------------------- zips
def _zip(path: Path, names: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in names.items():
            archive.writestr(name, data)
    return path


def test_reads_a_well_formed_plugin_zip(tmp_path):
    path = _zip(
        tmp_path / "Demo.zip",
        {
            "Demo.uplugin": b"{}",
            "Source/DemoRuntime/DemoRuntime.Build.cs": b"// x",
            "Source/DemoEditor/DemoEditor.Build.cs": b"// x",
            "Content/thing.uasset": b"x",
            "Config/FilterPlugin.ini": b"x",
        },
    )

    facts = read_zip(path)

    assert facts.name == "Demo.zip"
    assert facts.has_uplugin
    assert facts.has_source_build_cs
    assert facts.has_content
    assert facts.has_config
    assert facts.source_modules == ("DemoEditor", "DemoRuntime")


def test_a_nested_uplugin_does_not_count_as_root(tmp_path):
    """Fab needs the descriptor at the archive root, not one level down."""
    path = _zip(tmp_path / "Demo.zip", {"Demo/Demo.uplugin": b"{}"})

    assert read_zip(path).has_uplugin is False


def test_missing_content_and_config_are_reported(tmp_path):
    path = _zip(
        tmp_path / "Demo.zip",
        {"Demo.uplugin": b"{}", "Source/Demo/Demo.Build.cs": b"// x"},
    )

    facts = read_zip(path)

    assert not facts.has_content
    assert not facts.has_config


def test_an_absent_or_broken_zip_is_none(tmp_path):
    """None is a stable "no product file yet", not an error state."""
    assert read_zip(tmp_path / "nope.zip") is None

    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"definitely not a zip")
    assert read_zip(broken) is None


def test_zip_facts_carry_no_path_and_sort_their_modules(tmp_path):
    path = _zip(
        tmp_path / "Demo.zip",
        {
            "Demo.uplugin": b"{}",
            "Source/Zeta/Zeta.Build.cs": b"x",
            "Source/Alpha/Alpha.Build.cs": b"x",
        },
    )

    data = read_zip(path).as_dict()

    assert data["source_modules"] == ["Alpha", "Zeta"]
    assert str(tmp_path) not in str(data)


def test_digest_changes_when_the_zip_changes(tmp_path):
    first = read_zip(_zip(tmp_path / "a.zip", {"Demo.uplugin": b"{}"}))
    second = read_zip(_zip(tmp_path / "b.zip", {"Demo.uplugin": b'{"x":1}'}))

    assert first.sha256 != second.sha256
