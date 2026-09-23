"""The card frame every settings-style page is built from.

Lived as a private `_card` in both build_page and settings_page; a third copy
is where duplication stops being cheaper than a shared function.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


def card(title: str, blurb: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 13, 16, 14)
    layout.setSpacing(9)
    label = QLabel(title)
    label.setObjectName("cardTitle")
    layout.addWidget(label)
    if blurb:
        hint = QLabel(blurb)
        hint.setProperty("role", "caption")
        hint.setWordWrap(True)
        layout.addWidget(hint)
    return frame, layout
