"""Background thread that runs the build queue off the UI thread."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..builder import kill_process_tree, run_build
from ..models import BuildResult, EngineInfo, Platform, PluginInfo
from ..shipfilter import ShipFilter


class BuildWorker(QThread):
    log = Signal(str)
    plugin_started = Signal(str)
    plugin_finished = Signal(object)  # BuildResult
    progress = Signal(int, int)       # done, total
    finished_all = Signal(list)       # list[BuildResult]

    def __init__(
        self,
        engine: EngineInfo,
        jobs: list[PluginInfo],
        platforms: Platform,
        work_root: Path,
        ship_patterns: list[str],
        output_dir: Path,
        dry_run: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._engine = engine
        self._jobs = jobs
        self._platforms = platforms
        self._work_root = Path(work_root)
        self._ship_filter = ShipFilter(ship_patterns)
        self._output_dir = Path(output_dir)
        self._dry_run = dry_run
        self._cancelled = False
        self._proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """Stop now, not after the current plugin.

        RunUAT blocks for minutes, so the flag alone is not enough — the running
        process tree has to be killed for cancel to mean anything.
        """
        self._cancelled = True
        with self._proc_lock:
            proc = self._proc
        if proc is not None:
            kill_process_tree(proc)

    def _track(self, proc: subprocess.Popen) -> None:
        with self._proc_lock:
            self._proc = proc
        # A cancel that landed between launch and here must still take effect.
        if self._cancelled:
            kill_process_tree(proc)

    def _untrack(self) -> None:
        with self._proc_lock:
            self._proc = None

    def run(self) -> None:
        results: list[BuildResult] = []
        failed: set[str] = set()
        total = len(self._jobs)

        for done, plugin in enumerate(self._jobs):
            if self._cancelled:
                self.log.emit("Build cancelled by user.")
                break

            # Skip a plugin whose in-suite dependency already failed this run.
            blocking = [d for d in plugin.suite_dependency_names if d in failed]
            if blocking:
                msg = f"Skipping {plugin.name}: dependency failed ({', '.join(blocking)})"
                self.log.emit(msg)
                result = BuildResult(plugin.name, False, None, msg)
                failed.add(plugin.name)
                results.append(result)
                self.plugin_finished.emit(result)
                self.progress.emit(done + 1, total)
                continue

            self.plugin_started.emit(plugin.name)
            try:
                result = run_build(
                    engine=self._engine,
                    plugin=plugin,
                    platforms=self._platforms,
                    work_root=self._work_root,
                    ship_filter=self._ship_filter,
                    output_dir=self._output_dir,
                    log=self.log.emit,
                    dry_run=self._dry_run,
                    on_process_started=self._track,
                )
            finally:
                self._untrack()

            if self._cancelled:
                self.log.emit("Build cancelled by user.")
                break

            if not result.success:
                failed.add(plugin.name)
            results.append(result)
            self.plugin_finished.emit(result)
            self.progress.emit(done + 1, total)

        self.finished_all.emit(results)
