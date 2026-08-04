"""Turn UBT's compile-action counter into a bar that actually moves.

A plugin takes minutes, so per-plugin progress alone leaves the bar frozen and
the build looks hung. UBT prints `[12/98] Compile [x64] Foo.cpp` for every
action, which is the finest-grained signal available without parsing timings.

The awkward part is that one plugin runs several UBT passes and their count is
not knowable up front — CrimsonCommon runs three (98, 49, 49 actions) because it
has Runtime, Editor and UncookedOnly modules, while an editor-only plugin runs
one. So the total is estimated as work arrives, and the reported fraction is
clamped monotonic: a growing estimate makes the bar slow down, never rewind.
"""

from __future__ import annotations

import re

#: `[12/98] Compile [x64] Foo.cpp` — the counter UBT emits per build action.
_ACTION = re.compile(r"^\[(\d+)/(\d+)\]")

#: Assume roughly half of another pass may still be coming. Without some
#: allowance the first pass alone would fill the whole segment and then sit
#: still for every later pass; with too much, the bar barely moves.
_UNSEEN_PASS_ALLOWANCE = 0.5

#: Never let estimated progress claim the plugin is finished — only actually
#: finishing it does that.
_CEILING = 0.98


def parse_action(line: str) -> tuple[int, int] | None:
    """Extract `(done, total)` from a UBT action line, if it is one."""
    match = _ACTION.match(line.strip())
    if not match:
        return None
    done, total = int(match.group(1)), int(match.group(2))
    return (done, total) if total > 0 else None


class PluginProgress:
    """Monotonic 0..1 progress within a single plugin's build."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._finished_actions = 0   # actions from passes already completed
        self._pass_total = 0         # action count of the pass in flight
        self._pass_done = 0
        self._fraction = 0.0

    @property
    def fraction(self) -> float:
        return self._fraction

    def note(self, line: str) -> bool:
        """Feed a log line. Returns True when the fraction moved."""
        parsed = parse_action(line)
        if parsed is None:
            return False
        done, total = parsed

        # A new pass announces itself by restarting the counter, or by carrying
        # a different total from the pass in flight.
        if total != self._pass_total or done < self._pass_done:
            self._finished_actions += self._pass_done
            self._pass_total = total
            self._pass_done = 0

        self._pass_done = done
        completed = self._finished_actions + done
        estimate = self._finished_actions + total + total * _UNSEEN_PASS_ALLOWANCE
        fraction = min(completed / estimate, _CEILING) if estimate else 0.0

        if fraction <= self._fraction:
            return False
        self._fraction = fraction
        return True


class BuildProgress:
    """Overall progress across the queue, in units of one plugin.

    `value` is a float count of finished plugins plus the fraction of the one
    currently compiling, so the caller can scale it to whatever bar resolution
    it likes.
    """

    def __init__(self, total: int = 0) -> None:
        self.total = total
        self.done = 0
        self._current = PluginProgress()

    @property
    def value(self) -> float:
        return self.done + self._current.fraction

    def start_plugin(self) -> None:
        self._current.reset()

    def finish_plugin(self, done: int) -> None:
        self.done = done
        self._current.reset()

    def note(self, line: str) -> bool:
        return self._current.note(line)
