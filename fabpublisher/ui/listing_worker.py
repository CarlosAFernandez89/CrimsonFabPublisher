"""Run a listing check off the UI thread.

Hashing two dozen submission zips is minutes, not milliseconds, so the check
cannot run inline. Same cancel shape as `BuildWorker`: a flag the loop reads
between plugins, since there is no long-lived subprocess to kill here.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..listing.service import ListingService
from ..models import EngineInfo, PluginInfo


class ListingWorker(QThread):
    progress = Signal(int, int)  # done, total
    finished_scan = Signal(object)  # ListingScan

    def __init__(
        self,
        service: ListingService,
        plugins: list[PluginInfo],
        engine: EngineInfo | None,
        dev_platforms: list[str],
        parent=None,
    ):
        super().__init__(parent)
        self._service = service
        self._plugins = list(plugins)
        self._engine = engine
        self._dev_platforms = list(dev_platforms)
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def _on_progress(self, done: int, total: int) -> bool:
        self.progress.emit(done, total)
        # Returning False stops the service loop at the next plugin.
        return not self._cancelled

    def run(self) -> None:
        scan = self._service.check(
            self._plugins,
            engine=self._engine,
            dev_platforms=self._dev_platforms,
            on_progress=self._on_progress,
        )
        self.finished_scan.emit(scan)
