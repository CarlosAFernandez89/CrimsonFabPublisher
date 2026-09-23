"""Stage a listing for Fab: check it, generate the paste-ready bundle, see what
changed since last time, and record what was submitted.

Four operations, three buttons. Diff is not a button: it is the pane Check
fills in. A standalone Diff would hash the same zips for less output, so it
would be Check wearing a different label.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...listing.service import ListingScan
from ..listing_editor import ListingEditor
from ..listing_table_model import ListingTableModel
from ..status_delegate import StatusPillDelegate
from ..theme import icons, mono_font

#: How much of the drafter's output to keep on screen. The full text goes to
#: the Logs page, which is built for volume.
DRAFT_TAIL = 200

SCOPES = ("Selected", "Changed", "All")


class ListingsPage(QWidget):
    check_requested = Signal(str)  # scope
    build_requested = Signal()
    accept_requested = Signal(bool)  # force
    cancel_requested = Signal()
    draft_requested = Signal(str)
    improve_requested = Signal(str, str)
    copy_prompt_requested = Signal(str)
    open_settings_requested = Signal()
    open_bundle_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = ListingTableModel(self)
        self._listings_dir: Path | None = None
        self._draft_lines: list[str] = []
        self._draft_elapsed = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._empty_state())
        self.stack.addWidget(self._browser())
        outer.addWidget(self.stack)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    # -------------------------------------------------------------- empty
    def _empty_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(1)

        title = QLabel("Listings folder unavailable")
        title.setProperty("role", "h2")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        body = QLabel(
            "Listing copy, media and submission snapshots need a folder this "
            "app can write to. The default sits in your Documents; choose "
            "another in Settings if that one cannot be used."
        )
        body.setProperty("role", "caption")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignCenter)
        body.setMaximumWidth(520)
        layout.addWidget(body, 0, Qt.AlignCenter)

        button = QPushButton("Choose a folder in Settings")
        button.setProperty("variant", "primary")
        button.clicked.connect(self.open_settings_requested)
        layout.addWidget(button, 0, Qt.AlignCenter)
        layout.addStretch(2)
        return page

    # ------------------------------------------------------------ browser
    def _browser(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 14, 18, 12)
        layout.setSpacing(10)
        layout.addLayout(self._toolbar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._table())
        self.editor = ListingEditor()
        self.editor.draft_requested.connect(self.draft_requested)
        self.editor.improve_requested.connect(self.improve_requested)
        self.editor.copy_prompt_requested.connect(self.copy_prompt_requested)
        splitter.addWidget(self.editor)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([560, 520])
        layout.addWidget(splitter, 1)

        self.draft_pane = QPlainTextEdit()
        self.draft_pane.setReadOnly(True)
        self.draft_pane.setFont(mono_font(8.5))
        self.draft_pane.setMaximumHeight(120)
        self.draft_pane.hide()
        layout.addWidget(self.draft_pane)

        self.summary = QLabel("")
        self.summary.setProperty("role", "caption")
        layout.addWidget(self.summary)
        return page

    def _toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        row.addWidget(QLabel("Scope"))
        self.scope = QComboBox()
        self.scope.addItems(SCOPES)
        self.scope.setToolTip(
            "Checking hashes every submission zip, which takes minutes across "
            "the whole suite."
        )
        row.addWidget(self.scope)

        self.check_button = QPushButton("Check")
        self.check_button.setIcon(icons.icon("rescan"))
        self.check_button.clicked.connect(
            lambda: self.check_requested.emit(self.scope.currentText())
        )
        row.addWidget(self.check_button)

        # The only action that writes, so the only legitimate crimson here.
        self.build_button = QPushButton("Build bundles")
        self.build_button.setProperty("variant", "primary")
        self.build_button.clicked.connect(self.build_requested)
        row.addWidget(self.build_button)

        self.accept_button = QPushButton("Accept...")
        self.accept_button.clicked.connect(lambda: self.accept_requested.emit(False))
        row.addWidget(self.accept_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setIcon(icons.icon("cancel"))
        self.cancel_button.setProperty("variant", "ghost")
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.cancel_button.hide()
        row.addWidget(self.cancel_button)

        self.elapsed = QLabel("")
        self.elapsed.setProperty("role", "hint")
        row.addWidget(self.elapsed)

        row.addStretch(1)

        self.open_button = QPushButton("Open bundle")
        self.open_button.setProperty("variant", "ghost")
        self.open_button.clicked.connect(self._open_bundle)
        row.addWidget(self.open_button)
        return row

    def _table(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setItemDelegateForColumn(5, StatusPillDelegate(self.table))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, self.model.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.selectionModel().selectionChanged.connect(self._show_selected)
        layout.addWidget(self.table)
        return holder

    # ------------------------------------------------------------- state
    def set_listings_dir(self, path: Path | None) -> None:
        self._listings_dir = path
        configured = path is not None and str(path)
        self.stack.setCurrentIndex(1 if configured else 0)

    def set_scan(self, scan: ListingScan) -> None:
        self.model.set_rows(list(scan.rows))
        self._show_selected()
        publishable = scan.publishable
        blocked = sum(1 for r in publishable if r.blocked)
        review = sum(
            len(r.report.review_changes) + len(r.report.unclassified_changes)
            for r in publishable
        )
        excluded = len(scan.rows) - len(publishable)
        parts = [
            f"{len(publishable)} listing(s)",
            f"{len(publishable) - blocked} ready",
            f"{blocked} blocked",
            f"{review} review-triggering change(s)",
        ]
        if excluded:
            parts.append(f"{excluded} excluded")
        self.summary.setText(" - ".join(parts))

    def selected_rows(self) -> list:
        indexes = self.table.selectionModel().selectedRows()
        rows = [self.model.row_at(i.row()) for i in indexes]
        return [r for r in rows if r is not None]

    def rows_for_scope(self, scope: str) -> list:
        rows = [r for r in self.model.rows() if r.publishable]
        if scope == "Selected":
            chosen = [r for r in self.selected_rows() if r.publishable]
            return chosen or rows
        if scope == "Changed":
            return [r for r in rows if r.report.changes or r.report.status == "new"]
        return rows

    def _show_selected(self, *_args) -> None:
        rows = self.selected_rows()
        self.editor.set_row(rows[0] if rows else None, self._listings_dir)

    def _open_bundle(self) -> None:
        rows = self.selected_rows()
        if rows:
            self.open_bundle_requested.emit(rows[0].plugin_id)

    # -------------------------------------------------------------- busy
    def set_busy(self, busy: bool) -> None:
        for widget in (self.check_button, self.build_button, self.accept_button):
            widget.setEnabled(not busy)
        self.cancel_button.setVisible(busy)
        if busy:
            self._draft_elapsed = 0
            self._timer.start()
        else:
            self._timer.stop()
            self.elapsed.setText("")

    def _tick(self) -> None:
        self._draft_elapsed += 1
        minutes, seconds = divmod(self._draft_elapsed, 60)
        self.elapsed.setText(f"{minutes:02d}:{seconds:02d}")

    # ------------------------------------------------------------- draft
    def begin_draft(self, plugin_id: str) -> None:
        self._draft_lines = []
        self.draft_pane.setPlainText(f"Drafting copy for {plugin_id}...")
        self.draft_pane.show()

    def append_draft_line(self, text: str) -> None:
        self._draft_lines.append(text)
        del self._draft_lines[:-DRAFT_TAIL]
        self.draft_pane.setPlainText("\n".join(self._draft_lines))
        self.draft_pane.verticalScrollBar().setValue(
            self.draft_pane.verticalScrollBar().maximum()
        )

    def end_draft(self, message: str) -> None:
        if message:
            self.append_draft_line(message)
        QTimer.singleShot(4000, self.draft_pane.hide)

    def copy_prompt(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self.draft_pane.setPlainText(
            "Prompt copied. Paste it into a Claude session, then paste the "
            "JSON reply into the Raw JSON tab."
        )
        self.draft_pane.show()
        QTimer.singleShot(6000, self.draft_pane.hide)

    def set_scope(self, scope: str) -> None:
        index = self.scope.findText(scope)
        if index >= 0:
            self.scope.setCurrentIndex(index)
