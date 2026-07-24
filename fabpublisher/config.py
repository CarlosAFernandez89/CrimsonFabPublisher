"""Persisted application configuration and per-user data locations."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "CrimsonFabPublisher"


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def config_path() -> Path:
    return data_dir() / "config.json"


def state_path() -> Path:
    return data_dir() / "state.json"


@dataclass
class Config:
    plugins_root: str = ""
    engine_id: str = ""
    platform_mask: int = 1  # Platform.WIN64 — the first-run default
    selected: list[str] = field(default_factory=list)
    ship_patterns: list[str] = field(default_factory=list)
    output_dir: str = ""
    schema_version: int = 1
    theme: str = "crimson-dark"
    window_geometry: str = ""  # base64 of QMainWindow.saveGeometry()
    auto_open_output: bool = True
    auto_select_changed: bool = False
    #: Engine roots the user registered by hand, for installs the Epic Launcher
    #: never recorded. Merged with automatic detection.
    custom_engine_roots: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        path = config_path()
        if path.is_file():
            try:
                # utf-8-sig: an editor (or PowerShell) may have added a BOM,
                # which plain utf-8 would turn into a silent settings reset.
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                return cfg
            if not isinstance(data, dict):
                return cfg
            for key in asdict(cfg):
                if key in data:
                    setattr(cfg, key, data[key])
        return cfg

    def save(self) -> None:
        """Write atomically so a crash mid-write can't leave a truncated config."""
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, path)
