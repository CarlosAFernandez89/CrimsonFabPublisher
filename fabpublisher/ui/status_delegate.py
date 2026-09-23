"""Status rendered as a squared chip.

Status is the most-scanned cell in the app and tinted 9pt text on a near-black
background is the weakest signal available. A filled chip reads at a glance; the
15%-alpha tint means the label keeps the full-strength colour, so no per-status
contrast check is needed.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QStyledItemDelegate

from ..models import PluginStatus
from .listing_table_model import ChipColorRole, ChipRole
from .plugin_table_model import ReasonRole, StatusRole
from .theme import mono_font, status_color

PAD_X = 7
PAD_Y = 3
RADIUS = 2
TINT_ALPHA = 38  # ~15%


class StatusPillDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._font = mono_font(8.5)

    def _text(self, index) -> str:
        status = index.data(StatusRole)
        if not isinstance(status, PluginStatus):
            return str(index.data(ChipRole) or "")
        reason = index.data(ReasonRole) or ""
        label = status.value
        return f"{label} ({reason})" if reason and reason != label else label

    def _accent(self, index) -> str | None:
        """The chip colour, from either kind of status.

        The PluginStatus branch stays first so the Plugins table renders
        exactly as it did; anything else falls back to a plain chip role, which
        is how the listing table reuses this delegate rather than cloning it.
        """
        status = index.data(StatusRole)
        if isinstance(status, PluginStatus):
            return status_color(status)
        if index.data(ChipRole):
            return index.data(ChipColorRole)
        return None

    def paint(self, painter: QPainter, option, index) -> None:
        accent_hex = self._accent(index)
        if accent_hex is None:
            super().paint(painter, option, index)
            return

        self.initStyleOption(option, index)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        if option.state & option.state.__class__.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        accent = QColor(accent_hex)
        tint = QColor(accent)
        tint.setAlpha(TINT_ALPHA)

        painter.setFont(self._font)
        metrics = QFontMetrics(self._font)
        text = self._text(index)
        available = option.rect.width() - 2 * PAD_X - 6
        text = metrics.elidedText(text, Qt.ElideRight, max(available, 24))

        width = metrics.horizontalAdvance(text) + 2 * PAD_X
        height = metrics.height() + 2 * PAD_Y
        chip = QRectF(
            option.rect.left() + 4,
            option.rect.center().y() - height / 2 + 1,
            width,
            height,
        )

        painter.setPen(accent)
        painter.setBrush(tint)
        painter.drawRoundedRect(chip, RADIUS, RADIUS)
        painter.drawText(chip, Qt.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        metrics = QFontMetrics(self._font)
        return QSize(
            metrics.horizontalAdvance(self._text(index)) + 2 * PAD_X + 10,
            metrics.height() + 2 * PAD_Y + 6,
        )
