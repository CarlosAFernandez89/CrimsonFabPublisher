"""Logs page.

The frozen exe is windowed, so this panel and its export are the only
diagnostic channel a user has.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...config import data_dir
from ..log_model import LogLevel, LogModel
from ..theme import log_record_html, mono_font

LEVELS = [
    ("All", LogLevel.DEBUG),
    ("Info and above", LogLevel.INFO),
    ("Warnings and above", LogLevel.WARNING),
    ("Errors only", LogLevel.ERROR),
]


class LogsPage(QWidget):
    cleared = Signal()

    def __init__(self, logs: LogModel, parent=None):
        super().__init__(parent)
        self.logs = logs

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 12)
        layout.setSpacing(10)
        layout.addLayout(self._toolbar())

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(mono_font())
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.view.setPlaceholderText("Build output appears here.")
        layout.addWidget(self.view, 1)

        self.counts = QLabel("")
        self.counts.setProperty("role", "caption")
        layout.addWidget(self.counts)

        logs.rowsInserted.connect(self._on_rows_inserted)
        logs.modelReset.connect(self._rerender)
        logs.sources_changed.connect(self._refresh_sources)

    # --------------------------------------------------------------- toolbar
    def _toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)

        self.level_combo = QComboBox()
        for label, level in LEVELS:
            self.level_combo.addItem(label, level)
        self.level_combo.currentIndexChanged.connect(self._rerender)
        row.addWidget(self.level_combo)

        self.source_combo = QComboBox()
        self.source_combo.addItem("All plugins", None)
        self.source_combo.currentIndexChanged.connect(self._rerender)
        row.addWidget(self.source_combo)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Find… (Enter for next)")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(230)
        self.search.returnPressed.connect(self._find_next)
        row.addWidget(self.search)

        row.addStretch(1)

        self.follow = QCheckBox("Follow tail")
        self.follow.setChecked(True)
        row.addWidget(self.follow)

        for label, handler in (
            ("Copy", self._copy),
            ("Save as…", self._save),
            ("Clear", self._clear),
            ("Data folder", self._open_data_folder),
        ):
            button = QPushButton(label)
            button.setProperty("variant", "ghost")
            button.clicked.connect(handler)
            row.addWidget(button)
        return row

    # -------------------------------------------------------------- filtering
    def _min_level(self) -> LogLevel:
        return self.level_combo.currentData() or LogLevel.DEBUG

    def _source(self) -> str | None:
        return self.source_combo.currentData()

    def _passes(self, record) -> bool:
        source = self._source()
        return record.level >= self._min_level() and (
            source is None or record.source == source
        )

    def _on_rows_inserted(self, _parent, first: int, last: int) -> None:
        records = self.logs.records()
        chunk = [
            log_record_html(r)
            for r in records[first : last + 1]
            if self._passes(r)
        ]
        if not chunk:
            self._refresh_counts()
            return
        at_bottom = self.follow.isChecked()
        self.view.appendHtml("<br>".join(chunk))
        if at_bottom:
            self.view.moveCursor(QTextCursor.End)
        self._refresh_counts()

    def _rerender(self) -> None:
        """Filters changed — rebuild the whole view once from the model."""
        self.view.clear()
        html = [log_record_html(r) for r in self.logs.records() if self._passes(r)]
        if html:
            self.view.appendHtml("<br>".join(html))
            self.view.moveCursor(QTextCursor.End)
        self._refresh_counts()

    def _refresh_sources(self) -> None:
        current = self.source_combo.currentData()
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem("All plugins", None)
        for name in self.logs.sources():
            self.source_combo.addItem(name, name)
        index = self.source_combo.findData(current)
        self.source_combo.setCurrentIndex(max(index, 0))
        self.source_combo.blockSignals(False)

    def _refresh_counts(self) -> None:
        records = self.logs.records()
        errors = sum(1 for r in records if r.level >= LogLevel.ERROR)
        warnings = sum(1 for r in records if r.level == LogLevel.WARNING)
        self.counts.setText(
            f"{len(records)} lines · {warnings} warnings · {errors} errors"
        )

    def show_errors(self) -> None:
        """Jump straight to the errors — used by the strip and the nav badge."""
        index = self.level_combo.findData(LogLevel.ERROR)
        if index >= 0:
            self.level_combo.setCurrentIndex(index)

    # ---------------------------------------------------------------- actions
    def _find_next(self) -> None:
        text = self.search.text()
        if not text:
            return
        if not self.view.find(text):
            self.view.moveCursor(QTextCursor.Start)
            self.view.find(text, QTextDocument.FindFlag(0))

    def _copy(self) -> None:
        self.view.selectAll()
        self.view.copy()
        cursor = self.view.textCursor()
        cursor.clearSelection()
        self.view.setTextCursor(cursor)

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save log", "crimsonfabpublisher.log", "Log files (*.log *.txt)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.logs.to_text(self._min_level(), self._source()))
        except OSError as exc:
            QMessageBox.warning(self, "Could not save log", str(exc))

    def _clear(self) -> None:
        self.logs.clear()
        self.cleared.emit()

    def _open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))
