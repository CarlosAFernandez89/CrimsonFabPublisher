"""Sub-plugin progress from UBT's action counter."""

from __future__ import annotations

from fabpublisher.ui.build_progress import BuildProgress, PluginProgress, parse_action


def test_parses_ubt_action_lines():
    assert parse_action("[12/98] Compile [x64] Foo.cpp") == (12, 98)
    assert parse_action("  [35/98] Link [x64] UnrealEditor-Core.lib") == (35, 98)


def test_ignores_non_action_lines():
    for line in (
        "Running AutomationTool...",
        "BUILD SUCCESSFUL",
        "",
        "[not/numbers] thing",
        "[5/0] degenerate",
    ):
        assert parse_action(line) is None


def test_progress_advances_within_a_pass():
    p = PluginProgress()
    seen = []
    for n in (1, 25, 50, 98):
        p.note(f"[{n}/98] Compile [x64] F.cpp")
        seen.append(p.fraction)
    assert seen == sorted(seen)
    assert seen[0] > 0
    assert all(f < 1.0 for f in seen)


def test_progress_never_rewinds_across_passes():
    """CrimsonCommon runs three passes (98, 49, 49); the bar must not go back."""
    p = PluginProgress()
    values = []
    for total in (98, 49, 49):
        for n in range(1, total + 1):
            p.note(f"[{n}/{total}] Compile [x64] F.cpp")
            values.append(p.fraction)
    assert values == sorted(values), "fraction decreased between passes"
    assert values[-1] < 1.0, "estimate must never claim completion"


def test_a_new_pass_is_detected_by_a_restarting_counter():
    p = PluginProgress()
    for n in range(1, 50):
        p.note(f"[{n}/49] Compile [x64] F.cpp")
    after_first = p.fraction
    p.note("[1/49] Compile [x64] G.cpp")  # same total, counter restarts
    assert p.fraction >= after_first


def test_reset_clears_progress():
    p = PluginProgress()
    p.note("[40/98] Compile [x64] F.cpp")
    assert p.fraction > 0
    p.reset()
    assert p.fraction == 0.0


def test_overall_value_spans_finished_plugins_plus_current():
    b = BuildProgress(total=2)
    assert b.value == 0.0

    b.start_plugin()
    b.note("[49/98] Compile [x64] F.cpp")
    assert 0.0 < b.value < 1.0

    b.finish_plugin(1)
    assert b.value == 1.0  # exactly at the boundary, no leftover fraction

    b.start_plugin()
    b.note("[49/98] Compile [x64] F.cpp")
    assert 1.0 < b.value < 2.0

    b.finish_plugin(2)
    assert b.value == 2.0


def test_note_reports_whether_the_bar_should_repaint():
    b = BuildProgress(total=1)
    b.start_plugin()
    assert b.note("[10/98] Compile [x64] F.cpp") is True
    assert b.note("Some unrelated log line") is False
    # Same position again: no movement, so no repaint.
    assert b.note("[10/98] Compile [x64] F.cpp") is False
