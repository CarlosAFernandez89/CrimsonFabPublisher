"""Application shell.

Owns five things — settings, scan service, build controller, listing
controller, log model — wires them to the pages, and computes nothing itself.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import state_path
from ..dependencies import transitive_dependencies
from ..engines import detect_engines
from ..models import EngineInfo, PluginInfo, platform_uat_name
from ..platforms import detect_platform_availability
from ..scan_service import ScanService
from ..state import StateStore
from .app_settings import AppSettings
from .build_controller import BuildController, BuildRequest, preflight
from .listing_controller import ListingController
from .log_model import LogLevel, LogModel, level_from_issue
from .nav_sidebar import BUILD, LOGS, SETTINGS, NavSidebar
from .pages.build_page import BuildPage
from .pages.listings_page import ListingsPage
from .pages.logs_page import LogsPage
from .pages.plugins_page import PluginsPage
from .pages.settings_page import SettingsPage
from .plugin_table_model import PluginTableModel
from .status_strip import BuildStatusStrip


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CrimsonFabPublisher")
        self.resize(1180, 780)

        self.settings = AppSettings.load(self)
        self.logs = LogModel(self)
        self.engines: list[EngineInfo] = detect_engines(
            self.settings.custom_engine_roots
        )
        # Probe against the saved engine, not blind: a toolchain that is valid
        # for one engine can be rejected by another.
        self.platform_info = detect_platform_availability(
            engine.root if (engine := self._selected_engine()) else None
        )
        self.store = StateStore(state_path())
        self.scanner = ScanService(self.store)
        self.build = BuildController(self.store, self)
        self.listings = ListingController(self)
        self.model = PluginTableModel(self)

        self._current_hashes: dict[str, str] = {}
        self._issues: dict[str, list] = {}
        self._selection_restored = False
        self._listing_scan = None
        self._last_summary = ""

        self._build_ui()
        self._connect()
        # _build_ui may have landed on a different engine than the saved one.
        self._refresh_platform_info()
        self._configure_listings()
        self._restore_geometry()
        self.rescan()

    # --------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.nav = NavSidebar()
        row.addWidget(self.nav)

        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        self.stack = QStackedWidget()
        self.plugins_page = PluginsPage(self.settings, self.model)
        self.build_page = BuildPage(self.settings, self.engines, self.platform_info)
        self.listings_page = ListingsPage()
        self.logs_page = LogsPage(self.logs)
        self.settings_page = SettingsPage(self.settings)
        # Order must match nav_sidebar.ITEMS: the two are coupled positionally.
        for page in (
            self.plugins_page,
            self.build_page,
            self.listings_page,
            self.logs_page,
            self.settings_page,
        ):
            self.stack.addWidget(page)
        column.addWidget(self.stack, 1)

        self.strip = BuildStatusStrip()
        column.addWidget(self.strip)

        row.addWidget(right, 1)
        self.setCentralWidget(central)

        # The engine combo lives on the Build page; align settings with it once.
        self.settings.engine_id = self.build_page.engine_combo.currentData() or ""
        self.build_page.commit_platforms()
        self.settings_page.set_detected(self._auto_detected())

    def _connect(self) -> None:
        self.nav.page_changed.connect(self._show_page)

        self.plugins_page.rescan_requested.connect(self.rescan)
        self.plugins_page.choose_folder_requested.connect(self._browse_root)
        self.plugins_page.selection_changed.connect(self._refresh_build_page)
        self.plugins_page.open_settings_requested.connect(
            lambda: self._show_page(SETTINGS)
        )
        self.model.dataChanged.connect(lambda *_: self._refresh_build_page())

        self.build_page.build_requested.connect(self._start_build)
        self.build_page.cancel_requested.connect(self.build.cancel)
        self.build_page.engine_changed.connect(self._engine_selected)
        self.build_page.platforms_changed.connect(self._refresh_build_page)
        self.settings.work_dir_changed.connect(lambda _: self._refresh_build_page())
        self.build_page.platforms_unavailable.connect(self._on_platforms_unavailable)

        self.listings_page.check_requested.connect(self._check_listings)
        self.listings_page.build_requested.connect(self._build_listings)
        self.listings_page.accept_requested.connect(self._accept_listings)
        self.listings_page.cancel_requested.connect(self.listings.cancel)
        self.listings_page.draft_requested.connect(self._draft_listing)
        self.listings_page.improve_requested.connect(self._improve_listing)
        self.listings_page.copy_prompt_requested.connect(self._copy_listing_prompt)
        self.listings_page.open_bundle_requested.connect(self._open_bundle)
        self.listings_page.open_settings_requested.connect(
            lambda: self._show_page(SETTINGS)
        )
        self.listings_page.editor.saved.connect(lambda _: self._recheck_listings())

        self.listings.records.connect(self.logs.extend)
        self.listings.check_finished.connect(self._on_listing_scan)
        self.listings.busy_changed.connect(self.listings_page.set_busy)
        self.listings.draft_started.connect(self.listings_page.begin_draft)
        self.listings.draft_line.connect(self.listings_page.append_draft_line)
        self.listings.draft_finished.connect(self._on_draft_finished)

        self.settings_page.plugins_root_changed.connect(self.rescan)
        self.settings_page.listings_dir_changed.connect(self._configure_listings)
        self.settings_page.build_history_reset.connect(self._reset_history)
        self.settings_page.engine_roots_changed.connect(self._reload_engines)

        self.logs.rowsInserted.connect(lambda *_: self._refresh_error_badge())
        self.logs.modelReset.connect(self._refresh_error_badge)

        self.build.records.connect(self.logs.extend)
        self.build.status_changed.connect(self.model.set_status)
        self.build.started.connect(self._on_build_started)
        self.build.plugin_started.connect(self.strip.set_current)
        self.build.progress.connect(self.strip.set_progress)
        self.build.fine_progress.connect(self.strip.set_fine_progress)
        self.build.finished.connect(self._on_build_finished)

        self.strip.cancel_requested.connect(self._cancel_build)
        self.strip.view_logs_requested.connect(self._show_errors)
        self.strip.open_output_requested.connect(self._open_output)

    def _show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav.set_page(index)

    def _show_errors(self) -> None:
        self.logs_page.show_errors()
        self._show_page(LOGS)

    # ---------------------------------------------------------------- scanning
    def _selected_engine(self) -> EngineInfo | None:
        ident = self.settings.engine_id
        for engine in self.engines:
            if engine.identifier == ident:
                return engine
        return None

    def _engine_selected(self, identifier: str) -> None:
        self.settings.engine_id = identifier
        self._refresh_platform_info()
        self.rescan()

    def _refresh_platform_info(self) -> None:
        """Toolchain validity is per-engine, so re-probe whenever it changes."""
        engine = self._selected_engine()
        self.platform_info = detect_platform_availability(
            engine.root if engine else None
        )
        self.build_page.set_platform_info(self.platform_info)

    def _on_platforms_unavailable(self, names: list) -> None:
        self._log(
            f"Unchecked {', '.join(names)} — not buildable with the selected engine.",
            LogLevel.WARNING,
        )

    def _reload_engines(self) -> None:
        """Re-run detection after the manual engine roots changed."""
        self.engines = detect_engines(self.settings.custom_engine_roots)
        self.build_page.set_engines(self.engines)
        self.settings_page.set_detected(self._auto_detected())
        self.settings.engine_id = self.build_page.engine_combo.currentData() or ""
        self._log(f"Engine list reloaded — {len(self.engines)} available.")
        self._refresh_platform_info()
        self.rescan()

    def _auto_detected(self) -> list[EngineInfo]:
        """Only the engines found without help, for the Settings summary."""
        manual = {str(Path(r)).lower() for r in self.settings.custom_engine_roots}
        return [e for e in self.engines if str(e.root).lower() not in manual]

    def rescan(self) -> None:
        engine = self._selected_engine()
        self.strip.set_scanning(self.settings.plugins_root)
        result = self.scanner.scan(self.settings.plugins_root, engine)

        self._current_hashes = result.hashes
        self._issues = result.issues
        self.model.set_impact(result.impact)
        self.model.set_engine_version(engine.version if engine else "")
        self.model.set_plugins(result.plugins)

        if result.plugins and not self._selection_restored:
            self.model.set_checked(self.settings.selection)
            self._selection_restored = True
        if result.plugins and self.settings.auto_select_changed:
            self.model.set_checked(self.model.rebuild_names())

        engine_label = engine.label if engine else "No engine"
        self.nav.set_engine(engine_label)
        self.plugins_page.set_context(self.settings.plugins_root, engine_label)

        if result.scanned:
            self._log_scan(result)

        rebuild = len(self.model.rebuild_names())
        self._last_summary = (
            f"{len(result.plugins)} plugins · {rebuild} need rebuild"
            if result.scanned
            else "No plugins folder set"
        )
        self.strip.set_idle(self._last_summary)
        self._refresh_build_page()

    def _log_scan(self, result) -> None:
        if result.cycle_error:
            self._log(f"Dependency cycle: {result.cycle_error}", LogLevel.ERROR)
        self._log(f"Scanned {len(result.plugins)} plugins in {result.root}")
        for plugin in result.plugins:
            for issue in result.issues.get(plugin.name, ()):
                # Issue.level is app data — mapped exactly, never guessed.
                self._log(issue.message, level_from_issue(issue.level), plugin.name)
        if result.changed:
            self._log(f"Changed: {', '.join(sorted(result.changed))}")
            if result.resubmit_only:
                self._log(
                    "Must also resubmit (dependency): "
                    f"{', '.join(result.resubmit_only)}"
                )

    def _log(self, text: str, level: LogLevel = LogLevel.INFO, source: str = "") -> None:
        self.logs.append(text, level, source)

    def _refresh_error_badge(self) -> None:
        errors = sum(1 for r in self.logs.records() if r.level >= LogLevel.ERROR)
        self.nav.set_badge(LOGS, str(errors) if errors else "")
        self.strip.set_error_count(errors)

    def _browse_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select plugins folder")
        if folder:
            self.settings.plugins_root = folder
            self.settings_page.refresh()
            self.rescan()

    def _reset_history(self) -> None:
        self.store.clear()
        self.store.save()
        self._log("Build history reset — everything reads as changed.", LogLevel.WARNING)
        self.rescan()

    # --------------------------------------------------------------- listings
    def _configure_listings(self, *_args) -> None:
        """Point the listing layer at its folder, creating it if need be.

        There is always a folder — Documents by default — so the page never
        opens on a dead end. Creation failing is the only case the page has to
        report, and it says which path it could not use.
        """
        folder = self.settings.effective_listings_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._log(f"Cannot use the listings folder {folder}: {exc}", LogLevel.WARNING)
            self.listings_page.set_listings_dir(None)
            return
        self.listings.configure(
            str(folder),
            self.settings.effective_output_dir(),
            self.settings.listing_faq_review,
            self.settings.listing_changelog_review,
        )
        self.listings.prompt_template = self.settings.listing_prompt_template
        self.listings_page.set_listings_dir(folder)

    def _check_listings(self, scope: str) -> None:
        rows = self.listings_page.rows_for_scope(scope)
        plugins = [r.plugin for r in rows] if rows else self.model.plugins()
        if not plugins:
            self._log("Nothing to check — scan for plugins first.", LogLevel.WARNING)
            return
        self.listings.check(
            plugins,
            self._selected_engine(),
            [platform_uat_name(p) for p in self.platform_info
             if p in self.settings.platforms],
        )

    def _recheck_listings(self) -> None:
        """After an edit, re-run over whatever is on screen."""
        self._check_listings(self.listings_page.scope.currentText())

    def _on_listing_scan(self, scan) -> None:
        self._listing_scan = scan
        if scan.error:
            self.listings_page.set_listings_dir(None)
            return
        self.listings_page.set_scan(scan)

    def _build_listings(self) -> None:
        if self._listing_scan is None:
            self._log("Run Check first.", LogLevel.WARNING)
            return
        written = self.listings.build(self._listing_scan)
        if written and self.settings.auto_open_output:
            self._open_folder(written[0])

    def _accept_listings(self, force: bool) -> None:
        rows = self.listings_page.selected_rows() or (
            list(self._listing_scan.publishable) if self._listing_scan else []
        )
        rows = [r for r in rows if r.publishable]
        if not rows:
            self._log("Select a listing to accept.", LogLevel.WARNING)
            return

        blocked = [r for r in rows if r.blocked]
        if blocked and not force:
            names = ", ".join(r.plugin_id for r in blocked[:5])
            box = QMessageBox(self)
            box.setWindowTitle("Accept with errors?")
            box.setText(
                f"{len(blocked)} listing(s) still have errors: {names}.\n\n"
                f"A snapshot of copy Fab would reject becomes the baseline every "
                f"later diff is measured against."
            )
            fix = box.addButton("Fix them first", QMessageBox.RejectRole)
            box.addButton("Accept anyway", QMessageBox.DestructiveRole)
            box.setDefaultButton(fix)  # never default to the destructive path
            box.exec()
            if box.clickedButton() is fix:
                return

        result = self.listings.accept(rows, force=True)
        self._log(
            f"Accepted {len(result.accepted)} listing(s), "
            f"{result.fields_recorded} field(s) recorded."
        )
        self._recheck_listings()

    def _selected_listing_row(self):
        rows = self.listings_page.selected_rows()
        return rows[0] if rows else None

    def _draft_listing(self, _plugin_id: str) -> None:
        row = self._selected_listing_row()
        if row is None:
            return
        error = self.listings.start_draft(row, self.settings.claude_path)
        if error:
            self._log(error, LogLevel.WARNING)
            self.listings_page.copy_prompt(self.listings.draft_prompt_for(row))

    def _improve_listing(self, _plugin_id: str, instruction: str) -> None:
        row = self._selected_listing_row()
        if row is None:
            return
        error = self.listings.start_draft(
            row, self.settings.claude_path, instruction=instruction
        )
        if error:
            self._log(error, LogLevel.WARNING)

    def _copy_listing_prompt(self, _plugin_id: str) -> None:
        row = self._selected_listing_row()
        if row is not None:
            self.listings_page.copy_prompt(self.listings.draft_prompt_for(row))

    def _on_draft_finished(self, plugin_id: str, output: str, error: str) -> None:
        row = self._selected_listing_row()
        message = error
        if not error and row is not None and row.plugin_id == plugin_id:
            message = (
                self.listings.apply_draft(
                    row, output, overwrite=self.listings.draft_overwrites
                )
                or "Draft applied."
            )
            if message == "Draft applied.":
                self._recheck_listings()
            else:
                self._log(message, LogLevel.WARNING)
        self.listings_page.end_draft(message)

    def _open_bundle(self, plugin_id: str) -> None:
        from ..listing.render import bundle_dir

        folder = bundle_dir(self.settings.effective_output_dir(), plugin_id)
        if folder.is_dir():
            self._open_folder(folder)
        else:
            self._log(
                f"No bundle for {plugin_id} yet — run Build bundles.",
                LogLevel.WARNING,
            )

    def _open_folder(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ------------------------------------------------------------------ build
    def _jobs(self, names: set[str]) -> list[PluginInfo]:
        """Checked plugins plus their transitive suite deps, in build order."""
        plugins = self.model.plugins()
        by_name = {p.name: p for p in plugins}
        jobs = [by_name[n] for n in transitive_dependencies(plugins, names)]
        jobs.sort(key=lambda p: p.order)
        return jobs

    def _refresh_build_page(self) -> None:
        checked = set(self.model.checked_names())
        jobs = self._jobs(checked)
        checks = preflight(
            self._selected_engine(),
            self.settings.platforms,
            checked,
            jobs,
            self._issues,
            self.settings.effective_output_dir(),
            self.model.plugins(),
            self.settings.effective_work_dir(),
        )
        self.build_page.refresh(jobs, checked, checks)

    def _platform_summary(self) -> str:
        return "+".join(
            platform_uat_name(p)
            for p in self.platform_info
            if p in self.settings.platforms
        )

    def _start_build(self, dry_run: bool) -> None:
        if self.build.is_running:
            return
        checked = set(self.model.checked_names())
        jobs = self._jobs(checked)
        checks = preflight(
            self._selected_engine(),
            self.settings.platforms,
            checked,
            jobs,
            self._issues,
            self.settings.effective_output_dir(),
            self.model.plugins(),
            self.settings.effective_work_dir(),
        )
        if not checks.ok:
            # The page already shows these; the button is disabled too.
            self._show_page(BUILD)
            return

        auto = [p.name for p in jobs if p.name not in checked]
        if auto:
            self._log(f"Auto-including dependencies: {', '.join(auto)}")

        output_dir = self.settings.effective_output_dir()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Cannot write output", str(exc))
            return

        self._save_settings()
        self._dry_run = dry_run
        self.build.start(
            BuildRequest(
                engine=self._selected_engine(),
                jobs=jobs,
                platforms=self.settings.platforms,
                work_root=self.settings.effective_work_dir(),
                ship_patterns=self.settings.ship_patterns,
                output_dir=output_dir,
                hashes=self._current_hashes,
                dry_run=dry_run,
                all_plugins=self.model.plugins(),
            )
        )

    def _on_build_started(self, total: int) -> None:
        self.build_page.set_building(True)
        self.strip.start_build(
            total, self._platform_summary(), getattr(self, "_dry_run", False)
        )

    def _on_build_finished(self, results, cancelled: bool) -> None:
        self.build_page.set_building(False)
        ok = sum(1 for r in results if r.success)
        zips = [r.zip_path for r in results if r.success and r.zip_path]
        self.strip.set_finished(ok, len(results), cancelled, bool(zips))
        if zips and not cancelled and self.settings.auto_open_output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(zips[-1].parent)))

    def _cancel_build(self) -> None:
        self.strip.set_stopping()
        self.build.cancel()

    def _open_output(self) -> None:
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.settings.effective_output_dir()))
        )

    # ------------------------------------------------------------- lifecycle
    def _restore_geometry(self) -> None:
        saved = self.settings.window_geometry
        if saved:
            self.restoreGeometry(saved)

    def _save_settings(self) -> None:
        self.settings.set_selection_ordered(self.model.checked_names())
        self.settings.window_geometry = bytes(self.saveGeometry())
        self.settings.save()

    def closeEvent(self, event) -> None:
        # Destroying a running QThread aborts the process, so the build has to
        # stop before the window can go away.
        if self.build.is_running and not self.build.shutdown():
            event.ignore()
            return
        if not self.listings.shutdown():
            event.ignore()
            return
        self._save_settings()
        super().closeEvent(event)
