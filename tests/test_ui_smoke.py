"""Construct the real UI offscreen.

Cheap net for the things unit tests cannot see: broken imports, mistyped signal
connections, a QSS that fails to parse, and delegates that crash on paint.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from fabpublisher import config as config_module  # noqa: E402
from fabpublisher.models import PluginStatus  # noqa: E402
from fabpublisher.ui.log_model import LogLevel  # noqa: E402
from fabpublisher.ui.theme import apply_theme, icons, stylesheet  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    yield app


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch):
    """Redirect app data and stub engine detection.

    Without the stub every window would hit the registry and rglob the real
    engine's Plugins tree, which makes the suite slow and machine-dependent.
    """
    monkeypatch.setattr(config_module, "data_dir", lambda: tmp_path / "appdata")
    (tmp_path / "appdata").mkdir()

    from fabpublisher.models import EngineInfo
    from fabpublisher.ui import main_window as main_window_module

    engine_root = tmp_path / "UE_5.8"
    (engine_root / "Engine" / "Plugins" / "Runtime" / "GameplayAbilities").mkdir(
        parents=True
    )
    (
        engine_root
        / "Engine"
        / "Plugins"
        / "Runtime"
        / "GameplayAbilities"
        / "GameplayAbilities.uplugin"
    ).write_text("{}")
    engine = EngineInfo(identifier="UE_5.8", version="5.8", root=engine_root)
    monkeypatch.setattr(main_window_module, "detect_engines", lambda *_a: [engine])
    return tmp_path


@pytest.fixture
def window(qapp, suite: Path, sandbox: Path):
    """A MainWindow pointed at the fixture suite, with data redirected."""
    from fabpublisher.ui.main_window import MainWindow

    win = MainWindow()
    win.settings.plugins_root = str(suite)
    win.rescan()
    yield win
    win.build.shutdown()
    win.deleteLater()


def test_stylesheet_parses_and_has_no_leftover_placeholders():
    qss = stylesheet()
    assert qss, "crimson.qss was not found"
    assert "{{" not in qss, "an unsubstituted token placeholder is in the QSS"


def test_apply_theme_survives_a_missing_stylesheet(qapp, monkeypatch):
    monkeypatch.setattr(
        "fabpublisher.ui.theme._qss_path", lambda: Path("does/not/exist.qss")
    )
    assert apply_theme(qapp) is False  # degrades, does not raise
    apply_theme(qapp)  # restore


def test_every_icon_renders(qapp):
    for name in icons.names():
        assert not icons.icon(name).isNull(), name
    assert icons.icon("nope").isNull()


def test_window_constructs_and_scans(window, suite: Path):
    names = {p.name for p in window.model.plugins()}
    assert names == {"Common", "Ability", "Core"}
    assert window.plugins_page.stack.currentIndex() == 1  # not the empty state


def test_every_page_can_be_shown(window):
    for index in range(4):
        window._show_page(index)
        assert window.stack.currentIndex() == index
        assert window.nav.current_page() == index


def test_empty_state_shows_without_a_folder(qapp, sandbox: Path):
    from fabpublisher.ui.main_window import MainWindow

    win = MainWindow()
    assert win.plugins_page.stack.currentIndex() == 0
    win.deleteLater()


def test_preflight_blocks_with_nothing_selected(window):
    window.model.set_checked(set())
    window._refresh_build_page()
    assert not window.build_page.build_btn.isEnabled()


def test_queue_preview_pulls_in_dependencies(window):
    window.model.set_checked({"Core"})
    window._refresh_build_page()
    rows = [
        window.build_page.queue_list.item(i).text()
        for i in range(window.build_page.queue_list.count())
    ]
    assert len(rows) == 3  # Core plus Ability plus Common
    assert "Common" in rows[0]
    assert "auto" in rows[0]
    assert rows[-1].endswith("Core")


def test_selection_survives_a_rescan(window):
    window.model.set_checked({"Core"})
    window.rescan()
    assert window.model.checked_names() == ["Core"]


def test_select_changed_chip_uses_scan_impact(window):
    window.plugins_page.select_changed()
    # Everything is unbuilt on a fresh store, so everything needs a rebuild.
    assert set(window.model.checked_names()) == {"Common", "Ability", "Core"}


def test_name_filter_hides_rows(window):
    window.plugins_page.search.setText("Core")
    assert window.plugins_page.proxy.rowCount() == 1
    window.plugins_page.search.setText("")
    assert window.plugins_page.proxy.rowCount() == 3


def test_status_filter_hides_rows(window):
    combo = window.plugins_page.status_filter
    target = combo.findData(PluginStatus.MISSING_DEP)
    combo.setCurrentIndex(target)
    # Ability declares ThirdParty, which resolves nowhere.
    assert window.plugins_page.proxy.rowCount() == 1


def test_detail_panel_renders_for_each_plugin(window):
    for row in range(window.plugins_page.proxy.rowCount()):
        window.plugins_page.table.selectRow(row)
        assert window.plugins_page.detail_name.text()


def test_table_paints_every_status(window, qapp):
    """Exercises the pill delegate against all nine states."""
    from PySide6.QtGui import QPixmap

    table = window.plugins_page.table
    table.resize(900, 300)
    for status in PluginStatus:
        for plugin in window.model.plugins():
            window.model.set_status(plugin.name, status, "some reason")
        pixmap = QPixmap(table.size())
        table.render(pixmap)  # would raise if the delegate blew up


def test_logs_page_filters_and_exports(window):
    window.logs.clear()
    window.logs.append("plain", LogLevel.INFO, "Core")
    window.logs.append("bad", LogLevel.ERROR, "Core")
    page = window.logs_page
    page.show_errors()
    assert "bad" in page.view.toPlainText()
    assert "plain" not in page.view.toPlainText()
    assert "bad" in window.logs.to_text(LogLevel.ERROR)


def test_error_badge_tracks_the_log(window):
    window.logs.clear()
    assert window.nav._badges[2].text() == ""
    window.logs.append("boom", LogLevel.ERROR)
    assert window.nav._badges[2].text() == "1"


def test_settings_round_trip_through_the_page(window, sandbox: Path):
    tmp_path = sandbox
    page = window.settings_page
    page.ship_edit.setPlainText("*.md\n\nDocs/")
    assert window.settings.ship_patterns == ["*.md", "Docs/"]
    page.auto_open.setChecked(False)
    assert window.settings.auto_open_output is False
    window._save_settings()
    saved = json.loads((tmp_path / "appdata" / "config.json").read_text())
    assert saved["ship_patterns"] == ["*.md", "Docs/"]
    assert saved["auto_open_output"] is False


def test_unavailable_platforms_get_a_help_button_with_a_tooltip(window):
    """The warning symbol is the affordance: hover for a summary, click for steps."""
    page = window.build_page
    unavailable = [p for p, i in page.platform_info.items() if not i.available]
    assert unavailable, "expected at least one unbuildable target on this host"

    for platform, info in page.platform_info.items():
        warn = page._platform_warn[platform]
        # Shown exactly when there is something to explain.
        assert warn.isHidden() == info.available, platform
        assert page._platform_reason[platform].text() == info.reason
        if not info.available:
            assert "Click for setup steps" in warn.toolTip()


def test_manual_engine_root_round_trips_and_reloads(window, tmp_path: Path):
    """Adding a root must persist and reach the Build page's combo."""
    import json as _json

    root = tmp_path / "PortableUE"
    batch = root / "Engine" / "Build" / "BatchFiles"
    batch.mkdir(parents=True)
    (batch / "RunUAT.bat").write_text("@echo off\n")
    (root / "Engine" / "Build" / "Build.version").write_text(
        _json.dumps({"MajorVersion": 5, "MinorVersion": 9})
    )
    (root / "Engine" / "Build" / "InstalledBuild.txt").write_text("")

    assert window.settings.add_engine_root(str(root)) is True
    assert window.settings.add_engine_root(str(root)) is False  # no duplicates

    window.settings_page._refresh_engine_list()
    assert window.settings_page.engine_list.count() == 1

    # Detection is stubbed in this fixture, so verify the plumbing directly.
    from fabpublisher.engines import detect_engines as real_detect

    # This machine may have real engines installed too, so pick ours by root.
    engines = real_detect(window.settings.custom_engine_roots)
    added = next(e for e in engines if e.root == root)
    assert added.label == "UE_5.9"
    window.build_page.set_engines(engines)
    assert window.build_page.engine_combo.findData(added.identifier) >= 0

    window._save_settings()
    saved = json.loads((tmp_path / "appdata" / "config.json").read_text())
    assert saved["custom_engine_roots"] == [str(root)]

    window.settings.remove_engine_root(str(root))
    assert window.settings.custom_engine_roots == []


def test_stale_manual_root_is_flagged_not_crashed(window, tmp_path: Path):
    window.settings.add_engine_root(str(tmp_path / "moved-away"))
    window.settings_page._refresh_engine_list()
    item = window.settings_page.engine_list.item(0)
    assert "no RunUAT.bat" in item.text()


def test_reset_build_history_marks_everything_changed(window):
    hashes = dict(window._current_hashes)
    for name, digest in hashes.items():
        window.store.mark_built(name, digest)
    window.rescan()
    assert window.model.rebuild_names() == set()

    window._reset_history()
    assert window.model.rebuild_names() == {"Common", "Ability", "Core"}


def test_close_saves_and_does_not_hang(window):
    assert window.close() is True
