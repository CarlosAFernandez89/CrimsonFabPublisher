"""Identity and contents of the submission zip this app already builds.

The listing records the zip by digest rather than by path, so that a rebuilt
product file shows up as a change without the generated object ever containing
a machine-specific path.
"""

from __future__ import annotations

import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from ..builder import submission_zip_name
from ..models import EngineInfo, PluginInfo
from .imagefacts import sha256_file


@dataclass(frozen=True)
class ZipFacts:
    name: str
    bytes: int
    unzipped_bytes: int
    sha256: str
    has_uplugin: bool
    has_source_build_cs: bool
    has_content: bool
    has_config: bool
    source_modules: tuple[str, ...]

    def as_dict(self) -> dict:
        data = asdict(self)
        # Sorted, so module discovery order can never fake a diff.
        data["source_modules"] = sorted(self.source_modules)
        return data


def zip_path_for(output_dir: Path, plugin: PluginInfo, engine: EngineInfo) -> Path:
    """Where a successful build would have left this plugin's zip."""
    return Path(output_dir) / submission_zip_name(plugin, engine)


def read_zip(path: Path) -> ZipFacts | None:
    """Facts for a submission zip, or None if it is absent or unreadable.

    Returning None keeps the generated listing deterministic: "no product file
    yet" is a stable value, not an error state.
    """
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except (OSError, zipfile.BadZipFile):
        return None

    names = [info.filename.replace("\\", "/") for info in infos]
    modules = {
        parts[1]
        for name in names
        if name.endswith(".Build.cs") and len(parts := name.split("/")) > 2
    }

    def has_dir(folder: str) -> bool:
        return any(name.startswith(f"{folder}/") for name in names)

    try:
        size = path.stat().st_size
    except OSError:
        return None

    return ZipFacts(
        name=path.name,
        bytes=size,
        unzipped_bytes=sum(info.file_size for info in infos),
        sha256=sha256_file(path),
        # Fab requires the .uplugin at the archive root, not nested.
        has_uplugin=any(
            name.endswith(".uplugin") and "/" not in name for name in names
        ),
        has_source_build_cs=any(name.endswith(".Build.cs") for name in names),
        has_content=has_dir("Content"),
        has_config=has_dir("Config"),
        source_modules=tuple(sorted(modules)),
    )
