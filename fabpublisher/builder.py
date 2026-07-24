"""Orchestrate RunUAT BuildPlugin and produce FAB-ready submission zips."""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from collections.abc import Callable
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

# Flags mirror the original PackagePlugin.bat so build behaviour is unchanged.
BUILD_FLAGS = ("-Rocket", "-StrictIncludes", "-NoHostPlatform", "-CreateSubFolder")

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
    engine: EngineInfo, plugin: PluginInfo, out_dir: Path, platforms: Platform
) -> list[str]:
    """The exact RunUAT invocation for one plugin."""
    return [
        str(engine.runuat_path),
        "BuildPlugin",
        f"-Plugin={plugin.uplugin_path}",
        f"-Package={out_dir}",
        *BUILD_FLAGS,
        f"-TargetPlatforms={platform_arg(platforms)}",
    ]


def package_zip(
    source_dir: Path, dest_zip: Path, ship_filter: ShipFilter, log: LogFn = print
) -> Path:
    """Zip `source_dir` into `dest_zip`, dropping anything the filter excludes."""
    source_dir = Path(source_dir)
    dest_zip = Path(dest_zip)
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
) -> BuildResult:
    """Compile one plugin and write its submission zip.

    Returns a BuildResult; on failure the zip step is skipped.
    """
    out_dir = Path(work_root) / f"{plugin.name}_Build"
    cmd = build_command(engine, plugin, out_dir, platforms)

    if dry_run:
        log("[dry-run] " + subprocess.list2cmdline(cmd))
        return BuildResult(plugin.name, True, None, "Dry run (not executed)")

    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    log("> " + subprocess.list2cmdline(cmd))
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(engine.root),
        )
    except OSError as exc:
        return BuildResult(plugin.name, False, None, f"Failed to launch RunUAT: {exc}")

    # Hand the handle out so a cancel can actually reach the process tree.
    if on_process_started is not None:
        on_process_started(proc)

    assert proc.stdout is not None
    for line in proc.stdout:
        log(line.rstrip("\n"))
    code = proc.wait()

    if code != 0:
        shutil.rmtree(out_dir, ignore_errors=True)
        return BuildResult(
            plugin.name, False, None, f"Build failed (exit code {code})", code
        )

    dest_zip = Path(output_dir) / submission_zip_name(plugin, engine)
    try:
        package_zip(out_dir, dest_zip, ship_filter, log=log)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)

    return BuildResult(plugin.name, True, dest_zip, "Build succeeded", 0)
