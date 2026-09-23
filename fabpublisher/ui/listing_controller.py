"""Owns the listing run: the service, its workers, and the log batch.

The same division of labour as `BuildController` - the page emits intent, this
decides what happens, and the domain layer does the work. Log lines are
buffered on a timer rather than inserted one at a time, because a per-line
model insert visibly stalls the view.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..listing import prompt as prompt_mod
from ..listing import source
from ..listing.service import AcceptResult, ListingScan, ListingService
from ..models import EngineInfo, PluginInfo
from .draft_worker import DraftWorker, resolve_cli
from .listing_worker import ListingWorker
from .log_model import LogLevel, LogRecord

FLUSH_MS = 100
SHUTDOWN_MS = 5000


class ListingController(QObject):
    records = Signal(list)  # list[LogRecord]
    check_started = Signal(int)
    check_progress = Signal(int, int)
    check_finished = Signal(object)  # ListingScan
    draft_started = Signal(str)  # plugin id
    draft_line = Signal(str)
    draft_finished = Signal(str, str, str)  # plugin id, raw output, error
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.service: ListingService | None = None
        self.prompt_template = ""
        #: Per-plugin Claude session ids, so a follow-up resumes rather than
        #: starting cold. Kept on disk beside the listing copy.
        self._sessions: dict[str, str] = {}
        self._worker: ListingWorker | None = None
        self._draft: DraftWorker | None = None
        self._draft_plugin = ""
        self._overwrite_next = False
        self._buffer: list[LogRecord] = []
        self._timer = QTimer(self)
        self._timer.setInterval(FLUSH_MS)
        self._timer.timeout.connect(self._flush)
        self._started_at = 0.0

    # ------------------------------------------------------------------ setup
    def configure(
        self,
        listings_dir: str,
        output_dir: Path,
        faq_review: bool = True,
        changelog_review: bool = True,
    ) -> None:
        self.service = ListingService(
            listings_dir,
            output_dir,
            faq_review=faq_review,
            changelog_review=changelog_review,
        )
        self._sessions = source.load_sessions(self.service.listings_dir)

    @property
    def busy(self) -> bool:
        return bool(
            (self._worker and self._worker.isRunning())
            or (self._draft and self._draft.isRunning())
        )

    # -------------------------------------------------------------------- log
    def log(self, text: str, level: LogLevel = LogLevel.INFO, sourced: str = "") -> None:
        self._buffer.append(LogRecord(text, level, sourced))

    def _flush(self) -> None:
        if not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        self.records.emit(batch)

    # ------------------------------------------------------------------ check
    def check(
        self,
        plugins: list[PluginInfo],
        engine: EngineInfo | None,
        dev_platforms: list[str],
    ) -> bool:
        """Start a check. False when one is already running or nothing to do."""
        if self.service is None or self.busy or not plugins:
            return False

        self._started_at = time.time()
        self._worker = ListingWorker(self.service, plugins, engine, dev_platforms, self)
        self._worker.progress.connect(self.check_progress)
        self._worker.finished_scan.connect(self._on_scan)
        self._worker.finished.connect(lambda: self.busy_changed.emit(self.busy))

        self.log(f"Checking {len(plugins)} listing(s)...")
        self._timer.start()
        self.check_started.emit(len(plugins))
        self.busy_changed.emit(True)
        self._worker.start()
        return True

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        if self._draft is not None:
            self._draft.cancel()

    def _on_scan(self, scan: ListingScan) -> None:
        elapsed = time.time() - self._started_at
        if scan.error:
            self.log(scan.error, LogLevel.WARNING)
        else:
            blocked = sum(1 for r in scan.publishable if r.blocked)
            self.log(
                f"Checked {len(scan.publishable)} listing(s) in {elapsed:.1f}s - "
                f"{len(scan.publishable) - blocked} ready, {blocked} blocked."
            )
        self._flush()
        self._timer.stop()
        self.check_finished.emit(scan)
        self.busy_changed.emit(self.busy)

    # ------------------------------------------------------------------ build
    def build(self, scan: ListingScan) -> list[Path]:
        if self.service is None or scan.error:
            return []
        written = self.service.build(scan)
        self.log(f"Wrote {len(scan.publishable)} bundle(s) and the status table.")
        self._flush()
        return written

    # ----------------------------------------------------------------- accept
    def accept(self, rows, force: bool = False) -> AcceptResult:
        if self.service is None:
            return AcceptResult()
        result = self.service.accept(
            rows, force=force, submitted_at=time.strftime("%Y-%m-%d")
        )
        for plugin_id in result.accepted:
            self.log(f"Accepted {plugin_id}; snapshot recorded.", sourced=plugin_id)
        for plugin_id, reason in result.refused:
            self.log(f"Refused {plugin_id}: {reason}", LogLevel.WARNING, plugin_id)
        if result.accepted:
            self.log(
                f"Recorded {result.fields_recorded} field(s) across "
                f"{len(result.accepted)} listing(s)."
            )
        self._flush()
        return result

    # ------------------------------------------------------------------ draft
    def draft_prompt_for(self, row) -> str:
        folders = [
            name
            for name in ("Source", "Content", "Config", "Resources")
            if (row.plugin.path / name).is_dir()
        ]
        return prompt_mod.draft_prompt(
            row.plugin,
            row.authored,
            folders,
            template=self.prompt_template,
            requirements=row.requirements,
        )

    def has_session(self, plugin_id: str) -> bool:
        """True when a previous draft left a conversation to continue."""
        return bool(self._sessions.get(plugin_id))

    def start_draft(
        self, row, claude_path: str = "", instruction: str = ""
    ) -> str:
        """Launch the drafter. Returns "" on success, else why it could not.

        With an `instruction` this is a follow-up: it resumes the plugin's
        existing conversation, so the model still has its own draft in context
        and "make the technical section shorter" means something.
        """
        if self.busy:
            return "Something is already running."
        executable = resolve_cli(claude_path)
        if executable is None:
            return (
                "The Claude CLI is not on PATH. Copy the prompt instead, or set "
                "its location in Settings."
            )

        resume = bool(instruction) and self.has_session(row.plugin_id)
        if resume:
            session_id = self._sessions[row.plugin_id]
            text = prompt_mod.improve_prompt(instruction)
        else:
            # No session to continue, so start one and name it. A follow-up
            # without a session still works - the prompt carries the current
            # copy - it just has no memory of how it got there.
            session_id = str(uuid.uuid4())
            self._sessions[row.plugin_id] = session_id
            if self.service is not None:
                source.save_sessions(self.service.listings_dir, self._sessions)
            text = self.draft_prompt_for(row)
            if instruction:
                text += (
                    "\n\n## Also do this\n\n" + instruction.strip() + "\n"
                )

        self._overwrite_next = bool(instruction)
        self._draft_plugin = row.plugin_id
        self._draft = DraftWorker(
            executable, text, self, session_id=session_id, resume=resume
        )
        self._draft.line.connect(self._on_draft_line)
        self._draft.finished_draft.connect(self._on_draft_done)
        self._draft.finished.connect(lambda: self.busy_changed.emit(self.busy))

        self.log(f"Drafting listing copy for {row.plugin_id}...", sourced=row.plugin_id)
        self._timer.start()
        self.draft_started.emit(row.plugin_id)
        self.busy_changed.emit(True)
        self._draft.start()
        return ""

    def _on_draft_line(self, text: str) -> None:
        self.log(text, LogLevel.INFO, self._draft_plugin)
        self.draft_line.emit(text)

    def _on_draft_done(self, output: str, error: str) -> None:
        plugin_id = self._draft_plugin
        if error:
            self.log(f"Draft: {error}", LogLevel.WARNING, plugin_id)
        self._flush()
        self._timer.stop()
        self.draft_finished.emit(plugin_id, output, error)
        self.busy_changed.emit(self.busy)

    @property
    def draft_overwrites(self) -> bool:
        """A follow-up replaces what it was asked to change; a first draft fills gaps."""
        return self._overwrite_next

    def apply_draft(self, row, output: str, overwrite: bool = False) -> str:
        """Fold a draft into the listing file. Returns "" or an explanation."""
        if self.service is None:
            return "No listings folder is configured."
        parsed = prompt_mod.extract_json_block(output)
        if parsed is None:
            # Never silently discard a draft: keep the raw text and say where.
            path = source.draft_path(self.service.listings_dir, row.plugin_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(output, encoding="utf-8")
            return f"Could not read a JSON object from the draft. Raw text saved to {path}."

        merged = prompt_mod.merge_draft(row.authored, parsed, overwrite)
        source.save_source(self.service.listings_dir, row.plugin_id, merged)
        self.log(f"Draft merged into {row.plugin_id}.json", sourced=row.plugin_id)
        self._flush()
        return ""

    # --------------------------------------------------------------- shutdown
    def shutdown(self) -> bool:
        """Stop both workers. False if a thread refused to stop in time."""
        self._timer.stop()
        stopped = True
        for worker in (self._worker, self._draft):
            if worker is None or not worker.isRunning():
                continue
            worker.cancel()
            if not worker.wait(SHUTDOWN_MS):
                stopped = False
        self._flush()
        return stopped
