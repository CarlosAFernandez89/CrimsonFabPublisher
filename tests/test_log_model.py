"""Log model and the RunUAT severity heuristic."""

from __future__ import annotations

import pytest

from fabpublisher.models import PluginStatus
from fabpublisher.ui.log_model import (
    MAX_RECORDS,
    LogLevel,
    LogModel,
    LogRecord,
    classify_uat_line,
    level_from_issue,
)
from fabpublisher.ui.theme import level_color, status_color


@pytest.mark.parametrize(
    "line, expected",
    [
        # The unambiguous diagnostic form wins outright.
        ("E:\\Src\\Foo.cpp(42): error C2065: undeclared identifier", LogLevel.ERROR),
        ("E:\\Src\\Foo.cpp(9): warning C4100: unreferenced parameter", LogLevel.WARNING),
        ("Foo.cpp(1): fatal error C1083: cannot open include file", LogLevel.ERROR),
        # Summaries that merely mention the words are not failures.
        ("   0 Errors, 0 Warnings", LogLevel.INFO),
        ("Result: Succeeded, 0 Errors", LogLevel.INFO),
        # Paths and identifiers containing the words must not trip the heuristic.
        ("Compiling Engine/Source/Runtime/Core/ErrorHandling.cpp", LogLevel.INFO),
        ("Building WarningSuppression module", LogLevel.INFO),
        # Loose forms that should still be caught.
        ("ERROR: Cannot find engine", LogLevel.ERROR),
        ("BUILD FAILED", LogLevel.ERROR),
        ("UnrealBuildTool: Warning: deprecated API", LogLevel.WARNING),
        ("Took 12.3s to run UnrealBuildTool.exe", LogLevel.INFO),
        ("", LogLevel.INFO),
    ],
)
def test_classify_uat_line(line, expected):
    assert classify_uat_line(line) is expected


def test_level_from_issue_is_exact():
    assert level_from_issue("error") is LogLevel.ERROR
    assert level_from_issue("warning") is LogLevel.WARNING


def test_append_and_records():
    model = LogModel()
    model.append("hello")
    model.append("boom", LogLevel.ERROR, "Core")
    assert model.rowCount() == 2
    assert [r.text for r in model.records()] == ["hello", "boom"]
    assert model.records()[1].level is LogLevel.ERROR
    assert model.records()[1].source == "Core"


def test_sources_are_tracked_in_first_seen_order():
    model = LogModel()
    seen: list[int] = []
    model.sources_changed.connect(lambda: seen.append(1))
    model.append("a", source="Common")
    model.append("b", source="Core")
    model.append("c", source="Common")  # already known -> no new signal
    model.append("d")  # app-level, not a source
    assert model.sources() == ["Common", "Core"]
    assert len(seen) == 2


def test_extend_inserts_as_one_batch():
    model = LogModel()
    inserts: list[tuple[int, int]] = []
    model.rowsInserted.connect(lambda _p, f, l: inserts.append((f, l)))
    model.extend([LogRecord(text=f"line {i}") for i in range(50)])
    assert inserts == [(0, 49)]


def test_extend_of_nothing_is_a_no_op():
    model = LogModel()
    model.extend([])
    assert model.rowCount() == 0


def test_filtering_by_level_and_source():
    model = LogModel()
    model.append("debug", LogLevel.DEBUG)
    model.append("info", LogLevel.INFO, "Core")
    model.append("warn", LogLevel.WARNING, "Core")
    model.append("err", LogLevel.ERROR, "Common")

    assert len(model.filtered()) == 4
    assert [r.text for r in model.filtered(LogLevel.WARNING)] == ["warn", "err"]
    assert [r.text for r in model.filtered(source="Core")] == ["info", "warn"]
    assert [r.text for r in model.filtered(LogLevel.WARNING, "Core")] == ["warn"]


def test_to_text_export_carries_time_level_and_source():
    model = LogModel()
    model.append("something broke", LogLevel.ERROR, "Core")
    line = model.to_text()
    assert "ERROR" in line
    assert "[Core]" in line
    assert "something broke" in line
    assert line.count("\n") == 0


def test_to_text_respects_filters():
    model = LogModel()
    model.append("quiet", LogLevel.INFO)
    model.append("loud", LogLevel.ERROR)
    assert "quiet" not in model.to_text(LogLevel.ERROR)
    assert "loud" in model.to_text(LogLevel.ERROR)


def test_clear_resets_everything():
    model = LogModel()
    model.append("a", source="Core")
    model.clear()
    assert model.rowCount() == 0
    assert model.sources() == []
    assert model.to_text() == ""


def test_truncation_drops_oldest_and_keeps_one_notice(monkeypatch):
    monkeypatch.setattr("fabpublisher.ui.log_model.MAX_RECORDS", 100)
    model = LogModel()
    model.extend([LogRecord(text=f"line {i}") for i in range(150)])
    assert model.rowCount() == 100
    assert "earlier lines dropped" in model.records()[0].text
    assert model.records()[-1].text == "line 149"

    # A second overflow must update the notice, not stack a new one.
    model.extend([LogRecord(text=f"more {i}") for i in range(80)])
    assert model.rowCount() == 100
    notices = [r for r in model.records() if "earlier lines dropped" in r.text]
    assert len(notices) == 1
    assert model.records()[0] is notices[0]
    assert model.records()[-1].text == "more 79"


def test_every_status_and_level_has_a_colour():
    """A new enum member without a colour must fail here, not at paint time."""
    for status in PluginStatus:
        assert status_color(status).startswith("#")
    for level in LogLevel:
        assert level_color(level).startswith("#")


def test_max_records_default_is_sane():
    assert MAX_RECORDS >= 10_000
