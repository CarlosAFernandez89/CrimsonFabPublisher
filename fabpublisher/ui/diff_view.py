"""What changed since the last submission, grouped by what it costs.

A tree rather than a block of text: the review/instant split becomes structural
instead of a heading you have to read, and each row can be copied on its own.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from ..listing.diffing import CLEAN, NEW, PENDING, DiffReport
from .theme import color, mono_font


class DiffView(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderLabels(["Field", "Change"])
        self.setRootIsDecorated(True)
        self.setAlternatingRowColors(False)
        self.setUniformRowHeights(False)
        self.header().setStretchLastSection(True)
        self.setColumnWidth(0, 220)
        self._mono = mono_font()

    def _group(self, title: str, token: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self, [title, ""])
        item.setForeground(0, QBrush(QColor(color(token))))
        item.setExpanded(True)
        return item

    def _add(self, parent: QTreeWidgetItem, change) -> None:
        row = QTreeWidgetItem(parent, [change.path, change.summary])
        row.setFont(0, self._mono)
        row.setFont(1, self._mono)
        row.setToolTip(0, f"{change.path} ({change.compare})")
        for line in change.detail:
            detail = QTreeWidgetItem(row, ["", line])
            detail.setFont(1, self._mono)
            detail.setForeground(1, QBrush(QColor(color("text_muted"))))
        row.setExpanded(True)

    def show_report(self, report: DiffReport | None) -> None:
        self.clear()
        if report is None:
            return

        if report.status == NEW:
            QTreeWidgetItem(self, ["never submitted", "every field is new"])
            return
        if report.status == PENDING and not report.changes:
            QTreeWidgetItem(
                self, ["pending", "snapshot recorded, listing not live yet"]
            )
            return
        if report.status == CLEAN or not report.changes:
            item = QTreeWidgetItem(self, ["clean", "nothing has moved since accept"])
            item.setForeground(0, QBrush(QColor(color("success"))))
            return

        review = report.review_changes
        instant = report.instant_changes
        unclassified = report.unclassified_changes

        if review:
            group = self._group(f"Needs Fab review ({len(review)})", "warning")
            for change in review:
                self._add(group, change)
        if unclassified:
            # No spec classified these, so review was assumed. Shown apart so
            # the table gets updated rather than the guess being trusted.
            group = self._group(
                f"Unclassified - treated as review ({len(unclassified)})", "danger"
            )
            for change in unclassified:
                self._add(group, change)
        if instant:
            group = self._group(f"Instant, no review ({len(instant)})", "info")
            for change in instant:
                self._add(group, change)


class IssueList(QTreeWidget):
    """Errors and warnings, each naming the key that fixes it.

    Every row is copyable, because the point of a finding is to be taken
    somewhere else and fixed - a message you can only read is a message you
    retype.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderLabels(["Field", "Problem"])
        self.setRootIsDecorated(False)
        self.header().setStretchLastSection(True)
        self.setColumnWidth(0, 220)
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self._mono = mono_font()

        copy_selected = QAction("Copy", self)
        copy_selected.setShortcut(QKeySequence.Copy)
        copy_selected.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        copy_selected.triggered.connect(self.copy_selected)
        copy_all = QAction("Copy all", self)
        copy_all.triggered.connect(self.copy_all)
        self.addActions([copy_selected, copy_all])
        self.setContextMenuPolicy(Qt.ActionsContextMenu)

    # ------------------------------------------------------------------ copy
    def _line(self, item: QTreeWidgetItem) -> str:
        level = item.data(0, Qt.UserRole) or ""
        key = item.text(0)
        prefix = f"{level.upper()} " if level else ""
        return f"{prefix}[{key}] {item.text(1)}" if key and key != "-" else (
            f"{prefix}{item.text(1)}"
        )

    def _all_items(self) -> list[QTreeWidgetItem]:
        """Findings only. The empty-state row is a message, not something to copy."""
        items = (self.topLevelItem(i) for i in range(self.topLevelItemCount()))
        return [i for i in items if i is not None and i.data(0, Qt.UserRole)]

    def copy_selected(self) -> str:
        items = [i for i in self.selectedItems() if i.data(0, Qt.UserRole)]
        return self._copy(items or self._all_items())

    def copy_all(self) -> str:
        return self._copy(self._all_items())

    def _copy(self, items: list[QTreeWidgetItem]) -> str:
        text = "\n".join(self._line(i) for i in items if i is not None)
        if text:
            QGuiApplication.clipboard().setText(text)
        return text

    def show_issues(self, issues, empty_text: str = "Nothing to fix.") -> None:
        self.clear()
        if not issues:
            item = QTreeWidgetItem(self, ["", empty_text])
            item.setForeground(1, QBrush(QColor(color("success"))))
            return
        for issue in issues:
            row = QTreeWidgetItem(self, [issue.key or "-", issue.message])
            row.setFont(0, self._mono)
            token = "danger" if issue.level == "error" else "warning"
            row.setForeground(0, QBrush(QColor(color(token))))
            row.setToolTip(1, issue.message)
            row.setData(0, Qt.UserRole, issue.level)
