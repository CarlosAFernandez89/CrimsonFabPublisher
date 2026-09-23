"""The four operations end to end: check, build, accept, and diff-after-accept.

The cycle these tests pin is the point of the whole feature - accept records
what was submitted, and the next check reports only what has moved since.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fabpublisher.dependencies import classify_dependencies
from fabpublisher.discovery import discover_plugins
from fabpublisher.listing import source
from fabpublisher.listing.diffing import CHANGED, CLEAN, NEW, PENDING
from fabpublisher.listing.service import ListingService


@pytest.fixture
def env(suite: Path, listings: Path, tmp_path: Path):
    plugins = discover_plugins(suite)
    classify_dependencies(plugins, {"GameplayAbilities"})
    # Make Common live, so its diff exercises the changed/clean path rather
    # than sitting in PENDING forever.
    common = next(p for p in plugins if p.name == "Common")
    common.fab_url = "https://www.fab.com/listings/11111111-2222-3333-4444-555555555555"

    source.write_json(
        listings / "_defaults.json",
        {
            "category": "Engine Tools",
            "tags": ["unreal", "plugin", "tools", "runtime", "gameplay"],
            "media": {"thumbnail": "{id}/thumbnail.png"},
            "technical": {"dev_platforms": ["Windows"], "target_platforms": ["Win64"]},
            "silence": {"gallery_thumbnail_only": True},
        },
    )
    svc = ListingService(listings, tmp_path / "out")
    return svc, plugins, listings, common


def check(svc, plugins):
    return svc.check(plugins, dev_platforms=["Windows"])


# ------------------------------------------------------------------- check
def test_check_covers_every_plugin_and_writes_nothing(env):
    svc, plugins, listings, _ = env

    scan = check(svc, plugins)

    assert {r.plugin_id for r in scan.rows} == {"Common", "Ability", "Core"}
    assert not (svc.output_dir).exists()
    assert not (listings / source.STATUS_FILENAME).exists()


def test_a_plugin_with_no_authored_file_still_resolves(env):
    """Bootstrap: every discovered plugin gets a row from day one."""
    svc, plugins, _, _ = env

    row = check(svc, plugins).row("Ability")

    assert row.listing["title"] == "Ability"
    assert row.report.status == NEW


def test_publish_false_opts_a_plugin_out_of_the_run(env):
    svc, plugins, listings, _ = env
    source.write_json(listings / "Core.json", {"publish": False})

    scan = check(svc, plugins)

    assert scan.row("Core").publishable is False
    assert {r.plugin_id for r in scan.publishable} == {"Common", "Ability"}


def test_an_unknown_authored_key_blocks_the_listing(env):
    svc, plugins, listings, _ = env
    source.write_json(listings / "Common.json", {"tagz": ["oops"]})

    row = check(svc, plugins).row("Common")

    assert row.blocked
    assert "tagz" in {i.key for i in row.errors}


def test_malformed_json_is_reported_not_raised(env):
    svc, plugins, listings, _ = env
    (listings / "Common.json").write_text("{ not json", encoding="utf-8")

    row = check(svc, plugins).row("Common")

    assert row.blocked
    assert "not valid JSON" in row.errors[0].message


def test_a_silence_in_the_defaults_applies_to_every_plugin(env):
    """Silences merge like any other field, or a suite-wide one does nothing."""
    svc, plugins, listings, _ = env

    warnings = check(svc, plugins).row("Common").warnings

    # _defaults.json silences gallery_thumbnail_only for the whole suite.
    assert not any("only the thumbnail" in w.message for w in warnings)


def test_a_plugin_can_override_a_default_silence(env):
    svc, plugins, listings, _ = env
    source.write_json(
        listings / "Common.json", {"silence": {"gallery_thumbnail_only": False}}
    )

    warnings = check(svc, plugins).row("Common").warnings

    assert any("only the thumbnail" in w.message for w in warnings)


def test_the_audit_runs_alongside_the_listing_check(env):
    """Package problems and copy problems are separate questions."""
    svc, plugins, _, _ = env

    row = check(svc, plugins).row("Ability")

    # Ability depends on Common, a user-made plugin (Fab 4.3.6.d).
    assert any("4.3.6.d" in i.message for i in row.audit_errors)


def test_an_unconfigured_listings_folder_is_reported_not_failed(tmp_path):
    """config.json stores "" until the user picks a folder."""
    svc = ListingService("", tmp_path / "out")

    assert "Choose one in Settings" in svc.check([]).error


def test_a_configured_but_missing_folder_is_reported(tmp_path):
    svc = ListingService(tmp_path / "gone", tmp_path / "out")

    assert svc.check([]).error


# ------------------------------------------------------------------- build
def test_build_writes_bundles_and_the_status_table(env):
    svc, plugins, listings, _ = env

    svc.build(check(svc, plugins))

    assert (svc.output_dir / "_Listings" / "Common" / "listing.json").is_file()
    assert (listings / source.STATUS_FILENAME).is_file()


def test_build_skips_plugins_that_opted_out(env):
    svc, plugins, listings, _ = env
    source.write_json(listings / "Core.json", {"publish": False})

    svc.build(check(svc, plugins))

    assert not (svc.output_dir / "_Listings" / "Core").exists()


# ------------------------------------------------------------ accept + diff
def test_accept_then_check_reports_clean(env):
    """The cycle the feature exists for."""
    svc, plugins, _, _ = env
    scan = check(svc, plugins)
    assert scan.row("Common").report.status == NEW

    result = svc.accept([scan.row("Common")], submitted_at="2026-09-09")

    assert result.accepted == ("Common",)
    assert result.fields_recorded > 0
    assert check(svc, plugins).row("Common").report.status == CLEAN


def test_an_instant_edit_after_accept_does_not_trigger_review(env):
    svc, plugins, listings, _ = env
    svc.accept([check(svc, plugins).row("Common")], submitted_at="2026-09-09")

    source.write_json(listings / "Common.json", {"tags": ["extra"]})
    report = check(svc, plugins).row("Common").report

    assert report.status == CHANGED
    assert [c.path for c in report.instant_changes] == ["tags"]
    assert report.triggers_review is False


def test_a_copy_edit_after_accept_does_trigger_review(env):
    svc, plugins, listings, _ = env
    svc.accept([check(svc, plugins).row("Common")], submitted_at="2026-09-09")

    source.write_json(
        listings / "Common.json", {"description": {"what": "A brand new sentence."}}
    )
    report = check(svc, plugins).row("Common").report

    assert report.triggers_review is True
    assert "description.text" in {c.path for c in report.review_changes}


def test_a_rebuilt_thumbnail_is_detected_by_digest(env, tmp_path):
    """Proves binaries are tracked by hash, not by name or timestamp."""
    from .conftest import write_png

    svc, plugins, listings, _ = env
    svc.accept([check(svc, plugins).row("Common")], submitted_at="2026-09-09")

    write_png(listings / "media" / "Common" / "thumbnail.png", 1920, 1081)
    report = check(svc, plugins).row("Common").report

    assert "media.thumbnail" in {c.path for c in report.review_changes}


def test_a_snapshot_for_a_listing_that_is_not_live_reads_pending(env):
    svc, plugins, _, _ = env
    svc.accept([check(svc, plugins).row("Ability")], submitted_at="2026-09-09")

    assert check(svc, plugins).row("Ability").report.status == PENDING


def test_accept_refuses_while_errors_stand(env):
    """A snapshot of copy Fab would reject makes every later diff misleading."""
    svc, plugins, listings, _ = env
    source.write_json(listings / "Common.json", {"tags": []})
    (listings / "media" / "Common" / "thumbnail.png").unlink()

    row = check(svc, plugins).row("Common")
    assert row.blocked

    result = svc.accept([row])

    assert result.accepted == ()
    assert result.refused[0][0] == "Common"


def test_force_accepts_past_errors(env):
    svc, plugins, listings, _ = env
    (listings / "media" / "Common" / "thumbnail.png").unlink()

    row = check(svc, plugins).row("Common")
    result = svc.accept([row], force=True)

    assert result.accepted == ("Common",)


def test_the_snapshot_records_what_was_submitted(env):
    svc, plugins, listings, common = env

    svc.accept([check(svc, plugins).row("Common")], submitted_at="2026-09-09")
    snapshot = source.load_snapshot(listings, "Common").data

    assert snapshot["submitted_at"] == "2026-09-09"
    assert snapshot["submitted_version"] == "1.0"
    assert snapshot["listing_url"] == common.fab_url
    assert snapshot["listing"]["plugin_id"] == "Common"
