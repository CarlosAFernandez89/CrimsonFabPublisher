"""Persistent build status bar.

Always visible so a 40-minute compile stays answerable from any page. Driven
only by ScanService/BuildController signals — pages never touch it.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
)

from .theme import repolish


def _mmss(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class BuildStatusStrip(QFrame):
    cancel_requested = Signal()
    open_output_requested = Signal()
    view_logs_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusStrip")
        self.setFixedHeight(42)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 12, 0)
        row.setSpacing(10)

        self.text = QLabel("Ready")
        self.text.setObjectName("statusText")
        row.addWidget(self.text)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(190)
        self.progress.setTextVisible(False)
        self.progress.hide()
        row.addWidget(self.progress)

        self.detail = QLabel("")
        self.detail.setObjectName("statusDetail")
        row.addWidget(self.detail)

        row.addStretch(1)

        self.errors_btn = QPushButton("")
        self.errors_btn.setProperty("variant", "danger")
        self.errors_btn.clicked.connect(self.view_logs_requested)
        self.errors_btn.hide()
        row.addWidget(self.errors_btn)

        self.open_btn = QPushButton("Open output folder")
        self.open_btn.setProperty("variant", "ghost")
        self.open_btn.clicked.connect(self.open_output_requested)
        self.open_btn.hide()
        row.addWidget(self.open_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_requested)
        self.cancel_btn.hide()
        row.addWidget(self.cancel_btn)

        self._started_at = 0.0
        self._done = 0
        self._total = 0
        self._current = ""
        self._platforms = ""
        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._tick)

    # ------------------------------------------------------------------ state
    def _set_state(self, state: str) -> None:
        self.setProperty("state", state)
        repolish(self)

    def _hide_actions(self) -> None:
        self.cancel_btn.hide()
        self.open_btn.hide()

    def set_idle(self, summary: str, last: str = "") -> None:
        self._ticker.stop()
        self._set_state("idle")
        self.text.setText(summary or "Ready")
        self.detail.setText("")
        self.progress.hide()
        self._hide_actions()
        if last:
            self.detail.setText(last)

    def set_scanning(self, root: str) -> None:
        self._set_state("idle")
        self.text.setText("Scanning…")
        self.detail.setText(root)
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.show()
        self._hide_actions()

    def start_build(self, total: int, platforms: str, dry_run: bool = False) -> None:
        self._started_at = time.monotonic()
        self._done = 0
        self._total = total
        self._current = ""
        self._platforms = platforms
        self._set_state("building")
        self.progress.setRange(0, max(total, 1) * 200)
        self.progress.setValue(0)
        self.progress.show()
        self.open_btn.hide()
        self.cancel_btn.show()
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("Cancel")
        self.text.setText("Dry run…" if dry_run else "Building…")
        self._ticker.start()
        self._tick()

    def set_progress(self, done: int, total: int) -> None:
        """Plugin-level counts, shown as text only.

        The bar itself is driven by `set_fine_progress`, which moves during a
        compile instead of only at plugin boundaries.
        """
        self._done, self._total = done, total
        self._tick()

    def set_fine_progress(self, value: int, maximum: int) -> None:
        self.progress.setRange(0, max(maximum, 1))
        self.progress.setValue(value)

    def set_current(self, name: str) -> None:
        self._current = name
        self._tick()

    def _tick(self) -> None:
        if not self._ticker.isActive():
            return
        elapsed = _mmss(time.monotonic() - self._started_at)
        bits = [f"{self._done}/{self._total}"]
        if self._current:
            bits.append(self._current)
        if self._platforms:
            bits.append(self._platforms)
        bits.append(elapsed)
        self.detail.setText("  ·  ".join(bits))

    def set_stopping(self) -> None:
        self.text.setText("Stopping build…")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("Stopping…")

    def set_finished(self, ok: int, total: int, cancelled: bool, can_open: bool) -> None:
        self._ticker.stop()
        elapsed = _mmss(time.monotonic() - self._started_at)
        self.progress.hide()
        self.cancel_btn.hide()
        if cancelled:
            self._set_state("failed")
            self.text.setText("Cancelled")
        else:
            self._set_state("ok" if ok == total else "failed")
            self.text.setText(f"Done — {ok}/{total} succeeded")
        self.detail.setText(f"in {elapsed}")
        self.open_btn.setVisible(can_open)

    def set_error_count(self, count: int) -> None:
        self.errors_btn.setText(f"{count} error{'s' if count != 1 else ''}")
        self.errors_btn.setVisible(count > 0)
