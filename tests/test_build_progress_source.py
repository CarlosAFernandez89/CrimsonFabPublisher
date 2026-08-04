"""run_build sources progress from the tailed log, without double counting.

Both sources carry the same `[n/m]` lines: the tail while the pass runs, the
pipe once UAT finally flushes. Feeding the bar twice would inflate its estimate
and stall it, so each line must be forwarded exactly once.
"""

from __future__ import annotations

import time
from pathlib import Path

import fabpublisher.builder as builder
from fabpublisher.builder import run_build
from fabpublisher.models import EngineInfo, Platform, PluginInfo
from fabpublisher.shipfilter import ShipFilter

ENGINE = EngineInfo(identifier="UE_5.8", version="5.8", root=Path("F:/UE_5.8"))
ACTIONS = ["[1/2] Compile [x64] A.cpp", "[2/2] Compile [x64] B.cpp"]


class _FakeProc:
    """Stands in for RunUAT: announces its log, goes quiet, then floods."""

    def __init__(self, lines):
        self.stdout = lines
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0


def _plugin(root: Path) -> PluginInfo:
    path = root / "Widget"
    (path / "Source").mkdir(parents=True)
    (path / "Source" / "Widget.cpp").write_text("// code", encoding="utf-8")
    (path / "Widget.uplugin").write_text("{}", encoding="utf-8")
    return PluginInfo(name="Widget", path=path, uplugin_path=path / "Widget.uplugin")


def _run(tmp_path: Path, monkeypatch) -> list[str]:
    uba_log = tmp_path / "UBA-UnrealEditor-Win64-Development.txt"
    uba_log.write_text("lines from an earlier build\n", encoding="utf-8")

    def script():
        """What the pipe delivers, in the order and timing UAT delivers it."""
        yield f"Log file: {uba_log}\n"
        yield "Building UnrealEditor...\n"
        # UBT works, writing its log; the pipe stays silent meanwhile.
        with uba_log.open("a", encoding="utf-8") as handle:
            for action in ACTIONS:
                handle.write(action + "\n")
        time.sleep(0.8)  # let the tailer see them, as it would in a real build
        # UAT's child exits and everything it held arrives at once.
        for action in ACTIONS:
            yield action + "\n"
        yield "Took 90.82s to run dotnet.exe, ExitCode=0\n"

    monkeypatch.setattr(
        builder.subprocess, "Popen", lambda *a, **k: _FakeProc(script())
    )

    progress: list[str] = []
    result = run_build(
        engine=ENGINE,
        plugin=_plugin(tmp_path),
        platforms=Platform.WIN64,
        work_root=tmp_path / "work",
        ship_filter=ShipFilter(),
        output_dir=tmp_path / "out",
        log=lambda _: None,
        on_progress_line=progress.append,
    )
    assert result.success, result.message
    return progress


def test_each_action_reaches_progress_exactly_once(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch) == ACTIONS


def test_progress_arrives_before_the_pipe_flushes(tmp_path, monkeypatch):
    """The whole point: the tail wins the race against UAT."""
    progress = _run(tmp_path, monkeypatch)
    # Both were delivered by the tail, so nothing was left for the replay to
    # add — which is what "the bar moved during the compile" looks like.
    assert progress == ACTIONS


def test_no_progress_callback_is_harmless(tmp_path, monkeypatch):
    """The callback is optional; builds must not depend on one being wired."""
    uba_log = tmp_path / "UBA.txt"
    uba_log.write_text("", encoding="utf-8")
    lines = [f"Log file: {uba_log}\n", *[a + "\n" for a in ACTIONS]]
    monkeypatch.setattr(
        builder.subprocess, "Popen", lambda *a, **k: _FakeProc(iter(lines))
    )
    result = run_build(
        engine=ENGINE,
        plugin=_plugin(tmp_path),
        platforms=Platform.WIN64,
        work_root=tmp_path / "work",
        ship_filter=ShipFilter(),
        output_dir=tmp_path / "out",
        log=lambda _: None,
    )
    assert result.success, result.message
