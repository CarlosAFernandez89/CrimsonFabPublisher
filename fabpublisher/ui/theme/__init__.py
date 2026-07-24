"""Theme: the single place that turns tokens into colours for widgets.

`apply_theme`, the QSS and the drawn icons arrive with the shell rebuild; this
module starts as the colour lookup so no other file hard-codes a hex value.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette

from ...models import PluginStatus
from ..log_model import LogLevel, LogRecord
from .tokens import ACTIVE, CRIMSON_DARK, Tokens

__all__ = [
    "ACTIVE",
    "CRIMSON_DARK",
    "MONO_FAMILIES",
    "Tokens",
    "apply_theme",
    "color",
    "level_color",
    "log_record_html",
    "mono_font",
    "repolish",
    "status_color",
]

#: Ships with Windows 11 / Terminal, then Vista onwards, then anything.
MONO_FAMILIES = ["Cascadia Mono", "Consolas", "Courier New"]
UI_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Sans Serif"]
BASE_POINT_SIZE = 9.5

_STATUS_TOKEN: dict[PluginStatus, str] = {
    PluginStatus.UNKNOWN: "text_muted",
    PluginStatus.UP_TO_DATE: "success",
    PluginStatus.CHANGED: "warning",
    PluginStatus.NEEDS_RESUBMIT: "resubmit",
    PluginStatus.MISSING_DEP: "danger",
    PluginStatus.QUEUED: "neutral",
    PluginStatus.BUILDING: "info",
    PluginStatus.SUCCESS: "success",
    PluginStatus.FAILED: "danger",
}

_LEVEL_TOKEN: dict[LogLevel, str] = {
    LogLevel.DEBUG: "text_muted",
    LogLevel.INFO: "text_secondary",
    LogLevel.WARNING: "warning",
    LogLevel.ERROR: "danger",
}


def color(token: str) -> str:
    """Look a token up on the active theme."""
    return getattr(ACTIVE, token)


def status_color(status: PluginStatus) -> str:
    return color(_STATUS_TOKEN[status])


def level_color(level: LogLevel) -> str:
    return color(_LEVEL_TOKEN[level])


_LEADING_SPACES = re.compile(r"^ +")


def log_record_html(record: LogRecord) -> str:
    """One log line, coloured by severity, indentation preserved."""
    text = html.escape(record.text)
    text = _LEADING_SPACES.sub(lambda m: "&nbsp;" * len(m.group()), text)

    if record.group:
        return (
            f'<div style="color:{color("accent_text")};">'
            f"&#9472;&#9472; {text} "
            f'<span style="color:{color("border_strong")};">'
            f"{'&#9472;' * max(0, 60 - len(record.text))}</span></div>"
        )

    muted = color("text_muted")
    stamp = f'<span style="color:{muted};">{record.clock}</span>'
    where = (
        f' <span style="color:{muted};">[{html.escape(record.source)}]</span>'
        if record.source
        else ""
    )
    body = f'<span style="color:{level_color(record.level)};">{text}</span>'
    return f"{stamp}{where} {body}"


# ------------------------------------------------------------------ fonts
def mono_font(point_size: float | None = None) -> QFont:
    font = QFont()
    font.setFamilies(MONO_FAMILIES)
    font.setStyleHint(QFont.Monospace)
    font.setPointSizeF(point_size or BASE_POINT_SIZE)
    return font


def repolish(widget) -> None:
    """Re-evaluate property selectors after setProperty at runtime.

    Qt does not do this automatically, which is the single most common reason a
    `[state="…"]` rule appears not to work.
    """
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


# ------------------------------------------------------------- stylesheet
def _qss_path() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "fabpublisher" / "ui" / "theme" / "crimson.qss"
    return Path(__file__).resolve().parent / "crimson.qss"


_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def stylesheet(tokens: Tokens = ACTIVE) -> str:
    """Read the QSS and substitute tokens. Returns "" if it is missing."""
    path = _qss_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    values = tokens.as_dict()
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), raw)


def _palette(tokens: Tokens = ACTIVE) -> QPalette:
    """QSS cannot reach text selection, disabled roles or drawItemText."""
    p = QPalette()
    window = QColor(tokens.surface)
    text = QColor(tokens.text_primary)

    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, QColor(tokens.surface_sunken))
    p.setColor(QPalette.AlternateBase, QColor(tokens.surface_raised))
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, QColor(tokens.surface_overlay))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor(tokens.danger))
    p.setColor(QPalette.Highlight, QColor(tokens.accent))
    p.setColor(QPalette.HighlightedText, QColor(tokens.text_on_accent))
    p.setColor(QPalette.ToolTipBase, QColor(tokens.surface_overlay))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.PlaceholderText, QColor(tokens.text_muted))
    p.setColor(QPalette.Link, QColor(tokens.accent_text))

    disabled = QColor(tokens.text_muted)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, disabled)
    p.setColor(QPalette.Disabled, QPalette.Base, window)
    p.setColor(QPalette.Disabled, QPalette.Highlight, QColor(tokens.border))
    return p


def apply_theme(app, tokens: Tokens = ACTIVE) -> bool:
    """Style the whole application. Never raises — a missing QSS degrades to
    the palette alone rather than preventing startup.

    Order matters: the native Windows style ignores QSS on checkbox indicators,
    combo popups and progress chunks, so Fusion has to come first.
    """
    app.setStyle("Fusion")
    app.setPalette(_palette(tokens))

    font = QFont()
    font.setFamilies(UI_FAMILIES)
    font.setPointSizeF(BASE_POINT_SIZE)
    app.setFont(font)

    qss = stylesheet(tokens)
    app.setStyleSheet(qss)
    return bool(qss)
