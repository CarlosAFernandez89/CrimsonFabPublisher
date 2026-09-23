"""The listing status table.

Follows `PluginTableModel`: state travels on custom roles and the view decides
the colour, so no colour literal appears here.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ..listing.diffing import CHANGED, CLEAN, NEW, PENDING
from ..listing.service import ListingRow
from .theme import color, mono_font

#: The chip text, so the delegate can render a listing status the same way it
#: renders a PluginStatus without knowing what a listing is.
ChipRole = Qt.UserRole + 20
ChipColorRole = Qt.UserRole + 21
RowRole = Qt.UserRole + 22

BLOCKED = "blocked"
EXCLUDED = "excluded"

COLUMNS = (
    "Listing",
    "Tier",
    "Personal",
    "Professional",
    "Live",
    "Status",
    "Review",
    "Instant",
    "Issues",
    "Zip",
)

#: Columns holding data rather than prose, set in the monospace face.
_MONO = {1, 2, 3, 6, 7, 8}

_TOOLTIPS = (
    "Plugin id, which is also the listing file's name.",
    "free or premium. Drives the default prices.",
    "Personal seat price in US dollars.",
    "Professional seat price in US dollars.",
    "A dot means the listing already exists on Fab - update it, never "
    "create a second one.",
    "NEW: never submitted. PENDING: recorded but not live. changed / clean "
    "against the last accepted snapshot. BLOCKED: errors must be fixed first.",
    "Changes that send the listing back through Fab review.",
    "Changes Fab applies instantly.",
    "Errors and warnings from the listing check.",
    "Whether a submission zip was found in the output folder.",
)


def status_word(row: ListingRow) -> str:
    if not row.publishable:
        return EXCLUDED
    if row.blocked:
        return BLOCKED
    return {NEW: "NEW", PENDING: "PENDING", CLEAN: "clean", CHANGED: "changed"}.get(
        row.report.status, row.report.status
    )


def status_token(word: str) -> str:
    return {
        "NEW": "info",
        "PENDING": "neutral",
        "clean": "success",
        "changed": "warning",
        BLOCKED: "danger",
        EXCLUDED: "neutral",
    }.get(word, "neutral")


class ListingTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[ListingRow] = []
        self._mono = mono_font()

    # ------------------------------------------------------------------ data
    def set_rows(self, rows: list[ListingRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rows(self) -> list[ListingRow]:
        return list(self._rows)

    def row_at(self, index: int) -> ListingRow | None:
        return self._rows[index] if 0 <= index < len(self._rows) else None

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return COLUMNS[section]
        if role == Qt.ToolTipRole:
            return _TOOLTIPS[section]
        return None

    def _display(self, row: ListingRow, column: int) -> str:
        listing = row.listing or {}
        license_ = listing.get("license") or {}
        report = row.report
        review = len(report.review_changes) + len(report.unclassified_changes)

        if column == 0:
            return row.plugin_id
        if column == 1:
            return row.tier
        if column == 2:
            return f"{license_.get('price_personal', 0):.2f}"
        if column == 3:
            return f"{license_.get('price_professional', 0):.2f}"
        if column == 4:
            return "live" if row.plugin.is_live else ""
        if column == 5:
            return ""  # painted as a chip
        if column == 6:
            return str(review) if review else ""
        if column == 7:
            return str(len(report.instant_changes)) if report.instant_changes else ""
        if column == 8:
            errors, warnings = len(row.errors), len(row.warnings)
            if not errors and not warnings:
                return ""
            return f"{errors}E {warnings}W" if errors else f"{warnings}W"
        if column == 9:
            return "yes" if (listing.get("product_file")) else ""
        return ""

    def _tooltip(self, row: ListingRow, column: int) -> str:
        if column == 4 and row.plugin.is_live:
            return (
                f"Already on Fab - update this listing, do not create a new "
                f"one.\n{row.plugin.listing_url}"
            )
        if column == 8 and row.issues:
            return "\n".join(f"{i.level}: {i.message}" for i in row.issues[:6])
        if column == 5 and not row.publishable:
            return "publish is false in this plugin's listing file."
        return _TOOLTIPS[column]

    def _foreground(self, row: ListingRow, column: int):
        from PySide6.QtGui import QColor

        if column == 4 and row.plugin.is_live:
            return QColor(color("accent_text"))
        if column == 6 and (row.report.review_changes or row.report.unclassified_changes):
            token = "danger" if row.report.unclassified_changes else "warning"
            return QColor(color(token))
        if column == 8 and row.errors:
            return QColor(color("danger"))
        if column == 8 and row.warnings:
            return QColor(color("warning"))
        if not row.publishable:
            return QColor(color("text_muted"))
        return QColor(color("text_secondary"))

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = index.column()

        if role == Qt.DisplayRole:
            return self._display(row, column)
        if role == Qt.ToolTipRole:
            return self._tooltip(row, column)
        if role == Qt.FontRole and column in _MONO:
            return self._mono
        if role == Qt.ForegroundRole:
            return self._foreground(row, column)
        if role == Qt.TextAlignmentRole and column in (2, 3, 6, 7):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == ChipRole and column == 5:
            return status_word(row)
        if role == ChipColorRole and column == 5:
            return color(status_token(status_word(row)))
        if role == RowRole:
            return row
        return None
