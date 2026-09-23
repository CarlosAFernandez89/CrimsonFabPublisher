"""FAB pre-flight checks per plugin."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import DependencyKind, PluginInfo

MAX_SUBMISSION_BYTES = 15 * 1024 * 1024 * 1024  # 15 GB FAB limit


@dataclass
class Issue:
    level: str  # "error" | "warning"
    message: str
    #: The listing key, descriptor key or requirement section that fixes this.
    #: Empty for issues that are not tied to one editable field.
    key: str = ""


def _engine_major_minor(version: str) -> tuple[str, ...]:
    return tuple(version.split(".")[:2]) if version else ()


def validate_plugin(
    plugin: PluginInfo, engine_version: str | None = None
) -> list[Issue]:
    """Structural and dependency checks for a single plugin.

    `plugin.dependencies` must already be classified (see dependencies module)
    for the external-dependency warnings to be meaningful.
    """
    issues: list[Issue] = []

    if not (plugin.path / "Source").is_dir():
        issues.append(Issue("error", "No Source/ directory (FAB requires a code module)"))
    if not plugin.modules:
        issues.append(Issue("error", "No code modules declared in .uplugin"))

    if plugin.can_contain_content and not (plugin.path / "Content").is_dir():
        issues.append(
            Issue("warning", "CanContainContent is true but no Content/ folder exists")
        )

    if (
        engine_version
        and plugin.engine_version
        and _engine_major_minor(plugin.engine_version)
        != _engine_major_minor(engine_version)
    ):
        issues.append(
            Issue(
                "warning",
                f"Plugin targets EngineVersion {plugin.engine_version}, "
                f"building against {engine_version}",
            )
        )

    for dep in plugin.dependencies:
        if dep.kind == DependencyKind.EXTERNAL:
            issues.append(
                Issue(
                    "warning",
                    f"External dependency '{dep.name}' is not in the engine or this "
                    f"suite; the build will fail unless it is installed",
                )
            )

    return issues


def check_zip_size(zip_path: Path) -> Issue | None:
    """Warn if a produced submission zip exceeds the FAB size limit."""
    try:
        size = Path(zip_path).stat().st_size
    except OSError:
        return None
    if size > MAX_SUBMISSION_BYTES:
        gb = size / (1024**3)
        return Issue("warning", f"Submission zip is {gb:.1f} GB (FAB limit is 15 GB)")
    return None
