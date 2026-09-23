"""Settings: everything that is configured once, not chosen every run."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...config import config_path, data_dir, state_path
from ...engines import engine_from_root
from ...listing import prompt as prompt_mod
from ...shipfilter import DEFAULT_PATTERNS
from ..app_settings import (
    AppSettings,
    default_listings_dir,
    default_output_dir,
    default_work_dir,
)
from ..cards import card as _card
from ..theme import color, mono_font


class SettingsPage(QWidget):
    plugins_root_changed = Signal()
    build_history_reset = Signal()
    listings_dir_changed = Signal()
    engine_roots_changed = Signal()

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.settings = settings

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(14)
        layout.addWidget(self._paths())
        layout.addWidget(self._listings())
        layout.addWidget(self._engines())
        layout.addWidget(self._packaging())
        layout.addWidget(self._defaults())
        layout.addWidget(self._data())
        layout.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll)

    # ----------------------------------------------------------------- paths
    def _paths(self) -> QFrame:
        card, layout = _card("Paths")

        self.root_edit = QLineEdit(self.settings.plugins_root)
        self.root_edit.setPlaceholderText("Folder containing your plugin directories")
        self.root_edit.editingFinished.connect(self._commit_root)
        layout.addLayout(
            self._path_row("Plugins folder", self.root_edit, self._browse_root)
        )

        self.output_edit = QLineEdit(self.settings.output_dir)
        self.output_edit.setPlaceholderText(str(default_output_dir()))
        self.output_edit.editingFinished.connect(self._commit_output)
        layout.addLayout(
            self._path_row("Output folder", self.output_edit, self._browse_output)
        )

        self.work_edit = QLineEdit(self.settings.work_dir)
        self.work_edit.setPlaceholderText(str(default_work_dir()))
        self.work_edit.editingFinished.connect(self._commit_work)
        layout.addLayout(
            self._path_row("Work folder", self.work_edit, self._browse_work)
        )
        note = QLabel(
            "Staging for RunUAT output. Cleared after every plugin. Unreal fails "
            "on paths of 260+ characters, so keep it short (e.g. C:\\UEWork)."
        )
        note.setProperty("role", "hint")
        layout.addWidget(note)
        return card

    # -------------------------------------------------------------- listings
    def _listings(self) -> QFrame:
        card, layout = _card(
            "Fab listings",
            "Where authored listing copy, media and submission snapshots live. "
            "Defaults to your Documents folder; point it at a repository you "
            "control if you want the snapshots version-controlled — they are "
            "the only record of what you actually submitted.",
        )

        self.listings_edit = QLineEdit(self.settings.listings_dir)
        self.listings_edit.setPlaceholderText(str(default_listings_dir()))
        self.listings_edit.editingFinished.connect(self._commit_listings)
        layout.addLayout(
            self._path_row(
                "Listings folder", self.listings_edit, self._browse_listings
            )
        )

        self.claude_edit = QLineEdit(self.settings.claude_path)
        self.claude_edit.editingFinished.connect(self._commit_claude)
        layout.addLayout(
            self._path_row("Claude CLI", self.claude_edit, self._browse_claude)
        )
        self.claude_status = QLabel("")
        self.claude_status.setProperty("role", "hint")
        layout.addWidget(self.claude_status)
        self._refresh_claude_status()

        note = QLabel(
            "Fab documents neither FAQ nor changelog edits, so both are treated "
            "as review-triggering. Turn one off only once you have watched Fab "
            "apply that edit without a re-review."
        )
        note.setProperty("role", "hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.faq_review = QCheckBox("A FAQ edit re-enters Fab review")
        self.faq_review.setChecked(self.settings.listing_faq_review)
        self.faq_review.toggled.connect(
            lambda v: setattr(self.settings, "listing_faq_review", v)
        )
        layout.addWidget(self.faq_review)

        self.changelog_review = QCheckBox("A changelog edit re-enters Fab review")
        self.changelog_review.setChecked(self.settings.listing_changelog_review)
        self.changelog_review.toggled.connect(
            lambda v: setattr(self.settings, "listing_changelog_review", v)
        )
        layout.addWidget(self.changelog_review)

        layout.addWidget(self._prompt_editor())
        return card

    def _prompt_editor(self) -> QWidget:
        """The drafting prompt, collapsed by default.

        Good copy for a gameplay framework is not good copy for an editor tool,
        and only the publisher knows which they are shipping - so the prompt is
        theirs to edit. It is long, though, and almost never changed, so it
        stays folded away rather than dominating the page.
        """
        holder = QWidget()
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(6)

        self.prompt_toggle = QToolButton()
        self.prompt_toggle.setText("Drafting prompt")
        self.prompt_toggle.setCheckable(True)
        self.prompt_toggle.setChecked(False)
        self.prompt_toggle.setAutoRaise(True)
        self.prompt_toggle.setArrowType(Qt.RightArrow)
        self.prompt_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.prompt_toggle.setCursor(Qt.PointingHandCursor)
        self.prompt_toggle.toggled.connect(self._toggle_prompt)
        outer.addWidget(self.prompt_toggle, 0, Qt.AlignLeft)

        self.prompt_body = QWidget()
        body = QVBoxLayout(self.prompt_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)

        hint = QLabel(
            "Sent to Claude when you press Ask Claude. These placeholders are "
            "filled in: "
            + ", ".join("{" + name + "}" for name in prompt_mod.PLACEHOLDERS)
            + ". {requirements} is generated from Fab's published rules, so "
            "removing it means the drafter no longer knows what the validator "
            "will check."
        )
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        body.addWidget(hint)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setFont(mono_font(8.5))
        self.prompt_edit.setPlainText(
            self.settings.listing_prompt_template or prompt_mod.DEFAULT_TEMPLATE
        )
        self.prompt_edit.setMinimumHeight(260)
        body.addWidget(self.prompt_edit)

        row = QHBoxLayout()
        save = QPushButton("Save prompt")
        save.clicked.connect(self._commit_prompt)
        reset = QPushButton("Reset to default")
        reset.setProperty("variant", "ghost")
        reset.clicked.connect(self._reset_prompt)
        row.addWidget(save)
        row.addWidget(reset)
        row.addStretch(1)
        body.addLayout(row)

        self.prompt_body.setVisible(False)
        outer.addWidget(self.prompt_body)
        return holder

    def _toggle_prompt(self, shown: bool) -> None:
        self.prompt_toggle.setArrowType(Qt.DownArrow if shown else Qt.RightArrow)
        self.prompt_body.setVisible(shown)

    def _commit_prompt(self) -> None:
        text = self.prompt_edit.toPlainText().strip()
        # Storing the default verbatim would freeze it: a later improvement to
        # the built-in prompt would never reach anyone who had opened this box.
        self.settings.listing_prompt_template = (
            "" if text == prompt_mod.DEFAULT_TEMPLATE.strip() else text
        )
        self.settings.save()

    def _reset_prompt(self) -> None:
        self.prompt_edit.setPlainText(prompt_mod.DEFAULT_TEMPLATE)
        self.settings.listing_prompt_template = ""
        self.settings.save()

    def _refresh_claude_status(self) -> None:
        from ..draft_worker import resolve_cli

        found = resolve_cli(self.settings.claude_path)
        self.claude_status.setText(
            f"Found: {found}"
            if found
            else "Not found. Ask Claude falls back to copying the prompt."
        )
        self.claude_status.setProperty("state", "" if found else "warn")
        self.claude_status.style().unpolish(self.claude_status)
        self.claude_status.style().polish(self.claude_status)

    def _commit_listings(self) -> None:
        text = self.listings_edit.text().strip()
        if text != self.settings.listings_dir:
            self.settings.listings_dir = text
            self.listings_dir_changed.emit()

    def _commit_claude(self) -> None:
        self.settings.claude_path = self.claude_edit.text().strip()
        self._refresh_claude_status()

    def _browse_listings(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select listings folder")
        if folder:
            self.listings_edit.setText(folder)
            self._commit_listings()

    def _browse_claude(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select the Claude CLI")
        if path:
            self.claude_edit.setText(path)
            self._commit_claude()

    def _path_row(
        self, label: str, edit: QLineEdit, handler, browse_label: str = "Browse…"
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        caption = QLabel(label)
        caption.setMinimumWidth(110)
        caption.setProperty("role", "caption")
        row.addWidget(caption)
        row.addWidget(edit, 1)
        button = QPushButton(browse_label)
        button.clicked.connect(handler)
        row.addWidget(button)
        return row

    def _commit_root(self) -> None:
        text = self.root_edit.text().strip()
        if text != self.settings.plugins_root:
            self.settings.plugins_root = text
            self.plugins_root_changed.emit()

    def _commit_output(self) -> None:
        self.settings.output_dir = self.output_edit.text().strip()

    def _commit_work(self) -> None:
        self.settings.work_dir = self.work_edit.text().strip()

    def _browse_work(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select work folder")
        if folder:
            self.work_edit.setText(folder)
            self._commit_work()

    def _browse_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select plugins folder")
        if folder:
            self.root_edit.setText(folder)
            self._commit_root()

    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select output folder")
        if folder:
            self.output_edit.setText(folder)
            self._commit_output()

    # --------------------------------------------------------------- engines
    def _engines(self) -> QFrame:
        card, layout = _card(
            "Engine installations",
            "Detected from the Epic Launcher's registry entries and manifest — "
            "nothing is searched for on disk. Add a folder by hand for a portable "
            "copy, an unregistered source build, or an install made under another "
            "Windows account.",
        )

        self.detected_label = QLabel("")
        self.detected_label.setFont(mono_font(8.5))
        self.detected_label.setProperty("role", "hint")
        self.detected_label.setWordWrap(True)
        layout.addWidget(self.detected_label)

        self.engine_list = QListWidget()
        self.engine_list.setFont(mono_font(8.5))
        self.engine_list.setMaximumHeight(110)
        self.engine_list.itemSelectionChanged.connect(self._sync_engine_buttons)
        layout.addWidget(self.engine_list)

        row = QHBoxLayout()
        add = QPushButton("Add engine folder…")
        add.clicked.connect(self._add_engine_root)
        row.addWidget(add)

        self.remove_engine_btn = QPushButton("Remove")
        self.remove_engine_btn.setProperty("variant", "danger")
        self.remove_engine_btn.setEnabled(False)
        self.remove_engine_btn.clicked.connect(self._remove_engine_root)
        row.addWidget(self.remove_engine_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self._refresh_engine_list()
        return card

    def _refresh_engine_list(self) -> None:
        self.engine_list.clear()
        for path in self.settings.custom_engine_roots:
            engine = engine_from_root(path)
            if engine is None:
                item = QListWidgetItem(f"⚠  {path}   — no RunUAT.bat here any more")
                item.setForeground(QColor(color("danger")))
            else:
                tag = " (source)" if engine.is_source_build else ""
                item = QListWidgetItem(f"UE_{engine.version}{tag}   {path}")
            item.setData(Qt.UserRole, path)
            self.engine_list.addItem(item)
        if not self.settings.custom_engine_roots:
            placeholder = QListWidgetItem("No manually added engines.")
            placeholder.setForeground(QColor(color("text_muted")))
            placeholder.setFlags(Qt.NoItemFlags)
            self.engine_list.addItem(placeholder)
        self._sync_engine_buttons()

    def set_detected(self, engines) -> None:
        """Show what automatic detection found, so a gap is obvious."""
        if engines:
            self.detected_label.setText(
                "Detected automatically:   "
                + "    ".join(f"{e.label} → {e.root}" for e in engines)
            )
        else:
            self.detected_label.setText(
                "Detected automatically:   none — add a folder below."
            )

    def _sync_engine_buttons(self) -> None:
        item = self.engine_list.currentItem()
        self.remove_engine_btn.setEnabled(
            item is not None and item.data(Qt.UserRole) is not None
        )

    def _add_engine_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select an Unreal Engine installation folder"
        )
        if not folder:
            return
        if engine_from_root(folder) is None:
            QMessageBox.warning(
                self,
                "Not an engine folder",
                f"{folder}\n\nNo Engine\\Build\\BatchFiles\\RunUAT.bat was found here.\n"
                "Pick the engine root — the folder that contains Engine\\.",
            )
            return
        if not self.settings.add_engine_root(folder):
            QMessageBox.information(
                self, "Already added", "That engine folder is already in the list."
            )
            return
        self._refresh_engine_list()
        self.engine_roots_changed.emit()

    def _remove_engine_root(self) -> None:
        item = self.engine_list.currentItem()
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if path is None:
            return
        self.settings.remove_engine_root(path)
        self._refresh_engine_list()
        self.engine_roots_changed.emit()

    # ------------------------------------------------------------- packaging
    def _packaging(self) -> QFrame:
        card, layout = _card(
            "Packaging",
            "Extra paths stripped from the submission zip, one per line. "
            "Blank lines and # comments are ignored.",
        )

        self.ship_edit = QPlainTextEdit()
        self.ship_edit.setPlaceholderText("*.md\nDocs/\n*.pdb")
        self.ship_edit.setFont(mono_font())
        self.ship_edit.setFixedHeight(120)
        self.ship_edit.setPlainText("\n".join(self.settings.ship_patterns))
        self.ship_edit.textChanged.connect(self._commit_patterns)
        layout.addWidget(self.ship_edit)

        # Users had no way to know why Binaries/ vanishes from their zip.
        always = QLabel("Always excluded:  " + "   ".join(DEFAULT_PATTERNS))
        always.setFont(mono_font(8.5))
        always.setProperty("role", "hint")
        always.setWordWrap(True)
        layout.addWidget(always)
        return card

    def _commit_patterns(self) -> None:
        self.settings.ship_patterns = self.ship_edit.toPlainText().splitlines()

    # -------------------------------------------------------------- defaults
    def _defaults(self) -> QFrame:
        card, layout = _card("Defaults")

        self.auto_open = QCheckBox("Open the output folder when a build finishes")
        self.auto_open.setChecked(self.settings.auto_open_output)
        self.auto_open.toggled.connect(
            lambda v: setattr(self.settings, "auto_open_output", v)
        )
        layout.addWidget(self.auto_open)

        self.auto_select = QCheckBox("Select everything that needs rebuilding after a scan")
        self.auto_select.setChecked(self.settings.auto_select_changed)
        self.auto_select.toggled.connect(
            lambda v: setattr(self.settings, "auto_select_changed", v)
        )
        layout.addWidget(self.auto_select)
        return card

    # ------------------------------------------------------------------ data
    def _data(self) -> QFrame:
        card, layout = _card(
            "Data", "Settings and build history live beside the app, not in the registry."
        )

        for label, path in (("Settings", config_path()), ("Build history", state_path())):
            row = QHBoxLayout()
            caption = QLabel(label)
            caption.setMinimumWidth(110)
            caption.setProperty("role", "caption")
            value = QLabel(str(path))
            value.setFont(mono_font(8.5))
            value.setProperty("role", "hint")
            value.setWordWrap(True)
            row.addWidget(caption)
            row.addWidget(value, 1)
            layout.addLayout(row)

        buttons = QHBoxLayout()
        open_btn = QPushButton("Open folder")
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))
        )
        buttons.addWidget(open_btn)

        reset_btn = QPushButton("Reset build history")
        reset_btn.setProperty("variant", "danger")
        reset_btn.clicked.connect(self._reset_history)
        buttons.addWidget(reset_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return card

    def _reset_history(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Reset build history?",
            "Every plugin will read as changed until it is built again.\n"
            "Nothing on disk is deleted.",
        )
        if confirm == QMessageBox.Yes:
            self.build_history_reset.emit()

    # ----------------------------------------------------------------- sync
    def refresh(self) -> None:
        """Pull values back from settings after an external change."""
        if self.root_edit.text().strip() != self.settings.plugins_root:
            self.root_edit.setText(self.settings.plugins_root)
        if self.output_edit.text().strip() != self.settings.output_dir:
            self.output_edit.setText(self.settings.output_dir)
        if self.work_edit.text().strip() != self.settings.work_dir:
            self.work_edit.setText(self.settings.work_dir)
