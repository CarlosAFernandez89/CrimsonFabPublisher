"""Write the paste-ready bundle for one listing.

Everything here is a Python string constant rather than a bundled template
file, deliberately: the frozen exe resolves bundled data through
`sys._MEIPASS`, and a missing entry in the PyInstaller spec fails silently at
runtime. The theme already degrades invisibly that way once; this feature does
not add a second chance to.

`listing.json` is the diff subject and must be byte-identical across two runs
over unchanged inputs. Everything non-deterministic - the clock, absolute
paths, the engine label - goes in `meta.json`, which is never diffed.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import markup
from .diffing import CLEAN, NEW, PENDING, DiffReport
from .source import write_json

BUNDLE_DIRNAME = "_Listings"

#: Repeated at the top of every checklist because it is the single largest
#: behavioural risk in the workflow: an edit made in Fab's form is an edit the
#: snapshot never sees, and from then on the diff lies.
NEVER_EDIT_IN_FORM = (
    "**Do not edit copy in the Fab form.** Change the listing file and re-run "
    "Build instead. Anything typed straight into Fab is invisible to the "
    "snapshot, and every diff after that is wrong."
)


def bundle_dir(output_dir: Path, plugin_id: str) -> Path:
    return Path(output_dir) / BUNDLE_DIRNAME / plugin_id


def _blocks(listing: dict) -> dict[str, str]:
    """The description split back into its three areas for per-block pasting."""
    description = listing.get("description") or {}
    text = str(description.get("text") or "")
    names = list(description.get("blocks") or [])
    ranges = list(description.get("ranges") or [])
    return {name: text[start:end] for name, (start, end) in zip(names, ranges)}


def _description_text(listing: dict) -> str:
    return str((listing.get("description") or {}).get("text") or "")


def _description_html(listing: dict) -> str:
    """A page to open in a browser and copy from, formatting and all."""
    return (
        '<!DOCTYPE html>\n<html><head><meta charset="utf-8">'
        "<title>Description</title></head>\n<body>\n"
        + markup.to_html(_description_text(listing))
        + "\n</body></html>\n"
    )


#: Tags come out of Fab's own picker, so the generated list is a set of
#: candidates to try - not settings that will definitely apply.
TAGS_HEADER = (
    "# Suggested tags - search each one in Fab's tag picker.\n"
    "# The picker only offers tags Fab already knows, so anything that does\n"
    "# not come up cannot be used: drop it here and from the listing file, or\n"
    "# the snapshot will claim a tag the listing does not have.\n"
)


def _tags_text(listing: dict) -> str:
    # One per line: Fab's picker takes them one at a time, so this is the
    # shape you actually paste from.
    return TAGS_HEADER + "\n".join(str(t) for t in listing.get("tags") or [])


def _technical_text(listing: dict) -> str:
    technical = listing.get("technical") or {}
    stats = listing.get("stats") or {}
    rows = [
        ("Engine versions", ", ".join(technical.get("engine_versions") or [])),
        (
            "Required plugins",
            ", ".join(technical.get("required_plugins") or []) or "none",
        ),
        (
            "Engine plugins used",
            ", ".join(technical.get("engine_plugins") or []) or "none",
        ),
        ("Development platforms", ", ".join(technical.get("dev_platforms") or [])),
        ("Target platforms", ", ".join(technical.get("target_platforms") or [])),
        ("Distribution method", technical.get("distribution") or ""),
        ("Number of Blueprints", str(stats.get("blueprints", 0))),
        ("Number of C++ classes", str(stats.get("cpp_classes", 0))),
    ]
    return "\n".join(f"{label}: {value}" for label, value in rows)


def _faq_markdown(listing: dict) -> str:
    entries = listing.get("faq") or []
    if not entries:
        return "_No FAQ entries._\n"
    return "\n".join(
        f"### {entry.get('q', '')}\n\n{entry.get('a', '')}\n" for entry in entries
    )


def _changelog_markdown(listing: dict) -> str:
    entries = listing.get("changelog") or []
    if not entries:
        return "_No changelog entries._\n"
    out = []
    for entry in entries:
        out.append(f"### {entry.get('version', '')}")
        for note in entry.get("notes") or []:
            out.append(f"- {note}")
        out.append("")
    return "\n".join(out)


def _listing_markdown(listing: dict) -> str:
    license_ = listing.get("license") or {}
    media = listing.get("media") or {}
    declarations = listing.get("declarations") or {}
    fab = listing.get("fab") or {}

    lines = [
        f"# {listing.get('title', '')}",
        "",
        NEVER_EDIT_IN_FORM,
        "",
        "## Product type",
        listing.get("product_type", ""),
        "",
        "## Category",
        listing.get("category", "") or "_not set_",
        "",
        "## License and price",
        f"{license_.get('type', '')} - personal "
        f"${license_.get('price_personal', 0):.2f}, professional "
        f"${license_.get('price_professional', 0):.2f} "
        f"{license_.get('currency', '')}",
        "",
        "## Description",
        "",
        _description_text(listing) or "_not set_",
        "",
        "## Tags",
        ", ".join(listing.get("tags") or []) or "_not set_",
        "",
        "## Technical details",
        "",
        _technical_text(listing),
        "",
        "## Media",
        f"Thumbnail: {(media.get('thumbnail') or {}).get('source', '')}",
        f"Gallery: {media.get('gallery_count', 0)} item(s), upload in the order "
        f"they are numbered in this bundle's media/ folder",
        "",
        "## Declarations",
    ]
    lines += [
        f"- {label}: {'Yes' if declarations.get(key) else 'No'}"
        for key, label in (
            ("mature", "Mature content"),
            ("no_ai", "Disallow use by Generative AI Programs"),
            ("generative_ai", "Created with generative AI"),
            ("promotional", "Includes promotional content"),
            ("edc_forum_post", "Create an EDC forum post"),
        )
    ]
    lines += [
        "",
        "## FAQ",
        "",
        _faq_markdown(listing),
        "## Changelog",
        "",
        _changelog_markdown(listing),
        "## Fab listing",
        f"{fab.get('listing_url') or '_not submitted_'}",
        "",
    ]
    return "\n".join(lines)


def _changed_section(report: DiffReport) -> list[str]:
    if report.status in (NEW, CLEAN) or not report.changes:
        return []
    lines = ["## Changed since last submission", ""]
    if report.review_changes or report.unclassified_changes:
        lines.append("**These re-enter Fab review:**")
        lines += [
            f"- [ ] `{c.path}` - {c.summary}"
            for c in report.review_changes + report.unclassified_changes
        ]
        lines.append("")
    if report.instant_changes:
        lines.append("**These apply instantly:**")
        lines += [f"- [ ] `{c.path}` - {c.summary}" for c in report.instant_changes]
        lines.append("")
    lines.append("Everything else is unchanged - leave it alone.")
    lines.append("")
    return lines


def _checklist_markdown(listing: dict, report: DiffReport) -> str:
    fab = listing.get("fab") or {}
    live = bool(fab.get("is_live"))
    title = listing.get("title", "")

    lines = [
        f"# Submission checklist - {title}",
        "",
        NEVER_EDIT_IN_FORM,
        "",
    ]
    if live:
        lines += [
            "> **This listing already exists on Fab - update it, do not create "
            "a new one.**",
            ">",
            f"> {fab.get('listing_url', '')}",
            "",
        ]
    else:
        lines += ["> This listing has never been submitted. Create it.", ""]

    lines += _changed_section(report)

    lines += [
        "## Form, in order",
        "",
        f"- [ ] Title - paste from `description.txt`'s heading or: {title}",
        f"- [ ] Product type - {listing.get('product_type', '')}",
        f"- [ ] Category - {listing.get('category', '')}",

        "- [ ] License and price - see `listing.md`",
        "- [ ] Description - press *Copy description* in the app (or open "
        "`description.html` in a browser and copy it), then paste, so the "
        "headings, bullets and bold arrive formatted",
        "- [ ] Tags - search each line of `tags.txt` in the picker; delete any "
        "it does not offer from the listing file too",
        "- [ ] Thumbnail - `media/01-thumbnail.*`",
        "- [ ] Media gallery - upload `media/` in numeric order",
        "- [ ] Product file - add the Unreal Engine format and attach the zip",
        "- [ ] Technical details - paste `technical.txt`",
        "- [ ] FAQ - `faq.md`",
        "- [ ] Changelog - `changelog.md`",
        "- [ ] Declarations - see `listing.md`",
        "- [ ] **Submit for review**",
        "",
        "## Then",
        "",
        "- [ ] Come back to the Listings page and press **Accept**, so the "
        "snapshot records what you just submitted.",
        "",
    ]
    return "\n".join(lines)


def _copy_media(listing: dict, media_root: Path, dest: Path) -> list[str]:
    """Numbered copies in upload order, so the gallery is one drag from here."""
    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.iterdir():
        if stale.is_file():
            stale.unlink()

    copied: list[str] = []
    media = listing.get("media") or {}
    thumbnail = media.get("thumbnail") or {}
    entries = []
    if thumbnail.get("sha256"):
        entries.append(("thumbnail", thumbnail.get("source", "")))
    for item in media.get("gallery") or []:
        entries.append((Path(item.get("source", "")).stem, item.get("source", "")))

    for index, (label, rel) in enumerate(entries, start=1):
        origin = Path(media_root) / rel
        if not origin.is_file():
            continue
        target = dest / f"{index:02d}-{label}{origin.suffix.lower()}"
        shutil.copyfile(origin, target)
        copied.append(target.name)
    return copied


def write_bundle(
    listing: dict,
    report: DiffReport,
    out_dir: Path,
    media_root: Path,
    *,
    meta: dict | None = None,
) -> Path:
    """Write every artifact for one listing and return the folder."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    blocks = _blocks(listing)
    files = {
        "listing.md": _listing_markdown(listing),
        "description.txt": markup.to_plain(_description_text(listing)) + "\n",
        "description.html": _description_html(listing),
        "tags.txt": _tags_text(listing) + "\n",
        "technical.txt": _technical_text(listing) + "\n",
        "faq.md": _faq_markdown(listing),
        "changelog.md": _changelog_markdown(listing),
        "checklist.md": _checklist_markdown(listing, report),
    }
    for name, text in files.items():
        (out_dir / name).write_text(text, encoding="utf-8")

    if "how" in blocks:
        (out_dir / "description-how.txt").write_text(blocks["how"], encoding="utf-8")

    copied = _copy_media(listing, media_root, out_dir / "media")

    # The diff subject. Ordered, sorted and free of anything non-deterministic.
    write_json(out_dir / "listing.json", listing)

    # Everything the listing deliberately does not carry lives here, and this
    # file is never compared.
    write_json(
        out_dir / "meta.json",
        {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "media_root": str(Path(media_root).resolve()),
            "media_copied": copied,
            "diff_status": report.status,
            **(meta or {}),
        },
    )
    return out_dir


# ------------------------------------------------------------------- overview


def _status_word(report: DiffReport, blocked: bool) -> str:
    if blocked:
        return "BLOCKED"
    return {NEW: "NEW", PENDING: "PENDING", CLEAN: "clean"}.get(
        report.status, "changed"
    )


def status_markdown(rows: list[dict]) -> str:
    """The cross-listing table, regenerated on every build.

    Version-controlled, so it must be as deterministic as `listing.json`: no
    timestamps, no counts that move on their own. A file that churns on every
    build is a file nobody reads.
    """
    lines = [
        "# Fab listing status",
        "",
        NEVER_EDIT_IN_FORM,
        "",
        "| Listing | Tier | Personal | Professional | Live | Status | Review | "
        "Instant | Blocked by |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in sorted(rows, key=lambda r: r["plugin_id"]):
        lines.append(
            "| {plugin_id} | {tier} | {personal} | {professional} | {live} | "
            "{status} | {review} | {instant} | {blocked_by} |".format(**row)
        )
    lines.append("")
    return "\n".join(lines)


def status_row(
    listing: dict, report: DiffReport, tier: str, blockers: list[str]
) -> dict:
    license_ = listing.get("license") or {}
    fab = listing.get("fab") or {}
    return {
        "plugin_id": listing.get("plugin_id", ""),
        "tier": tier,
        "personal": f"${license_.get('price_personal', 0):.2f}",
        "professional": f"${license_.get('price_professional', 0):.2f}",
        "live": fab.get("listing_url") or "not submitted",
        "status": _status_word(report, bool(blockers)),
        "review": len(report.review_changes) + len(report.unclassified_changes),
        "instant": len(report.instant_changes),
        "blocked_by": "; ".join(blockers[:3]) if blockers else "-",
    }


def read_listing(path: Path) -> dict | None:
    """Read back a generated listing.json, or None if it is not there."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
