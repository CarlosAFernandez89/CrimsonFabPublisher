"""The four listing operations, orchestrated.

Mirrors `ScanService`: it holds the paths, returns frozen result objects, never
logs and never raises for a user-facing problem. The UI layer decides what to
show and when to run it.

check  - compose, validate, audit and diff. Writes nothing.
build  - check, then write every bundle and the status table.
diff   - carried inside a check result; there is no cheaper standalone form.
accept - record what was submitted, refusing while errors stand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..models import EngineInfo, PluginInfo
from ..validation import Issue
from . import compose as compose_mod
from . import diffing, pluginaudit, render, requires, schema, source, validate
from .zipfacts import ZipFacts, read_zip, zip_path_for


@dataclass(frozen=True)
class ListingRow:
    """Everything the UI needs about one plugin's listing."""

    plugin: PluginInfo
    listing: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    issues: tuple[Issue, ...] = ()
    audit: tuple[Issue, ...] = ()
    report: diffing.DiffReport = field(
        default_factory=lambda: diffing.DiffReport(status=diffing.NEW)
    )
    tier: str = "premium"
    publishable: bool = True
    authored: dict = field(default_factory=dict)
    requirements: requires.Requirements | None = None
    source_error: str = ""

    @property
    def plugin_id(self) -> str:
        return self.plugin.name

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.level == "error")

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.level == "warning")

    @property
    def audit_errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.audit if i.level == "error")

    @property
    def blocked(self) -> bool:
        return bool(self.errors)

    @property
    def blockers(self) -> list[str]:
        return [i.key or i.message[:40] for i in self.errors]


@dataclass(frozen=True)
class ListingScan:
    rows: tuple[ListingRow, ...] = ()
    listings_dir: Path | None = None
    error: str = ""

    def row(self, plugin_id: str) -> ListingRow | None:
        return next((r for r in self.rows if r.plugin_id == plugin_id), None)

    @property
    def publishable(self) -> tuple[ListingRow, ...]:
        return tuple(r for r in self.rows if r.publishable)


@dataclass(frozen=True)
class AcceptResult:
    accepted: tuple[str, ...] = ()
    refused: tuple[tuple[str, str], ...] = ()
    fields_recorded: int = 0


class ListingService:
    """Composes, validates and diffs listings. Holds no Qt and no state."""

    def __init__(
        self,
        listings_dir: Path,
        output_dir: Path,
        *,
        faq_review: bool = True,
        changelog_review: bool = True,
    ):
        # Keep the configured text as well as the path: Path("") normalises
        # to ".", so an unset folder is indistinguishable from the cwd once it
        # has been through Path.
        self.configured = str(listings_dir or "").strip()
        self.listings_dir = Path(self.configured)
        self.output_dir = Path(output_dir)
        self.specs = schema.build_specs(faq_review, changelog_review)

    # -------------------------------------------------------------- internals
    @property
    def media_root(self) -> Path:
        return source.media_root(self.listings_dir)

    def _zip_facts(
        self, plugin: PluginInfo, engine: EngineInfo | None
    ) -> ZipFacts | None:
        if engine is None:
            return None
        return read_zip(zip_path_for(self.output_dir, plugin, engine))

    # ------------------------------------------------------------------ check
    def check(
        self,
        plugins: list[PluginInfo],
        engine: EngineInfo | None = None,
        dev_platforms: list[str] | None = None,
        on_progress=None,
    ) -> ListingScan:
        """Compose, validate, audit and diff every plugin. Writes nothing."""
        if not self.configured or not self.listings_dir.is_dir():
            return ListingScan(
                error=(
                    "No listings folder yet. Choose one in Settings and keep it "
                    "under version control."
                )
            )

        defaults_loaded = source.load_defaults(self.listings_dir)
        rows: list[ListingRow] = []

        # Built once: rglobbing the engine's plugin tree for module owners is
        # far too slow to repeat per plugin.
        owners = requires.module_owners(
            requires.engine_uplugins(engine.root if engine else None)
            + [p.uplugin_path for p in plugins]
        )
        suite_names = {p.name for p in plugins}
        # Anything owning a module that is not one of ours ships with the engine.
        engine_plugin_names = {
            owner for owner in owners.values() if owner not in suite_names
        }

        for index, plugin in enumerate(plugins):
            if on_progress is not None and on_progress(index, len(plugins)) is False:
                break

            loaded = source.load_source(self.listings_dir, plugin.name)
            authored = loaded.data
            defaults = defaults_loaded.data
            publishable = compose_mod.is_publishable(authored, defaults)
            tier = compose_mod.tier_of(authored, defaults)

            if not publishable:
                rows.append(
                    ListingRow(
                        plugin=plugin,
                        tier=tier,
                        publishable=False,
                        authored=authored,
                    )
                )
                continue

            error = loaded.error or defaults_loaded.error
            resolved = requires.resolve(
                plugin, owners, engine_plugin_names, suite_names
            )
            listing, provenance = compose_mod.compose(
                plugin,
                authored,
                defaults,
                self.media_root,
                dev_platforms=dev_platforms,
                zip_facts=self._zip_facts(plugin, engine),
                requirements=resolved,
            )
            issues = validate.check_listing(
                listing,
                unknown_keys=source.unknown_keys(authored),
                stray_braces=source.stray_braces(authored),
                # Silences merge the way every other field does: a suite-wide
                # default applies unless the plugin overrides it.
                silence={
                    **(defaults.get("silence") or {}),
                    **(authored.get("silence") or {}),
                },
                descriptor_engine_version=plugin.engine_version,
                source_error=error,
            )
            snapshot = source.load_snapshot(self.listings_dir, plugin.name)
            previous = (snapshot.data or {}).get("listing") if snapshot.exists else None
            report = diffing.diff_listing(
                previous, listing, self.specs, is_live=plugin.is_live
            )

            rows.append(
                ListingRow(
                    plugin=plugin,
                    listing=listing,
                    provenance=provenance,
                    issues=tuple(issues),
                    audit=tuple(pluginaudit.audit_plugin(plugin)),
                    report=report,
                    tier=tier,
                    publishable=True,
                    authored=authored,
                    requirements=resolved,
                    source_error=error,
                )
            )

        return ListingScan(rows=tuple(rows), listings_dir=self.listings_dir)

    # ------------------------------------------------------------------ build
    def build(self, scan: ListingScan) -> list[Path]:
        """Write every bundle plus the status table. The only writing verb."""
        written: list[Path] = []
        rows = scan.publishable
        for row in rows:
            out_dir = render.bundle_dir(self.output_dir, row.plugin_id)
            render.write_bundle(
                row.listing,
                row.report,
                out_dir,
                self.media_root,
                meta={
                    "plugin_path": str(row.plugin.path),
                    "plugin_version": row.plugin.version_name,
                },
            )
            written.append(out_dir)

        table = render.status_markdown(
            [
                render.status_row(r.listing, r.report, r.tier, r.blockers)
                for r in rows
            ]
        )
        status = self.listings_dir / source.STATUS_FILENAME
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text(table, encoding="utf-8")
        written.append(status)
        return written

    # ----------------------------------------------------------------- accept
    def accept(
        self, rows: list[ListingRow], force: bool = False, submitted_at: str = ""
    ) -> AcceptResult:
        """Record what was submitted, so the next diff has a baseline.

        Refuses while a listing has errors: a snapshot of copy that Fab would
        have rejected is a baseline that makes every later diff misleading.
        """
        accepted: list[str] = []
        refused: list[tuple[str, str]] = []
        fields = 0

        for row in rows:
            if row.blocked and not force:
                refused.append(
                    (
                        row.plugin_id,
                        f"{len(row.errors)} error(s) - fix them or accept with "
                        f"force",
                    )
                )
                continue
            source.save_snapshot(
                self.listings_dir,
                row.plugin_id,
                {
                    "submitted_at": submitted_at,
                    "submitted_version": row.plugin.version_name,
                    "listing_url": row.plugin.listing_url,
                    "listing": row.listing,
                },
            )
            accepted.append(row.plugin_id)
            fields += len(diffing.leaf_paths(row.listing, self.specs))

        return AcceptResult(
            accepted=tuple(accepted),
            refused=tuple(refused),
            fields_recorded=fields,
        )
