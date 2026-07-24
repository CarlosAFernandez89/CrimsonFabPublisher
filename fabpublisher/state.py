"""Content-hash state tracking to detect which plugins changed since last build."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import PluginInfo

# Directories that never contribute to a plugin's source identity.
EXCLUDED_DIRS = frozenset(
    {"Binaries", "Intermediate", "Saved", "DerivedDataCache", ".git", "__pycache__"}
)


def hash_plugin_source(plugin_dir: Path) -> str:
    """SHA-256 over a plugin's meaningful source tree.

    Excludes build artifacts (`Binaries`, `Intermediate`, ...) so that a rebuild
    alone never registers as a change. File paths and contents both feed the
    digest, so adds, deletes, renames, and edits are all detected.
    """
    plugin_dir = Path(plugin_dir)
    digest = hashlib.sha256()

    entries: list[tuple[str, Path]] = []
    for path in plugin_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(plugin_dir)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        entries.append((rel.as_posix(), path))

    for rel_str, path in sorted(entries, key=lambda item: item[0]):
        digest.update(rel_str.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\0")

    return digest.hexdigest()


class StateStore:
    """Persisted map of plugin name -> last-built source hash."""

    def __init__(self, state_path: Path):
        self.state_path = Path(state_path)
        self._hashes: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_path.is_file():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
            self._hashes = dict(data.get("hashes", {}))
        except (OSError, ValueError):
            self._hashes = {}

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps({"hashes": self._hashes}, indent=2), encoding="utf-8"
        )

    def stored_hash(self, name: str) -> str | None:
        return self._hashes.get(name)

    def mark_built(self, name: str, digest: str) -> None:
        """Record a plugin's current hash after a successful build."""
        self._hashes[name] = digest

    def clear(self) -> None:
        """Forget every build. Everything then reads as changed."""
        self._hashes.clear()


def compute_changes(
    plugins: list[PluginInfo], store: StateStore
) -> tuple[dict[str, str], set[str]]:
    """Return (current hashes by name, set of names whose hash differs from store).

    A plugin with no stored hash (never built) counts as changed.
    """
    current: dict[str, str] = {}
    changed: set[str] = set()
    for plugin in plugins:
        digest = hash_plugin_source(plugin.path)
        current[plugin.name] = digest
        if store.stored_hash(plugin.name) != digest:
            changed.add(plugin.name)
    return current, changed
