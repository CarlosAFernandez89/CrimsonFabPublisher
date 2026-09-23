"""The Listings page, driven through the real window.

Reuses `test_ui_smoke`'s fixtures: without the sandbox these would hit the real
registry and rglob the real engine tree.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from fabpublisher.listing import source
from fabpublisher.ui.draft_worker import DraftWorker, resolve_cli
from fabpublisher.ui.listing_table_model import ChipColorRole, ChipRole, status_word
from fabpublisher.ui.nav_sidebar import LISTINGS

from .conftest import write_png
from .test_ui_smoke import qapp, sandbox, window  # noqa: F401


@pytest.fixture
def staged(window, tmp_path: Path):  # noqa: F811
    """A window whose listings folder is configured and seeded."""
    listings = tmp_path / "listings"
    (listings / "media").mkdir(parents=True)
    for name in ("Common", "Ability", "Core"):
        write_png(listings / "media" / name / "thumbnail.png")
    source.write_json(
        listings / "_defaults.json",
        {
            "category": "Engine Tools",
            "tags": ["unreal", "plugin", "tools", "runtime", "gameplay"],
            "media": {"thumbnail": "{id}/thumbnail.png"},
            "technical": {"dev_platforms": ["Windows"], "target_platforms": ["Win64"]},
            "silence": {"gallery_thumbnail_only": True},
        },
    )
    window.settings.listings_dir = str(listings)
    window._configure_listings()
    return window, listings


def run_check(win) -> None:
    """Run a check synchronously - the worker is a QThread we can wait on."""
    win._check_listings("All")
    worker = win.listings._worker
    assert worker is not None
    worker.wait(20000)
    qapp_process()


def qapp_process() -> None:
    from PySide6.QtWidgets import QApplication

    for _ in range(6):
        QApplication.processEvents()


# --------------------------------------------------------------------- shell
def test_the_page_is_reachable_and_last_but_settings(window):  # noqa: F811
    window._show_page(LISTINGS)

    assert window.stack.currentIndex() == LISTINGS
    assert window.stack.widget(LISTINGS) is window.listings_page


def test_with_nothing_configured_the_default_folder_is_used(window, tmp_path):  # noqa: F811
    """There is always a folder, so the page never opens on a dead end."""
    window.settings.listings_dir = ""
    window._configure_listings()

    expected = window.settings.effective_listings_dir()
    assert expected.is_dir()
    assert "Documents" in str(expected) or str(tmp_path) in str(expected)
    assert window.listings_page.stack.currentIndex() == 1


def test_a_default_folder_never_lands_inside_the_app_repo(window):  # noqa: F811
    """Whoever clones this tool publishes their own plugins, not ours."""
    from fabpublisher.ui.app_settings import default_listings_dir

    default = default_listings_dir()
    repo = Path(__file__).resolve().parent.parent

    assert repo not in default.resolve().parents
    assert default.resolve() != repo


def test_an_unusable_folder_is_reported_on_the_page(window, tmp_path):  # noqa: F811
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("I am a file", encoding="utf-8")
    window.settings.listings_dir = str(blocker / "listings")

    window._configure_listings()

    assert window.listings_page.stack.currentIndex() == 0


def test_configuring_a_folder_switches_to_the_table(staged):
    win, _ = staged

    assert win.listings_page.stack.currentIndex() == 1


# --------------------------------------------------------------------- check
def test_check_populates_a_row_per_plugin(staged):
    win, _ = staged

    run_check(win)

    model = win.listings_page.model
    assert model.rowCount() == 3
    assert {model.row_at(i).plugin_id for i in range(3)} == {
        "Common",
        "Ability",
        "Core",
    }


def test_the_status_column_carries_a_chip_and_its_colour(staged):
    win, _ = staged
    run_check(win)

    index = win.listings_page.model.index(0, 5)

    assert index.data(ChipRole) == "NEW"
    assert index.data(ChipColorRole).startswith("#")


def test_a_live_listing_is_marked_in_the_table(staged):
    win, _ = staged
    plugin = next(p for p in win.model.plugins() if p.name == "Common")
    plugin.fab_url = "https://www.fab.com/listings/11111111-2222-3333-4444-555555555555"

    run_check(win)

    row = next(
        r for r in win.listings_page.model.rows() if r.plugin_id == "Common"
    )
    assert row.plugin.is_live
    column = win.listings_page.model.index(
        win.listings_page.model.rows().index(row), 4
    )
    assert column.data(Qt.DisplayRole) == "live"
    assert "do not create a new one" in column.data(Qt.ToolTipRole)


def test_an_excluded_plugin_is_shown_but_not_counted(staged):
    win, listings = staged
    source.write_json(listings / "Core.json", {"publish": False})

    run_check(win)

    excluded = next(
        r for r in win.listings_page.model.rows() if r.plugin_id == "Core"
    )
    assert not excluded.publishable
    assert status_word(excluded) == "excluded"


# -------------------------------------------------------------------- editor
def test_selecting_a_row_loads_the_editor(staged):
    win, _ = staged
    run_check(win)

    win.listings_page.table.selectRow(0)
    editor = win.listings_page.editor

    assert editor.isEnabled()
    assert editor.title_edit.text()
    assert editor.provenance_tree.topLevelItemCount() > 0


def test_the_title_counter_warns_past_the_recommended_length(staged):
    win, _ = staged
    run_check(win)
    win.listings_page.table.selectRow(0)
    editor = win.listings_page.editor

    editor.title_edit.setText("x" * 40)
    assert editor.title_count.property("state") == "warn"

    editor.title_edit.setText("x" * 90)
    assert editor.title_count.property("state") == "error"


def test_saving_the_fields_tab_writes_the_listing_file(staged):
    win, listings = staged
    run_check(win)
    win.listings_page.table.selectRow(0)
    editor = win.listings_page.editor
    plugin_id = win.listings_page.selected_rows()[0].plugin_id

    editor.title_edit.setText("Hand Written Title")
    editor._save_fields()

    written = source.load_source(listings, plugin_id).data
    assert written["title"] == "Hand Written Title"


def test_invalid_raw_json_is_refused_rather_than_written(staged):
    win, listings = staged
    run_check(win)
    win.listings_page.table.selectRow(0)
    editor = win.listings_page.editor
    plugin_id = win.listings_page.selected_rows()[0].plugin_id
    before = source.load_source(listings, plugin_id).data

    editor.json_edit.setPlainText("{ not json at all")
    editor._save_json()

    assert "Not valid JSON" in editor.json_error.text()
    assert source.load_source(listings, plugin_id).data == before


def test_valid_raw_json_is_written(staged):
    win, listings = staged
    run_check(win)
    win.listings_page.table.selectRow(0)
    editor = win.listings_page.editor
    plugin_id = win.listings_page.selected_rows()[0].plugin_id

    editor.json_edit.setPlainText(json.dumps({"tags": ["one", "two"]}))
    editor._save_json()

    assert source.load_source(listings, plugin_id).data == {"tags": ["one", "two"]}


# --------------------------------------------------------------------- build
def test_build_writes_the_bundles_and_the_status_table(staged):
    win, listings = staged
    run_check(win)

    win.settings.auto_open_output = False
    win._build_listings()

    out = win.settings.effective_output_dir() / "_Listings" / "Common"
    assert (out / "checklist.md").is_file()
    assert (listings / source.STATUS_FILENAME).is_file()


def test_accept_then_check_reports_clean(staged):
    win, _ = staged
    run_check(win)
    plugin = next(p for p in win.model.plugins() if p.name == "Common")
    plugin.fab_url = "https://www.fab.com/listings/11111111-2222-3333-4444-555555555555"
    run_check(win)

    row = next(r for r in win.listings_page.model.rows() if r.plugin_id == "Common")
    assert not row.blocked, [i.message for i in row.errors]
    win.listings.accept([row], force=False)
    run_check(win)

    after = next(r for r in win.listings_page.model.rows() if r.plugin_id == "Common")
    assert after.report.status == "clean"


# --------------------------------------------------------------------- draft
def test_the_prompt_can_always_be_copied(staged):
    win, _ = staged
    run_check(win)
    win.listings_page.table.selectRow(0)

    win._copy_listing_prompt("Common")

    from PySide6.QtGui import QGuiApplication

    assert "Fab" in QGuiApplication.clipboard().text()


def test_a_missing_cli_falls_back_to_copying_rather_than_failing(staged):
    win, _ = staged
    run_check(win)
    win.listings_page.table.selectRow(0)
    win.settings.claude_path = "definitely-not-a-real-binary"

    win._draft_listing("Common")

    # isVisible() is False for every widget while the window is never shown,
    # so ask whether the pane was explicitly hidden instead.
    assert not win.listings_page.draft_pane.isHidden()
    assert "Prompt copied" in win.listings_page.draft_pane.toPlainText()


def test_resolve_cli_reports_absence_rather_than_guessing():
    assert resolve_cli("definitely-not-a-real-binary") is None


#: Stands in for the CLI: reads the prompt from stdin, narrates, then answers.
STAND_IN = (
    "import sys;"
    "p = sys.stdin.read();"
    "print('thinking...');"
    "print('read %d chars' % len(p));"
    'print(\'Here you go: {"title": "Demo Plugin", "tags": ["a"]}\')'
)


def _stand_in_worker(prompt: str = "prompt text") -> DraftWorker:
    return DraftWorker(sys.executable, prompt, args=("-c", STAND_IN))


def test_the_draft_worker_streams_lines_then_returns_the_whole_reply(qapp):  # noqa: F811
    worker = _stand_in_worker()
    lines: list[str] = []
    done: list[tuple[str, str]] = []
    worker.line.connect(lines.append)
    worker.finished_draft.connect(lambda out, err: done.append((out, err)))

    worker.start()
    worker.wait(20000)
    qapp_process()

    # Streamed in order, so the pane fills as it goes rather than at the end.
    assert lines[0] == "thinking..."
    assert done and done[0][1] == ""
    assert '"title"' in done[0][0]


def test_the_prompt_reaches_the_process_on_stdin(qapp):  # noqa: F811
    """Not argv: Windows caps a command line at 32,767 characters."""
    prompt = "x" * 5000
    worker = _stand_in_worker(prompt)
    done: list[tuple[str, str]] = []
    worker.finished_draft.connect(lambda out, err: done.append((out, err)))

    worker.start()
    worker.wait(20000)
    qapp_process()

    assert f"read {len(prompt)} chars" in done[0][0]


def test_a_draft_wrapped_in_prose_still_yields_its_json(qapp):  # noqa: F811
    from fabpublisher.listing.prompt import extract_json_block

    worker = _stand_in_worker()
    done: list[tuple[str, str]] = []
    worker.finished_draft.connect(lambda out, err: done.append((out, err)))
    worker.start()
    worker.wait(20000)
    qapp_process()

    assert extract_json_block(done[0][0]) == {"title": "Demo Plugin", "tags": ["a"]}


def test_a_worker_that_cannot_start_reports_instead_of_raising(qapp):  # noqa: F811
    worker = DraftWorker("definitely-not-a-real-binary", "prompt")
    done: list[tuple[str, str]] = []
    worker.finished_draft.connect(lambda out, err: done.append((out, err)))

    worker.start()
    worker.wait(20000)
    qapp_process()

    assert done and "Could not start" in done[0][1]


# ------------------------------------------------------- audit copy + fields
def test_audit_findings_can_be_copied(staged):
    """A finding you can only read is a finding you retype."""
    win, _ = staged
    run_check(win)
    win.listings_page.table.selectRow(0)

    text = win.listings_page.editor.audit_list.copy_all()

    assert text
    from PySide6.QtGui import QGuiApplication

    assert QGuiApplication.clipboard().text() == text
    # Level and key travel with the message, so it is actionable elsewhere.
    assert any(line.startswith(("ERROR", "WARNING")) for line in text.splitlines())


def test_the_description_is_copied_rich_and_plain(staged):
    """Fab's editor keeps the HTML; anything else gets text without markup."""
    win, _ = staged
    run_check(win)
    win.listings_page.table.selectRow(0)

    win.listings_page.editor.copy_description_button.click()

    from PySide6.QtGui import QGuiApplication

    mime = QGuiApplication.clipboard().mimeData()
    assert mime.hasHtml()
    assert "<p>" in mime.html()
    assert mime.text()
    assert "**" not in mime.text()


def test_copying_nothing_leaves_the_clipboard_alone(qapp):  # noqa: F811
    from fabpublisher.ui.diff_view import IssueList

    widget = IssueList()
    widget.show_issues([])

    assert widget.copy_all() == ""


def test_product_type_and_category_are_separate_fields(staged):
    win, _ = staged
    run_check(win)
    win.listings_page.table.selectRow(0)
    editor = win.listings_page.editor

    assert editor.product_type.currentText() == "Tools & Plugins"
    assert editor.category.currentText() == "Engine Tools"


def test_saving_the_fields_writes_product_type_and_category(staged):
    win, listings = staged
    run_check(win)
    win.listings_page.table.selectRow(0)
    editor = win.listings_page.editor
    plugin_id = win.listings_page.selected_rows()[0].plugin_id

    editor.category.setCurrentText("Physics")
    editor._save_fields()

    written = source.load_source(listings, plugin_id).data
    assert written["category"] == "Physics"
    assert written["product_type"] == "Tools & Plugins"


def test_the_listing_names_its_required_plugins(staged):
    """Ability depends on Common, which the customer has to install."""
    win, _ = staged
    run_check(win)

    row = next(r for r in win.listings_page.model.rows() if r.plugin_id == "Ability")

    assert "Common" in row.listing["technical"]["required_plugins"]
    assert "Required plugins" in row.listing["description"]["text"]


# ------------------------------------------------------------ prompt + resume
def test_the_prompt_template_can_be_edited_in_settings(staged):
    win, _ = staged
    page = win.settings_page

    assert not page.prompt_body.isVisibleTo(page)
    page.prompt_toggle.setChecked(True)
    assert page.prompt_body.isVisibleTo(page)

    page.prompt_edit.setPlainText("Write copy about {facts}. Nothing else.")
    page._commit_prompt()

    assert win.settings.listing_prompt_template.startswith("Write copy about")


def test_an_unedited_template_is_stored_as_empty(staged):
    """So a later improvement to the built-in prompt still reaches the user."""
    from fabpublisher.listing import prompt as prompt_mod

    win, _ = staged
    page = win.settings_page
    page.prompt_edit.setPlainText(prompt_mod.DEFAULT_TEMPLATE)
    page._commit_prompt()

    assert win.settings.listing_prompt_template == ""


def test_a_custom_template_reaches_the_composed_prompt(staged):
    win, _ = staged
    run_check(win)
    win.listings_page.table.selectRow(0)
    row = win.listings_page.selected_rows()[0]

    win.listings.prompt_template = "ONLY THIS. Facts:\n{facts}"
    text = win.listings.draft_prompt_for(row)

    assert text.startswith("ONLY THIS.")
    assert "Plugin id:" in text, "placeholders still fill in"


def test_a_stray_brace_in_a_template_renders_literally_rather_than_crashing(staged):
    win, _ = staged
    run_check(win)
    win.listings_page.table.selectRow(0)
    row = win.listings_page.selected_rows()[0]

    win.listings.prompt_template = "Use {facts} and keep {this_is_not_a_placeholder}."
    text = win.listings.draft_prompt_for(row)

    assert "{this_is_not_a_placeholder}" in text


def test_the_first_draft_mints_a_session_that_survives_a_reload(staged):
    win, listings = staged
    run_check(win)
    row = win.listings_page.model.rows()[0]
    assert not win.listings.has_session(row.plugin_id)

    win.settings.claude_path = "definitely-not-a-real-binary"
    win.listings.start_draft(row, win.settings.claude_path)  # refused, no session yet
    assert not win.listings.has_session(row.plugin_id)

    # Simulate a successful launch minting the id.
    from fabpublisher.listing import source as source_mod

    source_mod.save_sessions(listings, {row.plugin_id: "abc-123"})
    win._configure_listings()

    assert win.listings.has_session(row.plugin_id)


def test_sessions_survive_an_unreadable_file(tmp_path):
    from fabpublisher.listing import source as source_mod

    (tmp_path / "_sessions.json").write_text("{ not json", encoding="utf-8")

    assert source_mod.load_sessions(tmp_path) == {}
