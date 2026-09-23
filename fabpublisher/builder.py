"""Orchestrate RunUAT BuildPlugin and produce FAB-ready submission zips."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import threading
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path

from .models import (
    ALL_PLATFORMS,
    BuildResult,
    EngineInfo,
    Platform,
    PluginInfo,
    platform_uat_name,
    platforms_to_list,
)
from .shipfilter import ShipFilter

# `-StrictIncludes` is what satisfies the no-PCH / no-unity requirement: UE 5.8's
# BuildPluginCommand turns it into `-NoPCH -NoSharedPCH -DisableUnity` for UBT.
# BuildPlugin has no pass-through for arbitrary UBT arguments, so this flag is the
# only way to ask for it.
#
# The host platform is deliberately left in (no `-NoHostPlatform`): it is what
# compiles the editor target, and since Binaries/ never ships, catching a broken
# editor-only module is the whole reason to run a build at all.
#
# Two flags from the original PackagePlugin.bat are gone because UE 5.8 no longer
# parses them: `-Rocket`, and `-CreateSubFolder` (renamed `-PackageAppendPluginSubdir`).
# The rename is not adopted — a subfolder would push the .uplugin out of the zip
# root, which is exactly where FAB requires it.
BUILD_FLAGS = ("-StrictIncludes",)

LogFn = Callable[[str], None]
ProcFn = Callable[[subprocess.Popen], None]

#: Keep taskkill from flashing a console window out of the windowed exe.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def submission_zip_name(plugin: PluginInfo, engine: EngineInfo) -> str:
    """The exact file a successful build produces."""
    return f"{plugin.name}_{engine.label}_Submission.zip"


def kill_process_tree(proc: subprocess.Popen) -> None:
    """Stop RunUAT *and* its descendants.

    `proc.kill()` only reaps cmd.exe — UBT, MSBuild and every cl.exe it spawned
    keep running with no window to close them from. taskkill /T walks the tree.
    """
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
                creationflags=_NO_WINDOW,
            )
        else:
            proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def platform_arg(platforms: Platform) -> str:
    return "+".join(platform_uat_name(p) for p in platforms_to_list(platforms))


def build_command(
    engine: EngineInfo,
    plugin: PluginInfo,
    out_dir: Path,
    platforms: Platform,
    uplugin_path: Path | None = None,
    dependencies: Sequence[Path] = (),
) -> list[str]:
    """The exact RunUAT invocation for one plugin.

    `uplugin_path` overrides the descriptor to build, which is how a real build
    points RunUAT at the staged copy instead of the plugin's own folder.

    `dependencies` are descriptors of sibling plugins this one needs. BuildPlugin
    compiles into a throwaway host project containing only the target plugin, so
    a suite dependency is invisible unless named here — UBT otherwise stops with
    "Unable to find plugin". Engine plugins resolve on their own and must not be
    listed.
    """
    return [
        str(engine.runuat_path),
        "BuildPlugin",
        f"-Plugin={uplugin_path or plugin.uplugin_path}",
        f"-Package={out_dir}",
        *(f"-Dependencies={dep}" for dep in dependencies),
        *BUILD_FLAGS,
        f"-TargetPlatforms={platform_arg(platforms)}",
    ]


def _drop_readonly(func, path, _exc) -> None:
    """rmtree error hook: clear the read-only bit, then retry the delete."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def force_rmtree(path: Path, log: LogFn | None = None) -> None:
    """Delete a tree even when it holds read-only files.

    Version control (Perforce here) leaves working files read-only, `copy2`
    carries that bit into the staging copy, and Windows will not delete a
    read-only file. A plain `ignore_errors=True` hides that: the survivor stays
    on disk and the *next* build dies copying over it. So clear the bit and
    retry, and say so if anything still survives.
    """
    path = Path(path)
    if not path.exists():
        return
    shutil.rmtree(path, onexc=_drop_readonly)
    if path.exists() and log is not None:
        log(f"Warning: could not fully remove {path}")


#: Compiled suite plugins live here, under the output folder, so a dependent
#: build links against the same artifact its dependency shipped rather than
#: recompiling that dependency's source inside every host project.
BUILT_DIRNAME = "_Built"


def built_dir(output_dir: Path) -> Path:
    return Path(output_dir) / BUILT_DIRNAME


def built_uplugin(output_dir: Path, name: str) -> Path:
    """Descriptor of an already-built suite plugin, if it has been deposited."""
    return built_dir(output_dir) / name / f"{name}.uplugin"


def missing_built_dependencies(
    output_dir: Path, dependencies: Sequence[PluginInfo]
) -> list[str]:
    """Names of suite dependencies that have not been built yet, in order."""
    return [
        dep.name
        for dep in dependencies
        if not built_uplugin(output_dir, dep.name).is_file()
    ]


def deposit_built(out_dir: Path, output_dir: Path, name: str, log: LogFn = print) -> Path:
    """Publish a finished build into the built-dependency folder.

    Deliberately unfiltered: dependents need `Binaries/` and the generated
    headers under `Intermediate/Build`, which the submission zip strips.
    """
    target = built_dir(output_dir) / name
    force_rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(out_dir, target)
    log(f"Published {name} to {BUILT_DIRNAME}/ for dependent builds")
    return target


def stage_plugin(
    plugin: PluginInfo, stage_dir: Path, ship_filter: ShipFilter, log: LogFn = print
) -> Path:
    """Copy the plugin into `stage_dir`, dropping anything the filter excludes.

    Building from a filtered copy means excluded files are gone before the
    compiler ever sees them, rather than being stripped at zip time — nothing
    can leak into a submission by being forgotten later. The plugin's own folder
    is never modified, and because the defaults drop `Binaries/` and
    `Intermediate/`, the staged copy is also a guaranteed clean build.
    """
    stage_dir = Path(stage_dir)
    force_rmtree(stage_dir, log)

    copied = 0
    excluded = 0
    for path in sorted(plugin.path.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(plugin.path)
        if ship_filter.should_exclude(rel.as_posix()):
            excluded += 1
            continue
        target = stage_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1

    log(f"Staged {copied} files ({excluded} excluded) for build")
    return stage_dir / plugin.uplugin_path.name


def package_zip(
    source_dir: Path, dest_zip: Path, ship_filter: ShipFilter, log: LogFn = print
) -> Path:
    """Zip `source_dir` into `dest_zip`, dropping anything the filter excludes."""
    source_dir = Path(source_dir)
    dest_zip = Path(dest_zip)
    # The output folder is user-configured and may not exist yet; without this a
    # perfectly good multi-minute compile is thrown away at the last step.
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    if dest_zip.exists():
        dest_zip.unlink()

    included = 0
    excluded = 0
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(source_dir).as_posix()
            if ship_filter.should_exclude(rel):
                excluded += 1
                continue
            zf.write(path, rel)
            included += 1

    log(f"Packaged {included} files ({excluded} excluded) -> {dest_zip.name}")
    return dest_zip


#: UAT names the log its UBT child is about to write, and does it early —
#: measured at t=1.6s on a build that then went quiet until t=92s.
_LOG_FILE_LINE = re.compile(r"^\s*Log file:\s*(.+\.txt)\s*$")

#: `[12/98] Compile [x64] Foo.cpp` — the per-action counter. Must stay in step
#: with the parser in `ui/build_progress.py`, which turns it into a fraction.
_ACTION_LINE = re.compile(r"^\[\d+/\d+\]")

#: Re-read interval for the tailed log. Fine enough for a smooth bar, and
#: nothing next to a compile that runs for minutes.
_TAIL_INTERVAL = 0.25


class _ProgressTail:
    """Follow the log UBT writes while it is compiling.

    UAT runs UBT as its own child and holds that output until the child exits,
    so our pipe hears nothing for the length of a pass — measured at 83s of
    silence on a 112s build, with all 103 action lines then arriving inside a
    single 100ms window. A progress bar fed from the pipe can only sit still
    and then snap.

    UBT writes those same lines to its own log as the work happens: first
    action on disk at 19s against 96s on the pipe. So the file is the only
    live source, and this follows whichever one the current pass announced.
    """

    def __init__(self, emit: LogFn):
        self._emit = emit
        self._path: Path | None = None
        self._pos = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def follow(self, path: Path) -> None:
        """Switch to a pass's log; each pass announces its own."""
        with self._lock:
            self._path = path
            # These files outlive the run that wrote them, so start at the end
            # and count only growth — otherwise the previous build's actions
            # replay as this one's progress.
            try:
                self._pos = path.stat().st_size if path.is_file() else 0
            except OSError:
                self._pos = 0
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(_TAIL_INTERVAL):
            self._drain()
        self._drain()  # last look, so the tail of the final pass is not lost

    def _drain(self) -> None:
        with self._lock:
            path, pos = self._path, self._pos
        if path is None:
            return
        try:
            size = path.stat().st_size
            if size < pos:
                pos = 0  # rewritten for this run
            if size == pos:
                return
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(pos)
                chunk = handle.read()
                pos = handle.tell()
        except OSError:
            return  # mid-write, or gone; the next tick picks it up
        with self._lock:
            if path is not self._path:
                return  # a newer pass took over while we were reading
            self._pos = pos
        for line in chunk.splitlines():
            self._emit(line)


def package_dir(work_root: Path, plugin_name: str) -> Path:
    """RunUAT's `-Package` folder; its HostProject is where UBT compiles."""
    return Path(work_root) / f"{plugin_name}_Build"


def run_build(
    engine: EngineInfo,
    plugin: PluginInfo,
    platforms: Platform,
    work_root: Path,
    ship_filter: ShipFilter,
    output_dir: Path,
    log: LogFn = print,
    dry_run: bool = False,
    on_process_started: ProcFn | None = None,
    dependencies: Sequence[PluginInfo] = (),
    on_progress_line: LogFn | None = None,
) -> BuildResult:
    """Compile one plugin and write its submission zip.

    `dependencies` are the sibling plugins this one needs, transitive closure
    included. Each must already have been built and published to the
    `_Built` folder; the build is refused otherwise, so a dependent never
    silently compiles against something other than what its dependency ships.

    `on_progress_line` receives UBT's `[n/m]` action lines, each exactly once,
    from whichever source saw it first — the tailed log while a pass is in
    flight, the pipe otherwise. Kept separate from `log` because the two
    sources deliver the same lines at very different times.

    Returns a BuildResult; on failure the zip step is skipped.
    """
    work_root = Path(work_root)
    out_dir = package_dir(work_root, plugin.name)
    stage_dir = work_root / f"{plugin.name}_Staged"
    dep_paths = [built_uplugin(output_dir, dep.name) for dep in dependencies]

    if dry_run:
        cmd = build_command(
            engine,
            plugin,
            out_dir,
            platforms,
            stage_dir / plugin.uplugin_path.name,
            dep_paths,
        )
        log("[dry-run] " + subprocess.list2cmdline(cmd))
        return BuildResult(plugin.name, True, None, "Dry run (not executed)")

    missing = missing_built_dependencies(output_dir, dependencies)
    if missing:
        return BuildResult(
            plugin.name,
            False,
            None,
            f"Dependencies not built yet: {', '.join(missing)}. "
            f"Build them first so they are published to {BUILT_DIRNAME}/.",
        )

    try:
        staged_uplugin = stage_plugin(plugin, stage_dir, ship_filter, log=log)
    except OSError as exc:
        force_rmtree(stage_dir)
        return BuildResult(plugin.name, False, None, f"Failed to stage plugin: {exc}")

    if dependencies:
        log(f"Using built dependencies: {', '.join(d.name for d in dependencies)}")
    cmd = build_command(
        engine, plugin, out_dir, platforms, staged_uplugin, dep_paths
    )

    force_rmtree(out_dir, log)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        log("> " + subprocess.list2cmdline(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(engine.root),
                # RunUAT is a .bat, so without this the windowed exe pops an
                # empty console for the life of the build.
                creationflags=_NO_WINDOW,
            )
        except OSError as exc:
            return BuildResult(
                plugin.name, False, None, f"Failed to launch RunUAT: {exc}"
            )

        # Hand the handle out so a cancel can actually reach the process tree.
        if on_process_started is not None:
            on_process_started(proc)

        # Each action line must reach progress once, whichever source got it
        # first — the pipe replays everything the tail already delivered.
        seen_actions: set[str] = set()
        seen_lock = threading.Lock()

        def forward(line: str) -> None:
            text = line.strip()
            if on_progress_line is None or not _ACTION_LINE.match(text):
                return
            with seen_lock:
                if text in seen_actions:
                    return
                seen_actions.add(text)
            on_progress_line(text)

        tail = _ProgressTail(forward)
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                text = line.rstrip("\n")
                log(text)
                announced = _LOG_FILE_LINE.match(text)
                if announced:
                    tail.follow(Path(announced.group(1).strip()))
                else:
                    forward(text)
            code = proc.wait()
        finally:
            tail.stop()

        if code != 0:
            return BuildResult(
                plugin.name, False, None, f"Build failed (exit code {code})", code
            )

        # Publish before packaging: the compile is what dependents need, and it
        # should be available to them even if the zip step later fails.
        try:
            deposit_built(out_dir, output_dir, plugin.name, log=log)
        except OSError as exc:
            return BuildResult(
                plugin.name, False, None, f"Compiled, but publishing failed: {exc}"
            )

        dest_zip = Path(output_dir) / submission_zip_name(plugin, engine)
        try:
            package_zip(out_dir, dest_zip, ship_filter, log=log)
        except OSError as exc:
            # The compile is already done and correct; say so, rather than
            # letting this escape and take the whole build worker down with it.
            return BuildResult(
                plugin.name, False, None, f"Compiled, but packaging failed: {exc}"
            )
    finally:
        # Every exit path from here on leaves both scratch trees behind
        # otherwise, including the early returns above.
        force_rmtree(out_dir)
        force_rmtree(stage_dir)

    return BuildResult(plugin.name, True, dest_zip, "Build succeeded", 0)
