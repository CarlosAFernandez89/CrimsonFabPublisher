"""The per-listing detail panel.

Fields, media, audit, diff, provenance and the raw file.

One rule holds the whole thing together: **the file is the source of truth, not
the widget tree.** Every tab writes to `<listings_dir>/<Id>.json` and re-reads
from disk when shown, so there is no two-way binding to fall out of step and no
reconciliation bug to chase. It is the same discipline as `AppSettings` being
the model and no widget ever being one.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..listing import fabrules, markup, schema, source
from ..listing.service import ListingRow
from .cards import card
from .diff_view import DiffView, IssueList
from .theme import mono_font, repolish


class ListingEditor(QTabWidget):
    saved = Signal(str)  # plugin id
    draft_requested = Signal(str)
    improve_requested = Signal(str, str)  # plugin id, instruction
    copy_prompt_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row: ListingRow | None = None
        self._authored: dict = {}
        self._listings_dir: Path | None = None
        self._mono = mono_font()

        self.addTab(self._fields_tab(), "Fields")
        self.addTab(self._media_tab(), "Media")
        self.addTab(self._audit_tab(), "Audit")
        self.addTab(self._diff_tab(), "Diff")
        self.addTab(self._provenance_tab(), "Provenance")
        self.addTab(self._json_tab(), "Raw JSON")
        self.currentChanged.connect(lambda _: self._reload_current())
        self.setEnabled(False)

    # -------------------------------------------------------------- fields
    def _fields_tab(self) -> QWidget:
        page = QScrollArea()
        page.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(12)

        frame, box = card("Identity")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.title_edit = QLineEdit()
        self.title_count = QLabel("0 / 80")
        self.title_count.setProperty("role", "hint")
        self.title_edit.textChanged.connect(self._update_title_count)
        title_row = QHBoxLayout()
        title_row.addWidget(self.title_edit, 1)
        title_row.addWidget(self.title_count)
        form.addRow("Title", self._wrap(title_row))

        self.product_type = QComboBox()
        self.product_type.addItems(schema.PRODUCT_TYPES)
        self.product_type.setToolTip(
            "Fab's Product type field. A code plugin is Tools & Plugins."
        )
        form.addRow("Product type", self.product_type)

        self.category = QComboBox()
        self.category.addItem("")
        self.category.addItems(schema.CATEGORIES)
        form.addRow("Category", self.category)

        self.tier = QComboBox()
        self.tier.addItems(["premium", "free"])
        form.addRow("Tier", self.tier)

        self.license_type = QComboBox()
        self.license_type.addItems(schema.LICENSES)
        form.addRow("License", self.license_type)

        self.price_personal = self._price()
        self.price_professional = self._price()
        prices = QHBoxLayout()
        prices.addWidget(QLabel("personal"))
        prices.addWidget(self.price_personal)
        prices.addSpacing(10)
        prices.addWidget(QLabel("professional"))
        prices.addWidget(self.price_professional)
        prices.addStretch(1)
        form.addRow("Price (USD)", self._wrap(prices))
        box.addLayout(form)
        layout.addWidget(frame)

        frame, box = card(
            "Description",
            "Fab wants three things: what it is, how to use it, and the "
            "technical details. The technical block is generated from the "
            "descriptor and appended automatically.",
        )
        self.desc_what = self._text_area("What it is")
        self.desc_how = self._text_area("How to use it")
        self.desc_technical = self._text_area("Extra technical notes")
        for label, widget in (
            ("What it is", self.desc_what),
            ("How to use it", self.desc_how),
            ("Extra technical notes", self.desc_technical),
        ):
            caption = QLabel(label)
            caption.setProperty("role", "caption")
            box.addWidget(caption)
            box.addWidget(widget)

        ask_row = QHBoxLayout()
        self.ask_button = QPushButton("Ask Claude...")
        self.ask_button.clicked.connect(self._ask)
        self.improve_button = QPushButton("Ask for improvements...")
        self.improve_button.setToolTip(
            "Continues the same conversation, so it still has its own draft in "
            "context."
        )
        self.improve_button.clicked.connect(self._improve)
        self.copy_prompt_button = QPushButton("Copy prompt")
        self.copy_prompt_button.setProperty("variant", "ghost")
        self.copy_prompt_button.clicked.connect(self._copy_prompt)
        ask_row.addWidget(self.ask_button)
        ask_row.addWidget(self.improve_button)
        ask_row.addWidget(self.copy_prompt_button)
        ask_row.addStretch(1)
        self.copy_description_button = QPushButton("Copy description")
        self.copy_description_button.setToolTip(
            "Copies the built description with its headings, bullets and bold, "
            "ready to paste into Fab's description field. Reflects the last Check."
        )
        self.copy_description_button.clicked.connect(self._copy_description)
        ask_row.addWidget(self.copy_description_button)
        box.addLayout(ask_row)
        layout.addWidget(frame)

        frame, box = card(
            "Tags",
            "One per line, at most 25. These are suggestions: Fab only offers "
            "tags it already knows, so delete any the picker does not have.",
        )
        self.tags_edit = QPlainTextEdit()
        self.tags_edit.setFont(self._mono)
        self.tags_edit.setMaximumHeight(140)
        self.tags_count = QLabel("0 / 25")
        self.tags_count.setProperty("role", "hint")
        self.tags_edit.textChanged.connect(self._update_tag_count)
        box.addWidget(self.tags_edit)
        box.addWidget(self.tags_count)
        layout.addWidget(frame)

        frame, box = card("Declarations")
        self.declarations: dict[str, QCheckBox] = {}
        for key, label in (
            ("mature", "Mature content"),
            ("no_ai", "Disallow use by Generative AI Programs"),
            ("generative_ai", "Created with generative AI"),
            ("promotional", "Includes promotional content"),
            ("edc_forum_post", "Create an Epic Developer Community forum post"),
        ):
            checkbox = QCheckBox(label)
            self.declarations[key] = checkbox
            box.addWidget(checkbox)
        layout.addWidget(frame)

        save_row = QHBoxLayout()
        self.save_fields = QPushButton("Save")
        self.save_fields.setProperty("variant", "primary")
        self.save_fields.clicked.connect(self._save_fields)
        save_row.addStretch(1)
        save_row.addWidget(self.save_fields)
        layout.addLayout(save_row)
        layout.addStretch(1)

        page.setWidget(body)
        return page

    def _wrap(self, layout) -> QWidget:
        holder = QWidget()
        holder.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return holder

    def _price(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 9999.0)
        spin.setDecimals(2)
        spin.setSingleStep(5.0)
        spin.setPrefix("$")
        return spin

    def _text_area(self, placeholder: str) -> QPlainTextEdit:
        edit = QPlainTextEdit()
        edit.setPlaceholderText(placeholder)
        edit.setMaximumHeight(110)
        return edit

    def _update_title_count(self) -> None:
        length = len(self.title_edit.text())
        self.title_count.setText(f"{length} / {fabrules.TITLE_MAX}")
        state = ""
        if length > fabrules.TITLE_MAX:
            state = "error"
        elif length > fabrules.TITLE_RECOMMENDED:
            state = "warn"
        self.title_count.setProperty("state", state)
        repolish(self.title_count)

    def _update_tag_count(self) -> None:
        count = len([t for t in self.tags_edit.toPlainText().splitlines() if t.strip()])
        self.tags_count.setText(f"{count} / {fabrules.TAGS_MAX}")
        self.tags_count.setProperty("state", "error" if count > fabrules.TAGS_MAX else "")
        repolish(self.tags_count)

    # --------------------------------------------------------------- media
    def _media_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        self.media_hint = QLabel()
        self.media_hint.setProperty("role", "caption")
        self.media_hint.setWordWrap(True)
        layout.addWidget(self.media_hint)

        self.media_tree = QTreeWidget()
        self.media_tree.setColumnCount(4)
        self.media_tree.setHeaderLabels(["#", "File", "Size", "Dimensions"])
        self.media_tree.setRootIsDecorated(False)
        self.media_tree.setColumnWidth(0, 40)
        self.media_tree.setColumnWidth(1, 260)
        layout.addWidget(self.media_tree, 1)

        self.open_media = QPushButton("Open media folder")
        self.open_media.setProperty("variant", "ghost")
        self.open_media.clicked.connect(self._open_media_folder)
        row = QHBoxLayout()
        row.addWidget(self.open_media)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _open_media_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if self._row is None or self._listings_dir is None:
            return
        folder = source.media_root(self._listings_dir) / self._row.plugin_id
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # --------------------------------------------------------------- others
    def _audit_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 14)
        hint = QLabel(
            "Whether Fab would reject the package itself, which is a different "
            "question from whether the listing copy is complete. Each row cites "
            "the requirement it comes from."
        )
        hint.setProperty("role", "caption")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.audit_list = IssueList()
        layout.addWidget(self.audit_list, 1)

        row = QHBoxLayout()
        copy_selected = QPushButton("Copy selected")
        copy_selected.setProperty("variant", "ghost")
        copy_selected.clicked.connect(self.audit_list.copy_selected)
        copy_all = QPushButton("Copy all")
        copy_all.clicked.connect(self.audit_list.copy_all)
        row.addWidget(copy_selected)
        row.addWidget(copy_all)
        row.addStretch(1)
        note = QLabel("Right-click or Ctrl+C copies rows too.")
        note.setProperty("role", "hint")
        row.addWidget(note)
        layout.addLayout(row)
        return page

    def _diff_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 14)
        self.diff_view = DiffView()
        layout.addWidget(self.diff_view, 1)
        self.issue_list = IssueList()
        layout.addWidget(self.issue_list, 1)
        return page

    def _provenance_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 14)
        hint = QLabel(
            "Where each value came from: authored in the listing file, derived "
            "from the plugin, or a suite-wide default."
        )
        hint.setProperty("role", "caption")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.provenance_tree = QTreeWidget()
        self.provenance_tree.setColumnCount(3)
        self.provenance_tree.setHeaderLabels(["Field", "Origin", "From"])
        self.provenance_tree.setRootIsDecorated(False)
        self.provenance_tree.setColumnWidth(0, 220)
        self.provenance_tree.setColumnWidth(1, 90)
        layout.addWidget(self.provenance_tree, 1)
        return page

    def _json_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)

        hint = QLabel(
            "The authored file itself - the escape hatch for anything the "
            "Fields tab does not model."
        )
        hint.setProperty("role", "caption")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.json_edit = QPlainTextEdit()
        self.json_edit.setFont(self._mono)
        layout.addWidget(self.json_edit, 1)

        self.json_error = QLabel("")
        self.json_error.setProperty("role", "hint")
        self.json_error.setWordWrap(True)
        layout.addWidget(self.json_error)

        row = QHBoxLayout()
        row.addStretch(1)
        self.save_json = QPushButton("Save")
        self.save_json.setProperty("variant", "primary")
        self.save_json.clicked.connect(self._save_json)
        row.addWidget(self.save_json)
        layout.addLayout(row)
        return page

    # -------------------------------------------------------------- loading
    def set_row(self, row: ListingRow | None, listings_dir: Path | None) -> None:
        self._row = row
        self._listings_dir = listings_dir
        self.setEnabled(row is not None and listings_dir is not None)
        if row is None:
            return
        self._authored = dict(row.authored)
        self._load_fields(row, self._authored)
        self._load_media(row)
        self.audit_list.show_issues(
            list(row.audit), "No packaging problems found."
        )
        self.diff_view.show_report(row.report)
        self.issue_list.show_issues(list(row.issues), "This listing is ready.")
        self._load_provenance(row)
        self._load_json_data(self._authored)

    def _reload_current(self) -> None:
        """Re-read from disk on tab change: the file, not a widget, is truth.

        Held separately from the row rather than written back into it, because
        the row is a frozen result object owned by the last check.
        """
        if self._row is None or self._listings_dir is None:
            return
        loaded = source.load_source(self._listings_dir, self._row.plugin_id)
        if loaded.error:
            return
        self._authored = loaded.data
        if self.currentIndex() == self.count() - 1:
            self._load_json_data(self._authored)
        elif self.currentIndex() == 0:
            self._load_fields(self._row, self._authored)

    def _load_fields(self, row: ListingRow, authored: dict) -> None:
        listing = row.listing or {}
        self.title_edit.setText(str(authored.get("title") or listing.get("title") or ""))
        self._select(self.product_type, listing.get("product_type") or "")
        self._select(self.category, listing.get("category") or "")
        self._select(self.tier, row.tier)
        self._select(self.license_type, (listing.get("license") or {}).get("type", ""))
        license_ = listing.get("license") or {}
        self.price_personal.setValue(float(license_.get("price_personal") or 0))
        self.price_professional.setValue(float(license_.get("price_professional") or 0))

        description = authored.get("description") or {}
        self.desc_what.setPlainText(str(description.get("what") or ""))
        self.desc_how.setPlainText(str(description.get("how") or ""))
        self.desc_technical.setPlainText(str(description.get("technical") or ""))

        self.tags_edit.setPlainText("\n".join(listing.get("tags") or []))
        declarations = listing.get("declarations") or {}
        for key, checkbox in self.declarations.items():
            checkbox.setChecked(bool(declarations.get(key)))
        self._update_title_count()
        self._update_tag_count()

    def _select(self, combo: QComboBox, value: str) -> None:
        index = combo.findText(str(value or ""))
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _load_media(self, row: ListingRow) -> None:
        media = (row.listing or {}).get("media") or {}
        thumbnail = media.get("thumbnail") or {}
        missing = media.get("missing") or []
        self.media_hint.setText(
            f"Thumbnail and gallery live under the listings media folder. "
            f"{media.get('gallery_count', 0)} gallery item(s)."
            + (f"  Missing on disk: {', '.join(missing)}" if missing else "")
        )

        self.media_tree.clear()
        entries = [("thumb", thumbnail)] + [
            (str(item.get("index", "")), item) for item in media.get("gallery") or []
        ]
        for label, facts in entries:
            if not facts:
                continue
            size = facts.get("bytes") or 0
            dimensions = (
                f"{facts.get('width')}x{facts.get('height')}"
                if facts.get("width")
                else "unreadable"
            )
            item = QTreeWidgetItem(
                self.media_tree,
                [label, facts.get("source", ""), f"{size / 1024:.0f} KB", dimensions],
            )
            item.setFont(1, self._mono)

    def _load_provenance(self, row: ListingRow) -> None:
        self.provenance_tree.clear()
        for path in sorted(row.provenance):
            origin = row.provenance[path]
            item = QTreeWidgetItem(
                self.provenance_tree, [path, origin.kind, origin.detail]
            )
            item.setFont(0, self._mono)
            item.setToolTip(2, origin.detail)

    def _load_json_data(self, authored: dict) -> None:
        text = json.dumps(authored, indent=2, ensure_ascii=False) if authored else "{}"
        self.json_edit.setPlainText(text)
        self.json_error.setText("")

    # --------------------------------------------------------------- saving
    def _write(self, data: dict) -> None:
        if self._row is None or self._listings_dir is None:
            return
        source.save_source(self._listings_dir, self._row.plugin_id, data)
        self._authored = data
        self.saved.emit(self._row.plugin_id)

    def _save_fields(self) -> None:
        if self._row is None:
            return
        data = dict(self._authored)
        data["title"] = self.title_edit.text().strip()
        data["tier"] = self.tier.currentText()
        data["license"] = self.license_type.currentText()
        data["product_type"] = self.product_type.currentText()
        if self.category.currentText():
            data["category"] = self.category.currentText()
        data["price"] = {
            "personal": round(self.price_personal.value(), 2),
            "professional": round(self.price_professional.value(), 2),
        }
        data["description"] = {
            "what": self.desc_what.toPlainText().strip(),
            "how": self.desc_how.toPlainText().strip(),
            "technical": self.desc_technical.toPlainText().strip(),
        }
        data["tags"] = [t.strip() for t in self.tags_edit.toPlainText().splitlines() if t.strip()]
        data["declarations"] = {
            key: box.isChecked() for key, box in self.declarations.items()
        }
        self._write(data)

    def _save_json(self) -> None:
        try:
            data = json.loads(self.json_edit.toPlainText())
        except ValueError as exc:
            # Report and refuse. Writing unparseable text would lose the file.
            self.json_error.setText(f"Not valid JSON: {exc}")
            self.json_error.setProperty("state", "error")
            repolish(self.json_error)
            return
        if not isinstance(data, dict):
            self.json_error.setText("The listing file must contain a JSON object.")
            return
        self.json_error.setText("")
        self._write(data)

    # ---------------------------------------------------------------- draft
    def _ask(self) -> None:
        if self._row is not None:
            self.draft_requested.emit(self._row.plugin_id)

    def _improve(self) -> None:
        """Ask for a change in words, rather than editing the fields by hand."""
        if self._row is None:
            return
        instruction, accepted = QInputDialog.getMultiLineText(
            self,
            "Ask Claude for improvements",
            f"What should change about {self._row.plugin_id}'s copy?\n"
            f"The conversation is resumed, so it still has its own draft in "
            f"context.",
            "",
        )
        if accepted and instruction.strip():
            self.improve_requested.emit(self._row.plugin_id, instruction.strip())

    def _copy_prompt(self) -> None:
        if self._row is not None:
            self.copy_prompt_requested.emit(self._row.plugin_id)

    def _copy_description(self) -> None:
        """The composed description, formatted for Fab's editor.

        Both flavours go on the clipboard: rich editors take the HTML, and
        anything else still gets clean text rather than markup.
        """
        if self._row is None:
            return
        text = str(((self._row.listing or {}).get("description") or {}).get("text") or "")
        mime = QMimeData()
        mime.setHtml(markup.to_html(text))
        mime.setText(markup.to_plain(text))
        QGuiApplication.clipboard().setMimeData(mime)
