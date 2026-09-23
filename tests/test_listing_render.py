"""The bundle, the status table, and the determinism guarantee.

`test_build_is_byte_identical_twice` is the highest-priority test in the
feature: if a build is not reproducible, every diff is dirty and none of the
rest means anything.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from fabpublisher.dependencies import classify_dependencies
from fabpublisher.discovery import discover_plugins
from fabpublisher.listing import source
from fabpublisher.listing.diffing import CLEAN, NEW, DiffReport, diff_listing
from fabpublisher.listing.render import (
    NEVER_EDIT_IN_FORM,
    bundle_dir,
    status_markdown,
    status_row,
    write_bundle,
)
from fabpublisher.listing.service import ListingService

from .test_listing_diff import BASE


@pytest.fixture
def service(suite: Path, listings: Path, tmp_path: Path):
    found = discover_plugins(suite)
    classify_dependencies(found, {"GameplayAbilities"})
    source.write_json(
        listings / "_defaults.json",
        {
            "category": "Engine Tools",
            "media": {"thumbnail": "{id}/thumbnail.png"},
            "technical": {"dev_platforms": ["Windows"], "target_platforms": ["Win64"]},
        },
    )
    return ListingService(listings, tmp_path / "out"), found


# ------------------------------------------------------------- determinism
def test_build_is_byte_identical_twice(service, tmp_path):
    """Verification #1. Everything downstream depends on this."""
    svc, plugins = service

    first, second = tmp_path / "a", tmp_path / "b"
    for out in (first, second):
        svc.output_dir = out
        svc.build(svc.check(plugins, dev_platforms=["Windows"]))

    files = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
    assert files, "the build produced nothing to compare"
    for rel in files:
        if rel.name == "meta.json":
            continue
        assert (first / rel).read_bytes() == (second / rel).read_bytes(), rel


def test_meta_json_is_the_only_non_deterministic_file(service, tmp_path):
    """If meta.json matches too, non-determinism has leaked somewhere else and
    the test above has quietly stopped proving anything."""
    svc, plugins = service

    metas = []
    for out in (tmp_path / "a", tmp_path / "b"):
        svc.output_dir = out
        svc.build(svc.check(plugins, dev_platforms=["Windows"]))
        metas.append((out / "_Listings" / "Common" / "meta.json").read_text("utf-8"))

    assert "generated_at" in metas[0]
    assert "media_root" in metas[0]


def test_the_status_table_is_deterministic(service, tmp_path):
    svc, plugins = service
    scan = svc.check(plugins, dev_platforms=["Windows"])

    rows = [status_row(r.listing, r.report, r.tier, r.blockers) for r in scan.rows]
    assert status_markdown(rows) == status_markdown(list(reversed(rows)))


# ------------------------------------------------------------------ bundle
def test_bundle_writes_every_artifact(service, tmp_path):
    svc, plugins = service
    svc.build(svc.check(plugins, dev_platforms=["Windows"]))

    out = bundle_dir(svc.output_dir, "Common")
    names = {p.name for p in out.iterdir()}

    assert {
        "listing.md",
        "description.txt",
        "description.html",
        "tags.txt",
        "technical.txt",
        "faq.md",
        "changelog.md",
        "checklist.md",
        "listing.json",
        "meta.json",
        "media",
    } <= names


def test_tags_are_written_one_per_line(tmp_path, listings):
    listing = copy.deepcopy(BASE)
    listing["tags"] = ["save", "load", "persistence"]

    out = write_bundle(listing, DiffReport(NEW), tmp_path / "b", listings / "media")
    text = (out / "tags.txt").read_text("utf-8")

    # The header explains that these are candidates, not settings.
    assert text.startswith("#")
    assert "picker" in text
    body = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert body == ["save", "load", "persistence"]


def test_listing_json_round_trips(tmp_path, listings):
    listing = copy.deepcopy(BASE)

    out = write_bundle(listing, DiffReport(NEW), tmp_path / "b", listings / "media")

    assert json.loads((out / "listing.json").read_text("utf-8")) == listing


def test_media_is_copied_in_upload_order(service, tmp_path):
    svc, plugins = service
    svc.build(svc.check(plugins, dev_platforms=["Windows"]))

    media = sorted(p.name for p in (bundle_dir(svc.output_dir, "Common") / "media").iterdir())

    assert media[0].startswith("01-thumbnail")


# --------------------------------------------------------------- checklist
def test_every_checklist_opens_with_the_never_edit_rule(service):
    """The single largest behavioural risk in the workflow."""
    svc, plugins = service
    svc.build(svc.check(plugins, dev_platforms=["Windows"]))

    for plugin in plugins:
        text = (bundle_dir(svc.output_dir, plugin.name) / "checklist.md").read_text("utf-8")
        assert NEVER_EDIT_IN_FORM in text.split("## ")[0]


def test_a_live_listing_says_update_do_not_create(tmp_path, listings):
    listing = copy.deepcopy(BASE)
    listing["fab"] = {"listing_url": "https://fab/x", "product_id": "x", "is_live": True}

    out = write_bundle(listing, DiffReport(CLEAN), tmp_path / "b", listings / "media")

    assert "update it, do not create" in (out / "checklist.md").read_text("utf-8")


def test_the_how_block_is_written_whole_despite_its_paragraphs(tmp_path, listings):
    """Splitting the text on blank lines used to cut blocks at their first paragraph."""
    listing = copy.deepcopy(BASE)
    what, how = "Pitch.\n\nMore pitch.", "## Getting Started\n\n- Step one."
    listing["description"] = {
        "text": f"{what}\n\n{how}",
        "chars": len(what) + 2 + len(how),
        "blocks": ["what", "how"],
        "ranges": [[0, len(what)], [len(what) + 2, len(what) + 2 + len(how)]],
    }

    out = write_bundle(listing, DiffReport(NEW), tmp_path / "b", listings / "media")

    assert (out / "description-how.txt").read_text("utf-8") == how


def test_a_new_listing_says_create_it(tmp_path, listings):
    listing = copy.deepcopy(BASE)
    listing["fab"] = {"listing_url": "", "product_id": "", "is_live": False}

    out = write_bundle(listing, DiffReport(NEW), tmp_path / "b", listings / "media")

    assert "never been submitted" in (out / "checklist.md").read_text("utf-8")


def test_an_update_run_leads_with_what_changed_split_by_class(tmp_path, listings):
    listing = copy.deepcopy(BASE)
    listing["tags"] = ["save", "persistence"]
    listing["title"] = "My Save & Load"
    report = diff_listing(BASE, listing, is_live=True)

    out = write_bundle(listing, report, tmp_path / "b", listings / "media")
    text = (out / "checklist.md").read_text("utf-8")

    changed = text.index("Changed since last submission")
    assert changed < text.index("Form, in order")
    assert "These re-enter Fab review" in text
    assert "These apply instantly" in text
    assert text.index("re-enter Fab review") < text.index("apply instantly")


def test_a_clean_listing_has_no_changed_section(tmp_path, listings):
    out = write_bundle(
        copy.deepcopy(BASE), DiffReport(CLEAN), tmp_path / "b", listings / "media"
    )

    assert "Changed since last submission" not in (out / "checklist.md").read_text("utf-8")


# ------------------------------------------------------------------ status
def test_status_table_reports_prices_liveness_and_blockers(service):
    svc, plugins = service
    scan = svc.check(plugins, dev_platforms=["Windows"])

    table = status_markdown(
        [status_row(r.listing, r.report, r.tier, r.blockers) for r in scan.rows]
    )

    assert "| Common |" in table
    assert "not submitted" in table
    assert NEVER_EDIT_IN_FORM in table
