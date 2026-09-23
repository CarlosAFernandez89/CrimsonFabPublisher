"""Image size and digest, from header bytes only.

Pillow would do this in one line but is not a dependency, and adding it means a
new requirement plus a PyInstaller hidden-import risk for two numbers. Reading
the PNG IHDR and scanning for a JPEG SOF marker is about sixty lines and no
install.

Both readers return None for anything they do not recognise rather than
raising, so an odd file degrades to a warning instead of failing a build.
Swapping in Pillow later means replacing this module and nothing else.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

#: JPEG frame markers carrying dimensions. The arithmetic/progressive variants
#: are included; DHT/DAC/RST and friends deliberately are not.
_JPEG_SOF = {
    0xC0, 0xC1, 0xC2, 0xC3,
    0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB,
    0xCD, 0xCE, 0xCF,
}

_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class ImageFacts:
    """What the listing records about one image.

    `width`/`height` are None when the dimensions could not be read - a warning
    for the user, never a hard failure.
    """

    source: str
    bytes: int
    sha256: str
    width: int | None = None
    height: int | None = None

    @property
    def dimensions_known(self) -> bool:
        return self.width is not None and self.height is not None


def sha256_file(path: Path) -> str:
    """Streamed digest, so a large gallery item never lands in memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(_CHUNK):
            digest.update(block)
    return digest.hexdigest()


def _png_size(head: bytes) -> tuple[int, int] | None:
    # IHDR is always the first chunk: 8 bytes magic, 4 length, 4 type, then
    # width and height as big-endian uint32.
    if len(head) < 24 or not head.startswith(_PNG_MAGIC):
        return None
    if head[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", head[16:24])
    return (width, height) if width and height else None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    index = 2
    end = len(data)
    while index + 9 < end:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in _JPEG_SOF:
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return (width, height) if width and height else None
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        segment = struct.unpack(">H", data[index + 2 : index + 4])[0]
        if segment < 2:
            return None
        index += 2 + segment
    return None


def read_dimensions(path: Path) -> tuple[int, int] | None:
    """(width, height) for a PNG or JPEG, or None if it cannot be determined."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".png":
            with path.open("rb") as handle:
                return _png_size(handle.read(24))
        if suffix in (".jpg", ".jpeg"):
            # A SOF marker normally sits well inside the first 64 KB; reading
            # more than that to find one is not worth it for a preview image.
            with path.open("rb") as handle:
                return _jpeg_size(handle.read(64 * 1024))
    except (OSError, struct.error):
        return None
    return None


def read_image(path: Path, source: str) -> ImageFacts | None:
    """Facts for one image, or None when the file is not on disk.

    `source` is the workspace-relative path recorded in the listing - never an
    absolute one, which would make the generated object machine-specific.
    """
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        return None
    dimensions = read_dimensions(path)
    try:
        digest = sha256_file(path)
    except OSError:
        return None
    return ImageFacts(
        source=source,
        bytes=size,
        sha256=digest,
        width=dimensions[0] if dimensions else None,
        height=dimensions[1] if dimensions else None,
    )
