"""Owns a build run: preflight, worker lifetime, log batching, state commit.

None of this belongs in a window. `preflight` in particular is pure, so the
three modal dialogs it replaces are now a testable list of reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..builder import submission_zip_name
from ..models import BuildResult, EngineInfo, Platform, PluginInfo, PluginStatus
from ..state import StateStore
from ..validation import Issue, check_zip_size
from .build_worker import BuildWorker
from .log_model import LogLevel, LogRecord, classify_uat_line

#: Batch interval for log delivery. A big build emits thousands of lines and a
#: per-line model insert visibly stalls the view.
FLUSH_MS = 100


@dataclass(frozen=True)
class BuildRequest:
    engine: EngineInfo
    jobs: list[PluginInfo]
    platforms: Platform
    work_root: Path
    ship_patterns: list[str]
    output_dir: Path
    hashes: dict[str, str] = field(default_factory=dict)
    dry_run: bool = False


@dataclass(frozen=True)
class Preflight:
    """Why a build can or cannot start."""

    blockers: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blockers


def preflight(
    engine: EngineInfo | None,
    platforms: Platform,
    selection: set[str],
    jobs: list[PluginInfo],
    issues: dict[str, list[Issue]] | None = None,
) -> Preflight:
    """Everything that used to be a QMessageBox, as data.

    Only the three run gates block. Per-plugin validation problems are surfaced
    as warnings — the same non-blocking treatment they have always had.
    """
    blockers: list[Issue] = []
    if engine is None:
        blockers.append(Issue("error", "Select an installed engine."))
    if platforms == Platform.NONE:
        blockers.append(Issue("error", "Select at least one target platform."))
    if not selection:
        blockers.append(Issue("error", "Tick at least one plugin to build."))

    warnings: list[Issue] = []
    for job in jobs:
        for issue in (issues or {}).get(job.name, ()):
            warnings.append(Issue(issue.level, f"{job.name}: {issue.message}"))
    return Preflight(blockers=blockers, warnings=warnings)


class BuildController(QObject):
    started = Signal(int)  # total jobs
    plugin_started = Signal(str)
    plugin_finished = Signal(object)  # BuildResult
    status_changed = Signal(str, object, str)  # name, PluginStatus, reason
    progress = Signal(int, int)  # done, total
    records = Signal(list)  # list[LogRecord] — always a batch
    finished = Signal(list, bool)  # results, cancelled

    def __init__(self, store: StateStore, parent: QObject | None = None):
        super().__init__(parent)
        self.store = store
        self._worker: BuildWorker | None = None
        self._request: BuildRequest | None = None
        self._buffer: list[LogRecord] = []
        self._current = ""
        self._done = 0
        self._cancel_requested = False
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(FLUSH_MS)
        self._flush_timer.timeout.connect(self._flush)

    # ------------------------------------------------------------------ state
    @property
    def is_running(self) -> bool:
        return self._worker is not None

    @property
    def cancelled(self) -> bool:
        return self._cancel_requested

    # ------------------------------------------------------------------- logs
    def log(
        self, text: str, level: LogLevel = LogLevel.INFO, source: str = "", group: bool = False
    ) -> None:
        self._buffer.append(
            LogRecord(text=text, level=level, source=source, group=group)
        )
        if not self._flush_timer.isActive():
            self._flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        self.records.emit(batch)

    # ------------------------------------------------------------------ start
    def start(self, request: BuildRequest) -> None:
        if self.is_running:
            return
        self._request = request
        self._current = ""
        self._done = 0
        self._cancel_requested = False

        total = len(request.jobs)
        prefix = "DRY RUN — " if request.dry_run else ""
        names = ", ".join(p.name for p in request.jobs)
        self.log(f"{prefix}Building {total} plugin(s) [{names}]")
        for job in request.jobs:
            self.status_changed.emit(job.name, PluginStatus.QUEUED, "")

        self._worker = BuildWorker(
            engine=request.engine,
            jobs=request.jobs,
            platforms=request.platforms,
            work_root=request.work_root,
            ship_patterns=request.ship_patterns,
            output_dir=request.output_dir,
            dry_run=request.dry_run,
        )
        self._worker.log.connect(self._on_worker_log)
        self._worker.plugin_started.connect(self._on_plugin_started)
        self._worker.plugin_finished.connect(self._on_plugin_finished)
        self._worker.progress.connect(self.progress)
        self._worker.finished_all.connect(self._on_finished)

        self.started.emit(total)
        self._flush_timer.start()
        self._worker.start()

    # ------------------------------------------------------------- worker in
    def _on_worker_log(self, text: str) -> None:
        # RunUAT output is unstructured; severity here is a display hint only
        # and never influences success, which comes from the exit code alone.
        self._buffer.append(
            LogRecord(text=text, level=classify_uat_line(text), source=self._current)
        )

    def _on_plugin_started(self, name: str) -> None:
        self._current = name
        total = len(self._request.jobs) if self._request else 0
        self._done += 1
        self.log(f"{name}  [{self._done}/{total}]", source=name, group=True)
        self.status_changed.emit(name, PluginStatus.BUILDING, "")
        self.plugin_started.emit(name)

    def _on_plugin_finished(self, result: BuildResult) -> None:
        request = self._request
        if result.success and result.zip_path is not None:
            self.status_changed.emit(result.plugin_name, PluginStatus.SUCCESS, "")
            # The 15 GiB FAB ceiling — previously written but never called.
            oversize = check_zip_size(result.zip_path)
            if oversize is not None:
                self.log(oversize.message, LogLevel.WARNING, result.plugin_name)
            digest = (request.hashes if request else {}).get(result.plugin_name)
            if digest:
                self.store.mark_built(result.plugin_name, digest)
                self.store.save()
        elif result.success:
            # Dry run: nothing was built, so leave it queued.
            self.status_changed.emit(result.plugin_name, PluginStatus.QUEUED, "")
        else:
            self.status_changed.emit(
                result.plugin_name, PluginStatus.FAILED, result.message
            )
            self.log(result.message, LogLevel.ERROR, result.plugin_name)
        self.plugin_finished.emit(result)

    def _on_finished(self, results: list[BuildResult]) -> None:
        cancelled = self._cancel_requested
        if cancelled and self._current:
            # A killed plugin was never really attempted — don't call it failed.
            self.status_changed.emit(self._current, PluginStatus.QUEUED, "")

        ok = sum(1 for r in results if r.success)
        if cancelled:
            self.log(f"Cancelled. {ok}/{len(results)} completed.", LogLevel.WARNING)
        else:
            level = LogLevel.INFO if ok == len(results) else LogLevel.ERROR
            self.log(f"Done. {ok}/{len(results)} succeeded.", level)

        self._flush_timer.stop()
        self._flush()
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.wait(2000)
            worker.deleteLater()
        self._current = ""
        self.finished.emit(results, cancelled)

    # ------------------------------------------------------------------- stop
    def cancel(self) -> None:
        if self._worker is None:
            return
        self._cancel_requested = True
        self.log("Cancelling — stopping the running build…", LogLevel.WARNING)
        self._flush()
        self._worker.cancel()

    def shutdown(self, timeout_ms: int = 8000) -> bool:
        """Stop everything before the window goes away.

        Returns False if the thread is still alive, in which case the caller
        must not let the window close yet — destroying a running QThread aborts.
        Cleans up here rather than waiting for `finished_all`, which is queued
        and may never be delivered once the event loop is shutting down.
        """
        worker = self._worker
        if worker is None:
            return True
        self._cancel_requested = True
        worker.cancel()
        stopped = worker.wait(timeout_ms)
        if not stopped:
            worker.terminate()
            stopped = worker.wait(1000)
        if stopped:
            self._flush_timer.stop()
            self._worker = None
        return stopped

    # --------------------------------------------------------------- helpers
    def expected_zips(self, request: BuildRequest) -> list[str]:
        return [submission_zip_name(job, request.engine) for job in request.jobs]
