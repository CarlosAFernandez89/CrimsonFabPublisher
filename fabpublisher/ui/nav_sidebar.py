"""Left navigation rail.

QToolButtons in an exclusive group rather than a QListWidget: the active-item
bar is then `:checked { border-left: 3px solid accent }` in pure QSS, where a
list view would need a delegate.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .theme import icons

WIDTH = 200

#: (icon name, label)
ITEMS: list[tuple[str, str]] = [
    ("plugins", "Plugins"),
    ("build", "Build"),
    ("listing", "Listings"),
    ("logs", "Logs"),
    ("settings", "Settings"),
]

PLUGINS, BUILD, LISTINGS, LOGS, SETTINGS = range(5)


class NavSidebar(QWidget):
    page_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._wordmark())
        root.addSpacing(6)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._buttons: list[QToolButton] = []
        self._badges: list[QLabel] = []

        for index, (icon_name, label) in enumerate(ITEMS):
            button = self._nav_button(icon_name, label, index)
            self.group.addButton(button, index)
            root.addWidget(button)
            self._buttons.append(button)

        root.addStretch(1)

        self.engine_label = QLabel("No engine")
        self.engine_label.setObjectName("navFooter")
        self.engine_label.setProperty("role", "hint")
        self.engine_label.setContentsMargins(15, 8, 12, 12)
        self.engine_label.setWordWrap(True)
        root.addWidget(self.engine_label)

        self.group.idClicked.connect(self.page_changed)
        self._buttons[0].setChecked(True)

    # ------------------------------------------------------------------ build
    def _wordmark(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(15, 16, 12, 14)
        layout.setSpacing(0)

        top = QLabel("CRIMSON")
        top.setObjectName("wordmark")
        sub = QLabel("FabPublisher")
        sub.setObjectName("wordmarkSub")
        layout.addWidget(top)
        layout.addWidget(sub)
        return holder

    def _nav_button(self, icon_name: str, label: str, index: int) -> QToolButton:
        button = QToolButton()
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setText(label)
        button.setIcon(icons.icon(icon_name))
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setCursor(Qt.PointingHandCursor)

        # A layout on the button parks the badge at its right edge without
        # needing a wrapper widget, which would break the :checked border.
        badge = QLabel("", button)
        badge.setObjectName("navBadge")
        badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        badge.setAlignment(Qt.AlignCenter)
        badge.hide()

        row = QHBoxLayout(button)
        row.setContentsMargins(0, 0, 10, 0)
        row.addStretch(1)
        row.addWidget(badge)
        self._badges.append(badge)
        return button

    # ----------------------------------------------------------------- public
    def set_page(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)

    def current_page(self) -> int:
        return self.group.checkedId()

    def set_badge(self, index: int, text: str) -> None:
        """Show a count on a nav item, e.g. errors on Logs. Empty hides it."""
        if not 0 <= index < len(self._badges):
            return
        badge = self._badges[index]
        badge.setText(text)
        badge.setVisible(bool(text))

    def set_engine(self, label: str) -> None:
        self.engine_label.setText(label)
