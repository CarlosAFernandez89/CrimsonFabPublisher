"""Run the Claude CLI to draft listing copy, streaming as it goes.

The rule is that it must never look hung, and the app already solved that twice
for RunUAT: stream stdout line by line, batch the lines, keep an elapsed
counter running, and make cancel kill the whole process tree. This is the same
shape as `BuildWorker`, deliberately - a second mechanism would be a second
thing to get wrong.

The prompt goes in on **stdin**, not argv: Windows caps a command line at
32,767 characters and a listing prompt plus existing copy can approach that,
and stdin sidesteps every quoting question at the same time.

Follow-up rounds need the model to remember its own draft, and the CLI already
persists sessions on disk - so there is nothing to keep running here. Each
plugin gets a UUID the first time it is drafted; after that `--resume <uuid>`
continues that conversation, and "make the description shorter" means something
without re-sending everything.
"""

from __future__ import annotations

import shutil
import subprocess
import threading

from PySide6.QtCore import QThread, Signal

from ..builder import _NO_WINDOW, kill_process_tree

#: What we run when the user has not named a specific binary.
DEFAULT_EXE = "claude"


def resolve_cli(configured: str = "") -> str | None:
    """The Claude executable to run, or None when there is none to find."""
    if configured.strip():
        found = shutil.which(configured.strip())
        return found or (configured.strip() if _looks_like_path(configured) else None)
    return shutil.which(DEFAULT_EXE)


def _looks_like_path(value: str) -> bool:
    return "/" in value or "\\" in value


class DraftWorker(QThread):
    line = Signal(str)
    finished_draft = Signal(str, str)  # full stdout, error ("" when fine)

    def __init__(
        self,
        executable: str,
        prompt: str,
        parent=None,
        args: tuple[str, ...] = ("-p",),
        session_id: str = "",
        resume: bool = False,
    ):
        super().__init__(parent)
        # argv is a parameter so a test can stand in for the CLI without
        # patching run() out from under the thread.
        command = [executable, *args]
        if session_id:
            # --resume continues the stored conversation; --session-id names a
            # new one so the follow-up knows where to come back to.
            command += ["--resume", session_id] if resume else ["--session-id", session_id]
        self._command = command
        self._prompt = prompt
        self._cancelled = False
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True
        with self._lock:
            proc = self._proc
        if proc is not None:
            kill_process_tree(proc)

    def _track(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._proc = proc
        # A cancel that landed between launch and here must still take effect.
        if self._cancelled:
            kill_process_tree(proc)

    def run(self) -> None:
        collected: list[str] = []
        try:
            proc = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                # One ordered stream, exactly as run_build does, so a warning
                # cannot arrive out of order with the output it refers to.
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=_NO_WINDOW,
            )
        except OSError as exc:
            self.finished_draft.emit("", f"Could not start {self._command[0]}: {exc}")
            return

        self._track(proc)
        try:
            if proc.stdin is not None:
                proc.stdin.write(self._prompt)
                proc.stdin.close()
            if proc.stdout is not None:
                for raw in proc.stdout:
                    text = raw.rstrip("\n")
                    collected.append(text)
                    self.line.emit(text)
            code = proc.wait()
        except OSError as exc:
            self.finished_draft.emit("\n".join(collected), f"Draft failed: {exc}")
            return
        finally:
            with self._lock:
                self._proc = None

        output = "\n".join(collected)
        if self._cancelled:
            self.finished_draft.emit(output, "Cancelled.")
        elif code != 0:
            self.finished_draft.emit(output, f"Claude exited with code {code}.")
        else:
            self.finished_draft.emit(output, "")
