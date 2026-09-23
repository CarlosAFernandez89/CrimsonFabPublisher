"""Icons drawn with QPainter.

A handful of glyphs do not justify shipping SVG files: that would mean an assets folder,
another PyInstaller data entry, and a dependency on the qsvg imageformats plugin
being bundled correctly — which fails silently in the frozen exe. Drawing them
also means they recolour from tokens for free.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import color

SIZE = 20
_cache: dict[tuple[str, str, int], QIcon] = {}


def _pen(painter: QPainter, hex_color: str, width: float = 1.6) -> QPen:
    pen = QPen(QColor(hex_color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    return pen


def _plugins(p: QPainter, c: str, s: int) -> None:
    """A grid of squares — a set of things."""
    _pen(p, c)
    cell = s * 0.34
    gap = s * 0.10
    left = (s - (cell * 2 + gap)) / 2
    for row in range(2):
        for col in range(2):
            p.drawRect(
                QRectF(
                    left + col * (cell + gap),
                    left + row * (cell + gap),
                    cell,
                    cell,
                )
            )


def _build(p: QPainter, c: str, s: int) -> None:
    """A play triangle — run it."""
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(c))
    path = QPainterPath()
    path.moveTo(QPointF(s * 0.30, s * 0.20))
    path.lineTo(QPointF(s * 0.80, s * 0.50))
    path.lineTo(QPointF(s * 0.30, s * 0.80))
    path.closeSubpath()
    p.drawPath(path)


def _logs(p: QPainter, c: str, s: int) -> None:
    """Stacked lines of differing length — a text stream."""
    _pen(p, c, 1.7)
    for i, frac in enumerate((0.78, 0.55, 0.86, 0.42)):
        y = s * (0.24 + i * 0.17)
        p.drawLine(QPointF(s * 0.16, y), QPointF(s * 0.16 + s * frac * 0.78, y))


def _settings(p: QPainter, c: str, s: int) -> None:
    """Three sliders. A gear is the one shape that never draws cleanly small."""
    _pen(p, c, 1.7)
    for i, knob in enumerate((0.66, 0.34, 0.54)):
        y = s * (0.26 + i * 0.24)
        p.drawLine(QPointF(s * 0.15, y), QPointF(s * 0.85, y))
        p.setBrush(QColor(c))
        p.drawEllipse(QPointF(s * knob, y), s * 0.085, s * 0.085)
        p.setBrush(Qt.NoBrush)


def _rescan(p: QPainter, c: str, s: int) -> None:
    """A circular arrow."""
    _pen(p, c, 1.7)
    box = QRectF(s * 0.18, s * 0.18, s * 0.64, s * 0.64)
    p.drawArc(box, 60 * 16, 280 * 16)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(c))
    head = QPainterPath()
    tip = QPointF(s * 0.74, s * 0.20)
    head.moveTo(tip)
    head.lineTo(QPointF(tip.x() - s * 0.19, tip.y() + s * 0.04))
    head.lineTo(QPointF(tip.x() - s * 0.03, tip.y() + s * 0.21))
    head.closeSubpath()
    p.drawPath(head)


def _cancel(p: QPainter, c: str, s: int) -> None:
    """A stop square."""
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(c))
    p.drawRoundedRect(QRectF(s * 0.27, s * 0.27, s * 0.46, s * 0.46), 2, 2)


def _listing(p: QPainter, c: str, s: int) -> None:
    """A framed page with lines - a document, not the bare lines of _logs."""
    pen = QPen(QColor(c))
    pen.setWidthF(max(1.0, s * 0.075))
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(s * 0.22, s * 0.14, s * 0.56, s * 0.72), 2, 2)
    for i in range(3):
        y = s * (0.32 + i * 0.16)
        p.drawLine(QPointF(s * 0.34, y), QPointF(s * 0.66, y))


_SHAPES = {
    "plugins": _plugins,
    "build": _build,
    "logs": _logs,
    "settings": _settings,
    "listing": _listing,
    "rescan": _rescan,
    "cancel": _cancel,
}


def icon(name: str, token: str = "text_secondary", size: int = SIZE) -> QIcon:
    """A cached, token-coloured icon. Unknown names return an empty QIcon."""
    key = (name, token, size)
    if key in _cache:
        return _cache[key]

    shape = _SHAPES.get(name)
    if shape is None:
        return QIcon()

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    shape(painter, color(token), size)
    painter.end()

    result = QIcon(pixmap)
    _cache[key] = result
    return result


def names() -> list[str]:
    return list(_SHAPES)
