"""Build page: the per-run gates, what will actually run, and why it can't."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...builder import submission_zip_name
from ...models import (
    ALL_PLATFORMS,
    EngineInfo,
    Platform,
    PluginInfo,
    platform_uat_name,
)
from ...platforms import PlatformAvailability, available_mask, setup_guide
from ..app_settings import AppSettings
from ..theme import color, icons, mono_font


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 13, 16, 14)
    layout.setSpacing(9)
    label = QLabel(title)
    label.setObjectName("cardTitle")
    layout.addWidget(label)
    return frame, layout


class BuildPage(QWidget):
    build_requested = Signal(bool)  # dry_run
    cancel_requested = Signal()
    engine_changed = Signal(str)
    platforms_changed = Signal()
    platforms_unavailable = Signal(list)  # names dropped by an engine change

    def __init__(
        self,
        settings: AppSettings,
        engines: list[EngineInfo],
        platform_info: dict[Platform, PlatformAvailability],
        parent=None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.engines = engines
        self.platform_info = platform_info

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        layout.addWidget(self._run_config())
        layout.addWidget(self._queue())
        layout.addWidget(self._output())
        layout.addWidget(self._preflight())
        layout.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        outer.addWidget(self._actions())

    # ------------------------------------------------------------ run config
    def _run_config(self) -> QFrame:
        card, layout = _card("Run configuration")

        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("Engine"))
        self.engine_combo = QComboBox()
        self.engine_combo.setMinimumWidth(220)
        # Created before _fill_engines, which syncs it.
        self.engine_hint = QLabel("")
        self.engine_hint.setProperty("role", "hint")
        self.engine_hint.setFont(mono_font(8.5))

        self._fill_engines()
        self.engine_combo.currentIndexChanged.connect(
            lambda _: self.engine_changed.emit(self.engine_combo.currentData() or "")
        )
        engine_row.addWidget(self.engine_combo)
        engine_row.addWidget(self.engine_hint, 1)
        layout.addLayout(engine_row)

        header = QHBoxLayout()
        platforms_label = QLabel("Target platforms")
        platforms_label.setProperty("role", "caption")
        header.addWidget(platforms_label)
        header.addStretch(1)
        select_available = QPushButton("Select all available")
        select_available.setProperty("variant", "ghost")
        select_available.clicked.connect(self._select_available)
        header.addWidget(select_available)
        layout.addLayout(header)

        self.platform_checks: dict[Platform, QCheckBox] = {}
        self._platform_warn: dict[Platform, QPushButton] = {}
        self._platform_reason: dict[Platform, QLabel] = {}
        for platform in ALL_PLATFORMS:
            row = QHBoxLayout()
            row.setSpacing(8)
            box = QCheckBox(platform_uat_name(platform))
            box.setMinimumWidth(90)
            box.toggled.connect(self.commit_platforms)
            self.platform_checks[platform] = box
            row.addWidget(box)

            warn = self._help_button(platform)
            self._platform_warn[platform] = warn
            row.addWidget(warn)

            # The reason used to live in a tooltip, i.e. nowhere.
            reason = QLabel("")
            reason.setProperty("role", "hint")
            reason.setWordWrap(True)
            self._platform_reason[platform] = reason
            row.addWidget(reason, 1)
            layout.addLayout(row)

        self._apply_platform_info(first_run=True)
        return card

    def set_platform_info(self, info: dict[Platform, PlatformAvailability]) -> None:
        """Re-evaluate after an engine change.

        Availability is engine-dependent: the same Linux toolchain can satisfy
        one engine and be rejected by the next.
        """
        self.platform_info = info
        self._apply_platform_info()

    def _apply_platform_info(self, first_run: bool = False) -> None:
        saved = self.settings.platforms
        dropped: list[str] = []
        for platform, box in self.platform_checks.items():
            info = self.platform_info[platform]
            blocked = box.blockSignals(True)
            box.setEnabled(info.available)
            if first_run:
                box.setChecked(info.available and platform in saved)
            elif not info.available and box.isChecked():
                # Silently leaving it ticked would fail minutes into the build.
                box.setChecked(False)
                dropped.append(platform_uat_name(platform))
            box.blockSignals(blocked)

            self._platform_warn[platform].setVisible(not info.available)
            self._refresh_help_tooltip(platform)
            self._platform_reason[platform].setText(info.reason)

        self.commit_platforms()
        if dropped:
            self.platforms_unavailable.emit(dropped)

    def _help_button(self, platform: Platform) -> QPushButton:
        """The warning symbol doubles as the way in: hover for the summary,
        click for the full steps."""
        button = QPushButton("⚠")
        button.setProperty("variant", "icon")
        button.setFixedSize(26, 24)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda: self._show_setup_guide(platform))
        return button

    def _refresh_help_tooltip(self, platform: Platform) -> None:
        """The summary is engine-specific for version mismatches."""
        engine = self._engine()
        guide = setup_guide(platform, engine.root if engine else None)
        self._platform_warn[platform].setToolTip(
            f"{guide.summary}\n\nClick for setup steps." if guide else ""
        )

    def _show_setup_guide(self, platform: Platform) -> None:
        engine = self._engine()
        guide = setup_guide(platform, engine.root if engine else None)
        if guide is None:
            return

        steps = "".join(
            f"<li style='margin-bottom:7px;'>{html.escape(step)}</li>"
            for step in guide.steps
        )
        body = [f"<ol style='margin-left:-18px;'>{steps}</ol>"]
        if guide.env_vars:
            names = ", ".join(guide.env_vars)
            body.append(
                f"<p style='color:{color('text_muted')};'>Detected via: "
                f"<code>{html.escape(names)}</code></p>"
            )

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information if guide.possible else QMessageBox.Warning)
        box.setWindowTitle(guide.title)
        box.setTextFormat(Qt.RichText)
        box.setText(f"<b>{html.escape(guide.summary)}</b>")
        box.setInformativeText("".join(body))
        docs = (
            box.addButton("Open Epic's docs", QMessageBox.ActionRole)
            if guide.doc_url
            else None
        )
        box.addButton(QMessageBox.Close)
        box.exec()
        if docs is not None and box.clickedButton() is docs:
            QDesktopServices.openUrl(QUrl(guide.doc_url))

    def _fill_engines(self) -> None:
        """Populate the combo from self.engines, keeping the saved selection."""
        blocked = self.engine_combo.blockSignals(True)
        self.engine_combo.clear()
        for engine in self.engines:
            self.engine_combo.addItem(engine.label, engine.identifier)
            # Two installs can share a version, so the path is the disambiguator.
            self.engine_combo.setItemData(
                self.engine_combo.count() - 1, str(engine.root), Qt.ToolTipRole
            )
        if not self.engines:
            self.engine_combo.addItem("No engine detected", "")
        saved = self.engine_combo.findData(self.settings.engine_id)
        if saved >= 0:
            self.engine_combo.setCurrentIndex(saved)
        self.engine_combo.blockSignals(blocked)
        self._sync_engine_hint()

    def set_engines(self, engines: list[EngineInfo]) -> None:
        """Swap in a new engine list after the user edited the manual roots.

        Deliberately silent: the caller re-syncs settings and rescans, so
        emitting here would scan twice.
        """
        self.engines = engines
        self._fill_engines()

    def _sync_engine_hint(self) -> None:
        engine = self._engine()
        self.engine_hint.setText(str(engine.root) if engine else "")

    def _select_available(self) -> None:
        engine = self._engine()
        mask = available_mask(engine.root if engine else None)
        for platform, box in self.platform_checks.items():
            if box.isEnabled():
                box.setChecked(platform in mask)

    def commit_platforms(self) -> None:
        mask = Platform.NONE
        for platform, box in self.platform_checks.items():
            if box.isChecked():
                mask |= platform
        self.settings.platforms = mask
        self.platforms_changed.emit()

    # ---------------------------------------------------------------- queue
    def _queue(self) -> QFrame:
        card, layout = _card("Build queue")
        self.queue_hint = QLabel("")
        self.queue_hint.setProperty("role", "caption")
        layout.addWidget(self.queue_hint)

        self.queue_list = QListWidget()
        self.queue_list.setFont(mono_font())
        self.queue_list.setMaximumHeight(190)
        self.queue_list.setSelectionMode(QListWidget.NoSelection)
        layout.addWidget(self.queue_list)
        return card

    # --------------------------------------------------------------- output
    def _output(self) -> QFrame:
        card, layout = _card("Output")
        row = QHBoxLayout()
        self.output_label = QLabel("")
        self.output_label.setFont(mono_font(8.5))
        self.output_label.setProperty("role", "caption")
        self.output_label.setWordWrap(True)
        row.addWidget(self.output_label, 1)
        open_btn = QPushButton("Open")
        open_btn.setProperty("variant", "ghost")
        open_btn.clicked.connect(self._open_output)
        row.addWidget(open_btn)
        layout.addLayout(row)

        self.zips_label = QLabel("")
        self.zips_label.setFont(mono_font(8.5))
        self.zips_label.setProperty("role", "hint")
        self.zips_label.setWordWrap(True)
        layout.addWidget(self.zips_label)

        self.patterns_label = QLabel("")
        self.patterns_label.setProperty("role", "hint")
        layout.addWidget(self.patterns_label)
        return card

    def _open_output(self) -> None:
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.settings.effective_output_dir()))
        )

    # ------------------------------------------------------------- preflight
    def _preflight(self) -> QFrame:
        card, layout = _card("Preflight")
        self.preflight_box = QVBoxLayout()
        self.preflight_box.setSpacing(4)
        layout.addLayout(self.preflight_box)
        return card

    def _actions(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(18, 8, 18, 12)
        row.setSpacing(8)
        row.addStretch(1)

        self.dry_btn = QPushButton("Dry run")
        self.dry_btn.clicked.connect(lambda: self.build_requested.emit(True))
        row.addWidget(self.dry_btn)

        self.build_btn = QPushButton("Build selected")
        self.build_btn.setProperty("variant", "primary")
        self.build_btn.setDefault(True)
        self.build_btn.clicked.connect(lambda: self.build_requested.emit(False))
        row.addWidget(self.build_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setIcon(icons.icon("cancel", "danger"))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_requested)
        row.addWidget(self.cancel_btn)
        return holder

    # ------------------------------------------------------------- refreshing
    def refresh(self, jobs: list[PluginInfo], checked: set[str], checks) -> None:
        """Recompute the queue, output preview and preflight for the current state."""
        engine = self._engine()

        self.queue_list.clear()
        auto = 0
        for position, job in enumerate(jobs, start=1):
            suffix = "" if job.name in checked else "   (auto — dependency)"
            if suffix:
                auto += 1
            item = QListWidgetItem(f"{position:02d}   {job.name}{suffix}")
            if suffix:
                item.setForeground(QColor(color("text_muted")))
            self.queue_list.addItem(item)

        if not jobs:
            self.queue_hint.setText("Nothing selected yet.")
        else:
            extra = f", {auto} pulled in as dependencies" if auto else ""
            self.queue_hint.setText(
                f"{len(jobs)} plugin(s) in build order{extra}."
            )

        # Path("") is Path("."), so test the raw settings, not the Path.
        configured = self.settings.output_dir or self.settings.plugins_root
        self.output_label.setText(
            str(self.settings.effective_output_dir()) if configured else "—"
        )
        if jobs and engine is not None:
            names = [submission_zip_name(job, engine) for job in jobs]
            shown = "\n".join(names[:6])
            if len(names) > 6:
                shown += f"\n… and {len(names) - 6} more"
            self.zips_label.setText(shown)
        else:
            self.zips_label.setText("")
        count = len(self.settings.ship_patterns)
        self.patterns_label.setText(
            f"{count} extra exclude pattern(s) — edit in Settings › Packaging"
        )

        self._sync_engine_hint()
        self._render_preflight(checks)
        self.build_btn.setEnabled(checks.ok)
        self.dry_btn.setEnabled(checks.ok)

    def _render_preflight(self, checks) -> None:
        while self.preflight_box.count():
            item = self.preflight_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if checks.ok and not checks.warnings:
            self._preflight_line("✓  Ready to build", "success")
            return
        for issue in checks.blockers:
            self._preflight_line(f"✕  {issue.message}", "danger")
        for issue in checks.warnings:
            token = "danger" if issue.level == "error" else "warning"
            self._preflight_line(f"⚠  {issue.message}", token)

    def _preflight_line(self, text: str, token: str) -> None:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {color(token)};")
        self.preflight_box.addWidget(label)

    def set_building(self, building: bool) -> None:
        self.build_btn.setEnabled(not building)
        self.dry_btn.setEnabled(not building)
        self.cancel_btn.setEnabled(building)
        self.engine_combo.setEnabled(not building)
        for platform, box in self.platform_checks.items():
            box.setEnabled(not building and self.platform_info[platform].available)

    def _engine(self) -> EngineInfo | None:
        ident = self.engine_combo.currentData()
        for engine in self.engines:
            if engine.identifier == ident:
                return engine
        return None
