"""Compare a listing against the last one submitted.

The report's job is to answer one question: *what do I have to touch, and will
it cost me a review cycle?* So every change is classified against
`schema.SPECS`, and a path with no spec is reported UNCLASSIFIED and counted as
review-triggering. Failing safe costs a review that might not have been needed;
failing open costs a listing that silently went stale.

Summaries stay short on purpose. A description diff reports its line counts and
three sample lines, never the whole body - a report you have to scroll is a
report you stop reading.
"""

from __future__ import annotations

import difflib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from . import schema

NEW = "new"
PENDING = "pending"
CHANGED = "changed"
CLEAN = "clean"

#: Sample lines shown for a text change, and how wide each may be.
_TEXT_SAMPLES = 3
_TEXT_WIDTH = 100

#: Keys that carry an item's position rather than its identity.
_POSITION_KEYS = ("index",)


@dataclass(frozen=True)
class Change:
    path: str
    review: bool
    compare: str
    summary: str
    detail: tuple[str, ...] = ()
    #: True when no spec classified this path, so review was assumed.
    unclassified: bool = False


@dataclass(frozen=True)
class DiffReport:
    status: str
    changes: tuple[Change, ...] = ()
    provenance_note: str = field(default="", compare=False)

    @property
    def review_changes(self) -> tuple[Change, ...]:
        return tuple(c for c in self.changes if c.review and not c.unclassified)

    @property
    def instant_changes(self) -> tuple[Change, ...]:
        return tuple(c for c in self.changes if not c.review)

    @property
    def unclassified_changes(self) -> tuple[Change, ...]:
        return tuple(c for c in self.changes if c.unclassified)

    @property
    def triggers_review(self) -> bool:
        return any(c.review for c in self.changes)


def _truncate(text: str, width: int = _TEXT_WIDTH) -> str:
    text = text.strip()
    return text if len(text) <= width else text[: width - 1] + "…"


def leaf_paths(obj: object, specs: dict[str, schema.FieldSpec]) -> list[str]:
    """Every diffable path in a listing.

    Descends until it reaches a path that has a spec, which is what lets
    `media.thumbnail` be compared as one digest rather than four scalars.
    Ignored paths are dropped entirely.
    """
    paths: list[str] = []

    def walk(node: object, path: str) -> None:
        if path and schema.is_ignored(path):
            return
        if path and path in specs:
            paths.append(path)
            return
        if isinstance(node, dict):
            for key in node:
                walk(node[key], f"{path}.{key}" if path else key)
            return
        if path:
            paths.append(path)

    walk(obj, "")
    return paths


def _value_at(obj: object, path: str) -> object:
    node = obj
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _identity(item: object) -> str:
    """A stable name for a list item, ignoring where it currently sits."""
    if isinstance(item, dict):
        for key in ("source", "q", "version", "name"):
            if key in item:
                value = item[key]
                return (
                    PurePosixPath(str(value)).name if key == "source" else str(value)
                )
        stripped = {k: v for k, v in item.items() if k not in _POSITION_KEYS}
        return json.dumps(stripped, sort_keys=True, ensure_ascii=False)
    return str(item)


def _scalar_summary(before: object, after: object) -> str:
    return f"{before!r} -> {after!r}" if before != after else ""


def _set_summary(before: object, after: object) -> str:
    old = sorted(str(v) for v in before or [])
    new = sorted(str(v) for v in after or [])
    if old == new:
        return ""
    added = [v for v in new if v not in old]
    removed = [v for v in old if v not in new]
    parts = [f"+{v}" for v in added] + [f"-{v}" for v in removed]
    return "  ".join(parts)


def _list_summary(before: object, after: object) -> tuple[str, tuple[str, ...]]:
    old = list(before or [])
    new = list(after or [])
    old_ids = [_identity(i) for i in old]
    new_ids = [_identity(i) for i in new]
    if old_ids == new_ids:
        return "", ()

    old_counts, new_counts = Counter(old_ids), Counter(new_ids)
    added = sorted((new_counts - old_counts).elements())
    removed = sorted((old_counts - new_counts).elements())
    # A reorder must read as a move, not as an add plus a remove.
    moved = [
        f"{name} #{old_ids.index(name) + 1} -> #{new_ids.index(name) + 1}"
        for name in new_ids
        if name in old_ids and old_ids.index(name) != new_ids.index(name)
    ]

    summary = f"{len(old)} -> {len(new)} items"
    if not added and not removed and moved:
        summary = f"{len(new)} items reordered"

    detail = (
        [f"+ {name} at #{new_ids.index(name) + 1}" for name in added]
        + [f"- {name}" for name in removed]
        + [f"~ moved {m}" for m in dict.fromkeys(moved)]
    )
    return summary, tuple(detail[:_TEXT_SAMPLES])


def _text_summary(before: object, after: object) -> tuple[str, tuple[str, ...]]:
    old = str(before or "").splitlines()
    new = str(after or "").splitlines()
    if old == new:
        return "", ()
    added = [l for l in difflib.unified_diff(old, new, n=0) if l.startswith("+") and not l.startswith("+++")]
    removed = [l for l in difflib.unified_diff(old, new, n=0) if l.startswith("-") and not l.startswith("---")]
    summary = f"+{len(added)} / -{len(removed)} lines"
    detail = tuple(
        _truncate(line[0] + " " + line[1:])
        for line in (added + removed)[:_TEXT_SAMPLES]
    )
    return summary, detail


def _kb(value: object) -> str:
    return f"{int(value or 0) / 1024:.0f} KB"


def _digest_summary(before: object, after: object) -> str:
    old = before if isinstance(before, dict) else {}
    new = after if isinstance(after, dict) else {}
    if before is None and after is not None:
        return f"added ({_kb(new.get('bytes'))})"
    if before is not None and after is None:
        return "removed"
    old_sha, new_sha = str(old.get("sha256", "")), str(new.get("sha256", ""))
    if old_sha == new_sha and old.get("bytes") == new.get("bytes"):
        return ""
    return (
        f"sha {old_sha[:8] or '-'} -> {new_sha[:8] or '-'}, "
        f"{_kb(old.get('bytes'))} -> {_kb(new.get('bytes'))}"
    )


def _compare(
    spec: schema.FieldSpec | None, path: str, before: object, after: object
) -> Change | None:
    mode = spec.compare if spec else "scalar"
    detail: tuple[str, ...] = ()

    if mode == "set":
        summary = _set_summary(before, after)
    elif mode == "list":
        summary, detail = _list_summary(before, after)
    elif mode == "text":
        summary, detail = _text_summary(before, after)
    elif mode == "digest":
        summary = _digest_summary(before, after)
    else:
        summary = _scalar_summary(before, after)

    if not summary:
        return None
    return Change(
        path=path,
        review=spec.review if spec else True,
        compare=mode,
        summary=summary,
        detail=detail,
        unclassified=spec is None,
    )


def diff_listing(
    previous: dict | None,
    current: dict,
    specs: dict[str, schema.FieldSpec] | None = None,
    *,
    is_live: bool = False,
) -> DiffReport:
    """Compare the current listing against the last accepted snapshot.

    `previous` is None when nothing has been submitted yet. A snapshot that
    exists for a listing which is not live is reported PENDING - recorded but
    not yet on Fab - which is information, not an error.
    """
    specs = specs if specs is not None else schema.SPECS

    if previous is None:
        return DiffReport(status=NEW)

    paths = sorted(set(leaf_paths(previous, specs)) | set(leaf_paths(current, specs)))
    changes = [
        change
        for path in paths
        if (
            change := _compare(
                schema.spec_for(path, specs),
                path,
                _value_at(previous, path),
                _value_at(current, path),
            )
        )
        is not None
    ]

    if not is_live:
        status = PENDING
    else:
        status = CHANGED if changes else CLEAN
    return DiffReport(status=status, changes=tuple(changes))
