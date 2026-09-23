"""Authored listing copy and submission snapshots on disk.

The authored file is the source of truth for everything editorial. It is read
BOM-tolerantly and written atomically, matching how `Config` and `StateStore`
already handle their JSON.

The one strict rule here is the typo guard: a key that is not in `ALLOWED` is
an error, never a silent no-op. A misspelled `"tag"` that quietly does nothing
is far worse than one that refuses to load, because it looks like it worked.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

#: Sub-directories of the listings workspace.
SNAPSHOT_DIRNAME = "_snapshots"
DRAFT_DIRNAME = "_drafts"
MEDIA_DIRNAME = "media"
DEFAULTS_FILENAME = "_defaults.json"
STATUS_FILENAME = "STATUS.md"
SESSIONS_FILENAME = "_sessions.json"

#: The authored file's shape. A value of None means "any scalar or list";
#: a set means "a nested object with exactly these keys".
ALLOWED: dict[str, set[str] | None] = {
    "schema": None,
    "publish": None,
    "title": None,
    "tier": None,
    "product_type": None,
    "category": None,
    "tags": None,
    "license": None,
    "price": {"personal", "professional"},
    "description": {"what", "how", "technical"},
    "media": {"thumbnail", "gallery"},
    "technical": {
        "engine_versions",
        "dev_platforms",
        "target_platforms",
        "distribution",
        "include_engine_plugins",
    },
    "declarations": {
        "edc_forum_post",
        "mature",
        "no_ai",
        "generative_ai",
        "promotional",
    },
    "forum_post": {"has", "url"},
    "faq": None,
    "changelog": None,
    "silence": {"missing_content_config", "gallery_thumbnail_only"},
}

#: The only template token, usable only inside `media` strings. Kept to one
#: token in one subtree so it can never grow into a mini-language: any other
#: brace in an authored value is an error.
ID_TOKEN = "{id}"


@dataclass(frozen=True)
class LoadedSource:
    """An authored file as read from disk.

    `error` is non-empty when the file exists but could not be used. The caller
    reports it; nothing here raises.
    """

    data: dict = field(default_factory=dict)
    exists: bool = False
    error: str = ""
    path: Path | None = None


def source_path(listings_dir: Path, plugin_id: str) -> Path:
    return Path(listings_dir) / f"{plugin_id}.json"


def defaults_path(listings_dir: Path) -> Path:
    return Path(listings_dir) / DEFAULTS_FILENAME


def snapshot_path(listings_dir: Path, plugin_id: str) -> Path:
    return Path(listings_dir) / SNAPSHOT_DIRNAME / f"{plugin_id}.json"


def draft_path(listings_dir: Path, plugin_id: str) -> Path:
    return Path(listings_dir) / DRAFT_DIRNAME / f"{plugin_id}.txt"


def media_root(listings_dir: Path) -> Path:
    return Path(listings_dir) / MEDIA_DIRNAME


def unknown_keys(data: dict) -> list[str]:
    """Dotted paths in `data` that the authored schema does not define."""
    unknown: list[str] = []
    for key, value in data.items():
        if key not in ALLOWED:
            unknown.append(key)
            continue
        nested = ALLOWED[key]
        if nested is not None and isinstance(value, dict):
            unknown.extend(
                f"{key}.{sub}" for sub in value if sub not in nested
            )
    return sorted(unknown)


def stray_braces(data: dict) -> list[str]:
    """Paths holding a brace outside the one place templating is allowed."""
    found: list[str] = []

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str) and ("{" in node or "}" in node):
            in_media = path == "media" or path.startswith("media.")
            if not (in_media and node.replace(ID_TOKEN, "").count("{") == 0):
                found.append(path)

    walk(data, "")
    return sorted(found)


def resolve_id_token(value: str, plugin_id: str) -> str:
    return value.replace(ID_TOKEN, plugin_id)


def _read_json(path: Path) -> LoadedSource:
    if not path.is_file():
        return LoadedSource(exists=False, path=path)
    try:
        # utf-8-sig: an editor or PowerShell may have left a BOM, which plain
        # utf-8 would turn into a parse error on the very first key.
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return LoadedSource(exists=True, error=f"Could not read {path.name}: {exc}", path=path)
    try:
        data = json.loads(raw)
    except ValueError as exc:
        return LoadedSource(exists=True, error=f"{path.name} is not valid JSON: {exc}", path=path)
    if not isinstance(data, dict):
        return LoadedSource(
            exists=True, error=f"{path.name} must contain a JSON object", path=path
        )
    return LoadedSource(data=data, exists=True, path=path)


def load_source(listings_dir: Path, plugin_id: str) -> LoadedSource:
    return _read_json(source_path(listings_dir, plugin_id))


def load_defaults(listings_dir: Path) -> LoadedSource:
    return _read_json(defaults_path(listings_dir))


def load_snapshot(listings_dir: Path, plugin_id: str) -> LoadedSource:
    return _read_json(snapshot_path(listings_dir, plugin_id))


def write_json(path: Path, data: dict) -> None:
    """Write atomically, so a crash mid-write cannot truncate authored copy."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


def save_source(listings_dir: Path, plugin_id: str, data: dict) -> Path:
    path = source_path(listings_dir, plugin_id)
    write_json(path, data)
    return path


def save_snapshot(listings_dir: Path, plugin_id: str, data: dict) -> Path:
    path = snapshot_path(listings_dir, plugin_id)
    write_json(path, data)
    return path


def sessions_path(listings_dir: Path) -> Path:
    return Path(listings_dir) / SESSIONS_FILENAME


def load_sessions(listings_dir: Path) -> dict[str, str]:
    """Per-plugin Claude session ids, so a follow-up can resume the same chat.

    A missing or unreadable file just means "no history"; losing a session id
    costs context on the next follow-up, never data.
    """
    loaded = _read_json(sessions_path(listings_dir))
    return {
        str(k): str(v) for k, v in (loaded.data or {}).items() if isinstance(v, str)
    }


def save_sessions(listings_dir: Path, sessions: dict[str, str]) -> None:
    write_json(sessions_path(listings_dir), dict(sorted(sessions.items())))


def authored_ids(listings_dir: Path) -> list[str]:
    """Plugin ids that have an authored file, ignoring the underscore files."""
    root = Path(listings_dir)
    if not root.is_dir():
        return []
    return sorted(
        p.stem for p in root.glob("*.json") if not p.name.startswith("_")
    )
