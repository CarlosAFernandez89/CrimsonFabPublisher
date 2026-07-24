"""Structured build log.

The old UI appended raw strings straight into a QPlainTextEdit, so severity,
timing and per-plugin grouping were all unrecoverable. Everything lives in the
model now; views only render it.
"""

from __future__ import annotations

import enum
import re
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal

#: Beyond this the oldest records are dropped — a long build emits 20k+ lines.
MAX_RECORDS = 100_000


class LogLevel(enum.IntEnum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40


@dataclass(frozen=True, slots=True)
class LogRecord:
    text: str
    level: LogLevel = LogLevel.INFO
    source: str = ""  # "" for app events, plugin name during a build
    ts: float = field(default_factory=time.time)
    group: bool = False  # render as a section divider

    @property
    def clock(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.ts))


# --------------------------------------------------------------------- UAT
# RunUAT/UBT output is unstructured, so severity here is a display hint only.
# It never influences build success, which comes solely from the exit code.

#: The one unambiguous signal: an MSVC/clang diagnostic code.
_DIAGNOSTIC = re.compile(r":\s*(?:fatal\s+)?(error|warning)\s+[A-Z]+\d+\s*:", re.I)
#: "0 Errors, 0 Warnings" style summaries must not read as failures.
_ZERO_COUNT = re.compile(r"\b0\s+(?:error|warning)s?\b", re.I)
_ERRORISH = re.compile(
    r"(?i)(?:^|\W)(?:error|fatal|exception|unhandled|build failed|failed to)(?:\W|$)"
)
_WARNISH = re.compile(r"(?i)(?:^|\W)warn(?:ing)?(?:\W|$)")


def classify_uat_line(text: str) -> LogLevel:
    """Best-effort severity for one line of RunUAT output.

    Deliberately conservative: the default log filter shows everything, so a
    misclassification can only mis-colour a line, never hide it.
    """
    if _DIAGNOSTIC.search(text):
        return (
            LogLevel.ERROR
            if _DIAGNOSTIC.search(text).group(1).lower() == "error"
            else LogLevel.WARNING
        )
    if _ZERO_COUNT.search(text):
        return LogLevel.INFO
    if _ERRORISH.search(text):
        return LogLevel.ERROR
    if _WARNISH.search(text):
        return LogLevel.WARNING
    return LogLevel.INFO


def level_from_issue(level: str) -> LogLevel:
    """Map a `validation.Issue.level` exactly — app data is never guessed."""
    return LogLevel.ERROR if level == "error" else LogLevel.WARNING


# ------------------------------------------------------------------- model
LevelRole = Qt.UserRole + 1
SourceRole = Qt.UserRole + 2
RecordRole = Qt.UserRole + 3


class LogModel(QAbstractListModel):
    sources_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: list[LogRecord] = []
        self._sources: list[str] = []
        self._dropped = 0
        self._has_notice = False

    # ---- population ------------------------------------------------------
    def append(
        self,
        text: str,
        level: LogLevel = LogLevel.INFO,
        source: str = "",
        group: bool = False,
    ) -> None:
        self.extend([LogRecord(text=text, level=level, source=source, group=group)])

    def extend(self, records: list[LogRecord]) -> None:
        """Insert a batch in one signal — per-line inserts stall the view."""
        if not records:
            return
        start = len(self._records)
        self.beginInsertRows(QModelIndex(), start, start + len(records) - 1)
        self._records.extend(records)
        self.endInsertRows()

        new_sources = [
            r.source for r in records if r.source and r.source not in self._sources
        ]
        if new_sources:
            for name in new_sources:
                if name not in self._sources:
                    self._sources.append(name)
            self.sources_changed.emit()

        self._trim()

    def _trim(self) -> None:
        """Ring-drop the oldest records, keeping one notice row at the top."""
        if len(self._records) <= MAX_RECORDS:
            return
        # Drop from below the notice so it is never the thing we delete, and
        # count the notice itself against the cap so the total stays exact.
        first = 1 if self._has_notice else 0
        excess = len(self._records) - MAX_RECORDS + (0 if self._has_notice else 1)
        self.beginRemoveRows(QModelIndex(), first, first + excess - 1)
        del self._records[first : first + excess]
        self.endRemoveRows()

        self._dropped += excess
        notice = LogRecord(
            text=(
                f"… {self._dropped:,} earlier lines dropped "
                f"(log capped at {MAX_RECORDS:,})"
            ),
            level=LogLevel.WARNING,
        )
        if self._has_notice:
            self._records[0] = notice
            top = self.index(0, 0)
            self.dataChanged.emit(top, top)
        else:
            self.beginInsertRows(QModelIndex(), 0, 0)
            self._records.insert(0, notice)
            self.endInsertRows()
            self._has_notice = True

    def clear(self) -> None:
        self.beginResetModel()
        self._records = []
        self._sources = []
        self._dropped = 0
        self._has_notice = False
        self.endResetModel()
        self.sources_changed.emit()

    # ---- access ----------------------------------------------------------
    def records(self) -> list[LogRecord]:
        return self._records

    def sources(self) -> list[str]:
        return list(self._sources)

    def filtered(
        self, min_level: LogLevel = LogLevel.DEBUG, source: str | None = None
    ) -> list[LogRecord]:
        return [
            r
            for r in self._records
            if r.level >= min_level and (source is None or r.source == source)
        ]

    def to_text(
        self, min_level: LogLevel = LogLevel.DEBUG, source: str | None = None
    ) -> str:
        """Plain-text export. The frozen exe has no console — this is the only
        way a user can hand over a diagnostic."""
        lines = []
        for r in self.filtered(min_level, source):
            tag = r.level.name.ljust(7)
            where = f" [{r.source}]" if r.source else ""
            lines.append(f"{r.clock} {tag}{where} {r.text}")
        return "\n".join(lines)

    # ---- Qt model interface ---------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._records)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        record = self._records[index.row()]
        if role == Qt.DisplayRole:
            return record.text
        if role == LevelRole:
            return record.level
        if role == SourceRole:
            return record.source
        if role == RecordRole:
            return record
        return None
