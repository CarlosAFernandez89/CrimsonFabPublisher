"""Observable settings: the single source of truth the widgets bind to.

`Config` stays the plain on-disk shape. This wraps one and adds typed access
plus change notification, so no widget is ever the model.
"""

from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..config import APP_NAME, Config, data_dir, documents_dir
from ..models import Platform

#: Folder name used when the user has not chosen an output location.
SUBMISSIONS_DIRNAME = "FabSubmissions"

#: Where listing copy goes by default. Under Documents rather than %APPDATA%
#: because this is authored content the user is expected to find, edit and
#: back up - not app state they should never have to look at.
LISTINGS_DIRNAME = "Listings"


def default_output_dir() -> Path:
    """Where zips go when no output folder is set.

    The app's own data folder, not somewhere near the plugins: a folder the app
    invents inside a user's project tree is one they never asked for and cannot
    identify. Here it sits beside the config and state files, namespaced by the
    app, on the system drive.
    """
    return data_dir() / SUBMISSIONS_DIRNAME


def default_listings_dir() -> Path:
    """Where listing copy goes when the user has not chosen a folder.

    Documents, not %APPDATA%: these are files you open, edit and want backed
    up. Keeping them out of the app's own install tree also matters - anyone
    who clones this tool is publishing their own plugins, and their copy must
    never end up in its repository.
    """
    return documents_dir() / APP_NAME / LISTINGS_DIRNAME


def platform_from_mask(value: object) -> Platform:
    """Tolerate a stale or hand-edited mask instead of crashing at startup.

    `Platform` uses strict flag boundaries, so an out-of-range int raises.
    """
    try:
        return Platform(value)
    except (ValueError, TypeError):
        return Platform.NONE


def patterns_from_text(text: str) -> list[str]:
    """Split a ship-pattern editor's contents, dropping blank lines."""
    return [line for line in text.splitlines() if line.strip()]


class AppSettings(QObject):
    plugins_root_changed = Signal(str)
    engine_id_changed = Signal(str)
    platforms_changed = Signal(object)  # Platform
    selection_changed = Signal(object)  # set[str]
    ship_patterns_changed = Signal(list)
    output_dir_changed = Signal(str)
    auto_open_output_changed = Signal(bool)
    auto_select_changed_toggled = Signal(bool)
    custom_engine_roots_changed = Signal(list)
    listings_dir_changed = Signal(str)
    claude_path_changed = Signal(str)

    def __init__(self, config: Config | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self._c = config if config is not None else Config()

    @classmethod
    def load(cls, parent: QObject | None = None) -> "AppSettings":
        return cls(Config.load(), parent)

    def save(self) -> None:
        self._c.save()

    # ------------------------------------------------------------------ paths
    @property
    def plugins_root(self) -> str:
        return self._c.plugins_root

    @plugins_root.setter
    def plugins_root(self, value: str) -> None:
        value = value.strip()
        if value != self._c.plugins_root:
            self._c.plugins_root = value
            self.plugins_root_changed.emit(value)

    @property
    def output_dir(self) -> str:
        return self._c.output_dir

    @output_dir.setter
    def output_dir(self, value: str) -> None:
        value = value.strip()
        if value != self._c.output_dir:
            self._c.output_dir = value
            self.output_dir_changed.emit(value)

    def effective_output_dir(self) -> Path:
        """Where zips land.

        An unset output folder gets a dedicated app-owned folder rather than the
        plugins root — writing zips in among the plugin folders would put build
        products inside a version-controlled source tree.
        """
        if self._c.output_dir:
            return Path(self._c.output_dir)
        return default_output_dir()

    # --------------------------------------------------------------- listings
    @property
    def listings_dir(self) -> str:
        return self._c.listings_dir

    @listings_dir.setter
    def listings_dir(self, value: str) -> None:
        value = value.strip()
        if value != self._c.listings_dir:
            self._c.listings_dir = value
            self.listings_dir_changed.emit(value)

    def effective_listings_dir(self) -> Path:
        """Where authored listing copy lives, chosen or defaulted."""
        if self._c.listings_dir:
            return Path(self._c.listings_dir)
        return default_listings_dir()

    @property
    def claude_path(self) -> str:
        return self._c.claude_path

    @claude_path.setter
    def claude_path(self, value: str) -> None:
        value = value.strip()
        if value != self._c.claude_path:
            self._c.claude_path = value
            self.claude_path_changed.emit(value)

    @property
    def listing_prompt_template(self) -> str:
        return self._c.listing_prompt_template

    @listing_prompt_template.setter
    def listing_prompt_template(self, value: str) -> None:
        self._c.listing_prompt_template = value

    @property
    def listing_faq_review(self) -> bool:
        return self._c.listing_faq_review

    @listing_faq_review.setter
    def listing_faq_review(self, value: bool) -> None:
        self._c.listing_faq_review = bool(value)

    @property
    def listing_changelog_review(self) -> bool:
        return self._c.listing_changelog_review

    @listing_changelog_review.setter
    def listing_changelog_review(self, value: bool) -> None:
        self._c.listing_changelog_review = bool(value)

    # ----------------------------------------------------------------- engine
    @property
    def engine_id(self) -> str:
        return self._c.engine_id

    @engine_id.setter
    def engine_id(self, value: str) -> None:
        value = value or ""
        if value != self._c.engine_id:
            self._c.engine_id = value
            self.engine_id_changed.emit(value)

    @property
    def custom_engine_roots(self) -> list[str]:
        return list(self._c.custom_engine_roots)

    @custom_engine_roots.setter
    def custom_engine_roots(self, value: list[str]) -> None:
        value = [str(v) for v in value if str(v).strip()]
        if value != self._c.custom_engine_roots:
            self._c.custom_engine_roots = value
            self.custom_engine_roots_changed.emit(value)

    def add_engine_root(self, path: str) -> bool:
        """Register a root. False if it is already registered."""
        path = str(path).strip()
        existing = {p.lower() for p in self._c.custom_engine_roots}
        if not path or path.lower() in existing:
            return False
        self.custom_engine_roots = [*self._c.custom_engine_roots, path]
        return True

    def remove_engine_root(self, path: str) -> None:
        self.custom_engine_roots = [
            p for p in self._c.custom_engine_roots if p != path
        ]

    # -------------------------------------------------------------- platforms
    @property
    def platforms(self) -> Platform:
        return platform_from_mask(self._c.platform_mask)

    @platforms.setter
    def platforms(self, value: Platform) -> None:
        if value.value != self._c.platform_mask:
            self._c.platform_mask = value.value
            self.platforms_changed.emit(value)

    # -------------------------------------------------------------- selection
    @property
    def selection(self) -> set[str]:
        return set(self._c.selected)

    @selection.setter
    def selection(self, value: set[str]) -> None:
        if set(value) != set(self._c.selected):
            self._c.selected = sorted(value)
            self.selection_changed.emit(set(value))

    def set_selection_ordered(self, names: list[str]) -> None:
        """Persist the selection in build order, as the table reports it."""
        if set(names) != set(self._c.selected):
            self._c.selected = list(names)
            self.selection_changed.emit(set(names))
        else:
            self._c.selected = list(names)

    # -------------------------------------------------------------- packaging
    @property
    def ship_patterns(self) -> list[str]:
        return list(self._c.ship_patterns)

    @ship_patterns.setter
    def ship_patterns(self, value: list[str]) -> None:
        value = [line for line in value if line.strip()]
        if value != self._c.ship_patterns:
            self._c.ship_patterns = value
            self.ship_patterns_changed.emit(value)

    # --------------------------------------------------------------- defaults
    @property
    def auto_open_output(self) -> bool:
        return bool(self._c.auto_open_output)

    @auto_open_output.setter
    def auto_open_output(self, value: bool) -> None:
        value = bool(value)
        if value != self._c.auto_open_output:
            self._c.auto_open_output = value
            self.auto_open_output_changed.emit(value)

    @property
    def auto_select_changed(self) -> bool:
        return bool(self._c.auto_select_changed)

    @auto_select_changed.setter
    def auto_select_changed(self, value: bool) -> None:
        value = bool(value)
        if value != self._c.auto_select_changed:
            self._c.auto_select_changed = value
            self.auto_select_changed_toggled.emit(value)

    # --------------------------------------------------------------- geometry
    @property
    def window_geometry(self) -> bytes:
        try:
            return base64.b64decode(self._c.window_geometry.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            return b""

    @window_geometry.setter
    def window_geometry(self, value: bytes) -> None:
        self._c.window_geometry = base64.b64encode(bytes(value)).decode("ascii")

    # ------------------------------------------------------------------ theme
    @property
    def theme(self) -> str:
        return self._c.theme
