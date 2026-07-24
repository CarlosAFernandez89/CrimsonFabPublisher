"""Plugins page: what exists, what changed, what is selected to build."""

from __future__ import annotations

from PySide6.QtCore import QSortFilterProxyModel, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...models import DependencyKind, PluginInfo, PluginStatus
from ..app_settings import AppSettings
from ..plugin_table_model import (
    COL_CHECK,
    COL_ORDER,
    COL_STATUS,
    PluginRole,
    PluginTableModel,
)
from ..status_delegate import StatusPillDelegate
from ..theme import color, icons, mono_font, status_color

FILTERS = [
    ("All", None),
    ("Changed", PluginStatus.CHANGED),
    ("Needs resubmit", PluginStatus.NEEDS_RESUBMIT),
    ("Missing dep", PluginStatus.MISSING_DEP),
    ("Up to date", PluginStatus.UP_TO_DATE),
]


class _FilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ""
        self.status: PluginStatus | None = None

    def filterAcceptsRow(self, row, parent):
        index = self.sourceModel().index(row, 0, parent)
        plugin = self.sourceModel().data(index, PluginRole)
        if plugin is None:
            return True
        if self.status is not None and plugin.status is not self.status:
            return False
        if self.text and self.text.lower() not in plugin.name.lower():
            return False
        return True


class PluginsPage(QWidget):
    rescan_requested = Signal()
    choose_folder_requested = Signal()
    selection_changed = Signal()
    open_settings_requested = Signal()

    def __init__(self, settings: AppSettings, model: PluginTableModel, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.model = model

        self.proxy = _FilterProxy(self)
        self.proxy.setSourceModel(model)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(12)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._empty_state())
        self.stack.addWidget(self._browser())
        root.addWidget(self.stack, 1)

        model.modelReset.connect(self._refresh)
        model.dataChanged.connect(lambda *_: self._refresh_footer())
        self._refresh()

    # ------------------------------------------------------------ empty state
    def _empty_state(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(460)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(28, 26, 28, 26)
        inner.setSpacing(10)

        title = QLabel("No plugins folder set")
        title.setProperty("role", "h2")
        blurb = QLabel(
            "Choose the folder that holds your plugin directories — the one "
            "containing <Name>/<Name>.uplugin."
        )
        blurb.setWordWrap(True)
        blurb.setProperty("role", "caption")

        choose = QPushButton("Choose folder…")
        choose.setProperty("variant", "primary")
        choose.clicked.connect(self.choose_folder_requested)

        inner.addWidget(title)
        inner.addWidget(blurb)
        inner.addSpacing(6)
        inner.addWidget(choose, 0, Qt.AlignLeft)
        layout.addWidget(card, 0, Qt.AlignCenter)
        return holder

    # ---------------------------------------------------------------- browser
    def _browser(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addLayout(self._header())
        layout.addLayout(self._toolbar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._table())
        splitter.addWidget(self._details())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([680, 320])
        splitter.setCollapsible(1, True)
        layout.addWidget(splitter, 1)

        self.footer = QLabel("")
        self.footer.setProperty("role", "caption")
        layout.addWidget(self.footer)
        return holder

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self.path_label = QLabel("")
        self.path_label.setProperty("role", "caption")
        self.path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.path_label.setCursor(Qt.PointingHandCursor)
        self.path_label.mousePressEvent = lambda _e: self.open_settings_requested.emit()
        row.addWidget(self.path_label, 1)

        self.engine_chip = QLabel("")
        self.engine_chip.setFont(mono_font(8.5))
        self.engine_chip.setProperty("role", "caption")
        row.addWidget(self.engine_chip)

        rescan = QPushButton("Rescan")
        rescan.setIcon(icons.icon("rescan"))
        rescan.clicked.connect(self.rescan_requested)
        row.addWidget(rescan)
        return row

    def _toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)

        for label, handler in (
            ("All", self.select_all),
            ("None", self.select_none),
            ("Changed", self.select_changed),
            ("Invert", self.select_invert),
        ):
            button = QPushButton(label)
            button.setProperty("variant", "ghost")
            button.clicked.connect(handler)
            row.addWidget(button)

        row.addSpacing(12)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(240)
        self.search.textChanged.connect(self._set_text_filter)
        row.addWidget(self.search)

        self.status_filter = QComboBox()
        for label, status in FILTERS:
            self.status_filter.addItem(label, status)
        self.status_filter.currentIndexChanged.connect(self._set_status_filter)
        row.addWidget(self.status_filter)

        row.addStretch(1)
        return row

    def _table(self) -> QWidget:
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setItemDelegateForColumn(COL_STATUS, StatusPillDelegate(self.table))
        self.table.setWordWrap(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Fixed)  # checkbox
        header.setSectionResizeMode(2, QHeaderView.Stretch)  # name
        header.setHighlightSections(False)
        self.table.setColumnWidth(COL_CHECK, 34)
        self.table.setColumnWidth(COL_ORDER, 40)

        # Space toggles every selected row, so a range select is one keystroke.
        toggle = QShortcut(QKeySequence(Qt.Key_Space), self.table)
        toggle.setContext(Qt.WidgetShortcut)
        toggle.activated.connect(self._toggle_selected)

        self.table.selectionModel().selectionChanged.connect(self._show_details)
        return self.table

    # ---------------------------------------------------------------- details
    def _details(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("card")
        panel.setMinimumWidth(240)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        self.detail_name = QLabel("Select a plugin")
        self.detail_name.setProperty("role", "h2")
        layout.addWidget(self.detail_name)

        self.detail_body = QLabel("")
        self.detail_body.setWordWrap(True)
        self.detail_body.setTextFormat(Qt.RichText)
        self.detail_body.setAlignment(Qt.AlignTop)
        self.detail_body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout.addWidget(self.detail_body, 1)

        self.open_folder_btn = QPushButton("Open folder")
        self.open_folder_btn.setProperty("variant", "ghost")
        self.open_folder_btn.clicked.connect(self._open_plugin_folder)
        self.open_folder_btn.setEnabled(False)
        layout.addWidget(self.open_folder_btn, 0, Qt.AlignLeft)

        self._detail_plugin: PluginInfo | None = None
        return panel

    def _selected_plugin(self) -> PluginInfo | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.proxy.data(rows[0], PluginRole)

    def _show_details(self, *_args) -> None:
        plugin = self._selected_plugin()
        self._detail_plugin = plugin
        self.open_folder_btn.setEnabled(plugin is not None)
        if plugin is None:
            self.detail_name.setText("Select a plugin")
            self.detail_body.setText("")
            return

        self.detail_name.setText(plugin.friendly_name or plugin.name)
        muted = color("text_muted")
        secondary = color("text_secondary")

        def row(label: str, value: str) -> str:
            return (
                f'<tr><td style="color:{muted};padding-right:10px;">{label}</td>'
                f'<td style="color:{secondary};">{value}</td></tr>'
            )

        facts = [
            row("Name", plugin.name),
            row("Version", plugin.version_name or "—"),
            row("Engine", plugin.engine_version or "—"),
            row("Content", "Yes" if plugin.can_contain_content else "No"),
            row("Build order", str(plugin.order)),
        ]
        html = f'<table cellspacing="0">{"".join(facts)}</table>'

        if plugin.modules:
            items = "".join(
                f'<div style="color:{secondary};">{m.name} '
                f'<span style="color:{muted};">· {m.type} · {m.loading_phase}</span></div>'
                for m in plugin.modules
            )
            html += f'<p style="color:{muted};">MODULES</p>{items}'

        if plugin.dependencies:
            kind_color = {
                DependencyKind.SUITE: color("info"),
                DependencyKind.ENGINE: color("neutral"),
                DependencyKind.EXTERNAL: color("danger"),
            }
            items = "".join(
                f'<div style="color:{secondary};">{d.name} '
                f'<span style="color:{kind_color[d.kind]};">· {d.kind.value}</span></div>'
                for d in plugin.dependencies
            )
            html += f'<p style="color:{muted};">DEPENDENCIES</p>{items}'

        html += (
            f'<p style="color:{muted};">STATUS</p>'
            f'<div style="color:{status_color(plugin.status)};">{plugin.status.value}</div>'
        )
        self.detail_body.setText(html)

    def _open_plugin_folder(self) -> None:
        if self._detail_plugin is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._detail_plugin.path)))

    # --------------------------------------------------------------- filtering
    def _set_text_filter(self, text: str) -> None:
        self.proxy.text = text
        self.proxy.invalidate()
        self._refresh_footer()

    def _set_status_filter(self, index: int) -> None:
        self.proxy.status = self.status_filter.itemData(index)
        self.proxy.invalidate()
        self._refresh_footer()

    # --------------------------------------------------------------- selection
    def _visible_names(self) -> set[str]:
        names = set()
        for row in range(self.proxy.rowCount()):
            plugin = self.proxy.data(self.proxy.index(row, 0), PluginRole)
            if plugin is not None:
                names.add(plugin.name)
        return names

    def select_all(self) -> None:
        self.model.set_checked(set(self.model.checked_names()) | self._visible_names())
        self.selection_changed.emit()

    def select_none(self) -> None:
        self.model.set_checked(set(self.model.checked_names()) - self._visible_names())
        self.selection_changed.emit()

    def select_invert(self) -> None:
        checked = set(self.model.checked_names())
        visible = self._visible_names()
        self.model.set_checked((checked - visible) | (visible - checked))
        self.selection_changed.emit()

    def select_changed(self) -> None:
        """Everything the last scan says needs rebuilding."""
        self.model.set_checked(set(self.model.rebuild_names()))
        self.selection_changed.emit()

    def _toggle_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        names = {self.proxy.data(r, PluginRole).name for r in rows}
        checked = set(self.model.checked_names())
        # If any selected row is unchecked, check them all; otherwise clear them.
        self.model.set_checked(
            checked | names if names - checked else checked - names
        )
        self.selection_changed.emit()

    # ------------------------------------------------------------------ state
    def set_context(self, root: str, engine_label: str) -> None:
        self.path_label.setText(root or "")
        self.path_label.setToolTip(f"{root}\nClick to change in Settings")
        self.engine_chip.setText(engine_label)
        self.stack.setCurrentIndex(1 if root else 0)

    def _refresh(self) -> None:
        self.proxy.invalidate()
        self._show_details()
        self._refresh_footer()

    def _refresh_footer(self) -> None:
        plugins = self.model.plugins()
        checked = len(self.model.checked_names())
        rebuild = len(self.model.rebuild_names())
        shown = self.proxy.rowCount()
        hidden = f" · {len(plugins) - shown} hidden by filter" if shown != len(plugins) else ""
        self.footer.setText(
            f"{len(plugins)} plugins · {checked} selected · {rebuild} need rebuild{hidden}"
        )
