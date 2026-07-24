"""CrimsonFabPublisher entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from fabpublisher.ui.main_window import MainWindow
from fabpublisher.ui.theme import apply_theme


def _resource_path(name: str) -> Path:
    """Resolve a bundled resource both in dev and inside a PyInstaller exe."""
    base: str | None = getattr(sys, "_MEIPASS", None)
    if base:
        root = Path(base)
    else:
        root = Path(__file__).resolve().parent
    return root / name


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("CrimsonFabPublisher")
    if not apply_theme(app):
        print("crimson.qss not found — running with the palette only.")

    icon_path = _resource_path("app.ico")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
