"""Following UBT's log for live progress.

UAT holds its child's output until the child exits, so the pipe delivers a
whole pass of `[n/m]` lines at once, minutes late. These cover the tailer that
reads them from UBT's own log instead.
"""

from __future__ import annotations

import time
from pathlib import Path

from fabpublisher.builder import _ACTION_LINE, _LOG_FILE_LINE, _ProgressTail


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_announcement_line_yields_the_log_path():
    line = (
        r"Log file: C:\Users\x\AppData\Roaming\Unreal Engine\AutomationTool"
        r"\Logs\F+Epic+Games+UE_5.8\UBA-UnrealEditor-Win64-Development.txt"
    )
    match = _LOG_FILE_LINE.match(line)
    assert match
    assert match.group(1).endswith("UBA-UnrealEditor-Win64-Development.txt")


def test_non_announcement_lines_are_left_alone():
    assert _LOG_FILE_LINE.match("Building UnrealEditor...") is None
    assert _ACTION_LINE.match("[12/98] Compile [x64] Foo.cpp")
    assert _ACTION_LINE.match("Took 90.82s to run dotnet.exe") is None


def test_tail_emits_lines_appended_after_it_starts(tmp_path: Path):
    log = tmp_path / "UBA-UnrealEditor-Win64-Development.txt"
    log.write_text("stale line from the previous run\n", encoding="utf-8")

    seen: list[str] = []
    tail = _ProgressTail(seen.append)
    tail.follow(log)
    try:
        with log.open("a", encoding="utf-8") as handle:
            handle.write("[1/2] Compile [x64] A.cpp\n")
            handle.write("[2/2] Compile [x64] B.cpp\n")
        assert _wait_for(lambda: len(seen) >= 2)
    finally:
        tail.stop()

    # The previous run's content must never count as this run's progress.
    assert seen == ["[1/2] Compile [x64] A.cpp", "[2/2] Compile [x64] B.cpp"]


def test_tail_recovers_when_the_file_is_rewritten(tmp_path: Path):
    """UBT truncates the log for a new pass; progress must not go silent."""
    log = tmp_path / "UBA.txt"
    log.write_text("x" * 5000, encoding="utf-8")

    seen: list[str] = []
    tail = _ProgressTail(seen.append)
    tail.follow(log)
    try:
        log.write_text("[1/1] Compile [x64] Fresh.cpp\n", encoding="utf-8")
        assert _wait_for(lambda: seen)
    finally:
        tail.stop()

    assert seen == ["[1/1] Compile [x64] Fresh.cpp"]


def test_tail_survives_a_missing_file(tmp_path: Path):
    """The log is named before it exists — that must not kill the thread."""
    log = tmp_path / "not-there-yet.txt"

    seen: list[str] = []
    tail = _ProgressTail(seen.append)
    tail.follow(log)
    try:
        time.sleep(0.4)
        log.write_text("[1/1] Compile [x64] Late.cpp\n", encoding="utf-8")
        assert _wait_for(lambda: seen)
    finally:
        tail.stop()

    assert seen == ["[1/1] Compile [x64] Late.cpp"]
