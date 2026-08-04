"""Qt table model over the discovered plugins.

Owns no colours and no fonts beyond the data/prose split: the view decides how
state looks, the model only says what the state is.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ..models import DependencyKind, PluginInfo, PluginStatus
from .theme import color, mono_font

COLUMNS = [
    "#", "", "Plugin", "Version", "Engine", "Modules", "Deps", "BP", "C++", "Status"
]
(
    COL_ORDER,
    COL_CHECK,
    COL_NAME,
    COL_VERSION,
    COL_ENGINE,
    COL_MODULES,
    COL_DEPS,
    COL_BLUEPRINTS,
    COL_CPP,
    COL_STATUS,
) = range(10)

#: Columns carrying machine truth, set in monospace.
_MONO_COLUMNS = {
    COL_ORDER,
    COL_NAME,
    COL_VERSION,
    COL_ENGINE,
    COL_MODULES,
    COL_DEPS,
    COL_BLUEPRINTS,
    COL_CPP,
}

StatusRole = Qt.UserRole + 1
PluginRole = Qt.UserRole + 2
ReasonRole = Qt.UserRole + 3


def _major_minor(version: str) -> tuple[str, ...]:
    return tuple(version.split(".")[:2]) if version else ()


class PluginTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._plugins: list[PluginInfo] = []
        self._checked: set[str] = set()
        self._reasons: dict[str, str] = {}
        self._impact: dict[str, str] = {}
        self._engine_version = ""
        self._mono = mono_font()

    # ---- data population -------------------------------------------------
    def set_plugins(self, plugins: list[PluginInfo]) -> None:
        self.beginResetModel()
        self._plugins = plugins
        names = {p.name for p in plugins}
        self._checked &= names
        # Every status here is freshly computed by the scan, so any build-time
        # reason held over would explain a state that no longer exists.
        self._reasons.clear()
        self.endResetModel()

    def set_impact(self, impact: dict[str, str]) -> None:
        """What the last scan says needs rebuilding, and why."""
        self._impact = dict(impact)

    def set_engine_version(self, version: str) -> None:
        self._engine_version = version or ""

    def plugins(self) -> list[PluginInfo]:
        return self._plugins

    def rebuild_names(self) -> set[str]:
        """Changed plus dependency-impacted, intersected with what exists.

        Driven by the scan impact rather than status, because a plugin with an
        external dependency reports MISSING_DEP yet may still be changed.
        """
        return set(self._impact) & {p.name for p in self._plugins}

    def set_status(self, name: str, status: PluginStatus, reason: str = "") -> None:
        for row, plugin in enumerate(self._plugins):
            if plugin.name == name:
                plugin.status = status
                # The reason belongs to the status it arrived with: a later
                # status carrying none must not inherit the old explanation,
                # or a fixed plugin keeps reading "(Build failed ...)".
                if reason:
                    self._reasons[name] = reason
                else:
                    self._reasons.pop(name, None)
                left = self.index(row, 0)
                right = self.index(row, COL_STATUS)
                self.dataChanged.emit(left, right)
                return

    def checked_names(self) -> list[str]:
        ordered = sorted(self._plugins, key=lambda p: p.order)
        return [p.name for p in ordered if p.name in self._checked]

    def set_checked(self, names: set[str]) -> None:
        new = set(names) & {p.name for p in self._plugins}
        if new == self._checked:
            return
        self._checked = new
        if self._plugins:
            self.dataChanged.emit(
                self.index(0, COL_CHECK),
                self.index(len(self._plugins) - 1, COL_CHECK),
                [Qt.CheckStateRole],
            )

    # ---- Qt model interface ---------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._plugins)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == COL_CHECK:
            base |= Qt.ItemIsUserCheckable
        return base

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        plugin = self._plugins[index.row()]
        col = index.column()

        if role == Qt.CheckStateRole and col == COL_CHECK:
            return Qt.Checked if plugin.name in self._checked else Qt.Unchecked

        if role == Qt.DisplayRole:
            return self._display(plugin, col)

        if role == Qt.FontRole and col in _MONO_COLUMNS:
            return self._mono

        if role == Qt.TextAlignmentRole and col in (
            COL_ORDER,
            COL_MODULES,
            COL_BLUEPRINTS,
            COL_CPP,
        ):
            return int(Qt.AlignRight | Qt.AlignVCenter)

        if role == Qt.ForegroundRole:
            return self._foreground(plugin, col)

        if role == Qt.ToolTipRole:
            return self._tooltip(plugin, col)

        if role == StatusRole:
            return plugin.status
        if role == PluginRole:
            return plugin
        if role == ReasonRole:
            return self._reasons.get(plugin.name, "")
        return None

    # ---- per-column rendering -------------------------------------------
    def _display(self, plugin: PluginInfo, col: int):
        if col == COL_ORDER:
            return f"{plugin.order:02d}"
        if col == COL_NAME:
            return plugin.name
        if col == COL_VERSION:
            return plugin.version_name or "—"
        if col == COL_ENGINE:
            return plugin.engine_version or "—"
        if col == COL_MODULES:
            return str(len(plugin.modules))
        if col == COL_DEPS:
            return self._deps_text(plugin)
        if col == COL_BLUEPRINTS:
            return str(plugin.blueprint_count)
        if col == COL_CPP:
            return str(plugin.cpp_class_count)
        return None

    def _deps_text(self, plugin: PluginInfo) -> str:
        suite = sum(1 for d in plugin.dependencies if d.kind is DependencyKind.SUITE)
        external = sum(
            1 for d in plugin.dependencies if d.kind is DependencyKind.EXTERNAL
        )
        if not plugin.dependencies:
            return "—"
        text = str(suite)
        if external:
            text += f" · {external}!"
        return text

    def _foreground(self, plugin: PluginInfo, col: int):
        from PySide6.QtGui import QColor

        if col == COL_ORDER:
            return QColor(color("text_muted"))
        if col == COL_ENGINE and self._mismatched(plugin):
            return QColor(color("warning"))
        if col == COL_DEPS and any(
            d.kind is DependencyKind.EXTERNAL for d in plugin.dependencies
        ):
            return QColor(color("danger"))
        if col in (COL_VERSION, COL_MODULES, COL_BLUEPRINTS, COL_CPP):
            return QColor(color("text_secondary"))
        return None

    def _mismatched(self, plugin: PluginInfo) -> bool:
        return bool(
            self._engine_version
            and plugin.engine_version
            and _major_minor(plugin.engine_version) != _major_minor(self._engine_version)
        )

    def _tooltip(self, plugin: PluginInfo, col: int):
        if col == COL_NAME:
            return f"{plugin.friendly_name or plugin.name}\n{plugin.path}"
        if col == COL_ENGINE and self._mismatched(plugin):
            return (
                f"Targets EngineVersion {plugin.engine_version}, "
                f"building against {self._engine_version}"
            )
        if col == COL_MODULES and plugin.modules:
            return "\n".join(
                f"{m.name} · {m.type} · {m.loading_phase}" for m in plugin.modules
            )
        if col == COL_DEPS and plugin.dependencies:
            return "\n".join(
                f"{d.name} · {d.kind.value}" for d in plugin.dependencies
            )
        if col == COL_BLUEPRINTS:
            return (
                f"Blueprints: {plugin.blueprint_count}\n"
                "Blueprint assets under Content/ (levels excluded).\n"
                "Paste into the Fab 'Blueprints' field."
            )
        if col == COL_CPP:
            return (
                f"C++ classes: {plugin.cpp_class_count}\n"
                "Classes and structs defined in Source/ headers,\n"
                "reflected or not (Source/ThirdParty excluded).\n"
                "Paste into the Fab 'C++ classes' field."
            )
        if col == COL_STATUS:
            reason = self._reasons.get(plugin.name)
            impact = self._impact.get(plugin.name)
            bits = [plugin.status.value]
            if impact:
                bits.append(f"rebuild reason: {impact}")
            if reason:
                bits.append(reason)
            return "\n".join(bits)
        return None

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:
        if role == Qt.CheckStateRole and index.column() == COL_CHECK:
            plugin = self._plugins[index.row()]
            if Qt.CheckState(value) == Qt.Checked:
                self._checked.add(plugin.name)
            else:
                self._checked.discard(plugin.name)
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False
