"""The description markup, and turning it into what Fab's editor accepts.

Fab's description is rich text - headings, bullets, bold, links - but it does
not render markdown source: pasted `**` shows up as two asterisks. So the copy
is written in a deliberately tiny markup and converted here, once, into the
HTML its editor keeps on paste, or into plain text for anywhere else.

The subset is exactly:

    ## Heading            -> <h4>
    - item                -> <ul><li>, consecutive lines grouped
    **bold**              -> <strong>
    [text](https://...)   -> <a>

Blank lines separate paragraphs. Anything else is reported by `problems()`
rather than guessed at, so the validator and the renderer agree on one list.

Pure functions only - no Qt, no files.
"""

from __future__ import annotations

import html
import re

_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(\S(?:.*?\S)?)\*\*")
_HEADING = "## "
_BULLET = "- "


def _inline_html(text: str) -> str:
    out = html.escape(text, quote=False)
    out = _LINK.sub(
        lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', out
    )
    return _BOLD.sub(r"<strong>\1</strong>", out)


def _inline_plain(text: str) -> str:
    text = _LINK.sub(r"\1 (\2)", text)
    return _BOLD.sub(r"\1", text)


def to_html(text: str) -> str:
    """The description as the HTML fragment Fab's editor keeps on paste.

    An empty paragraph goes before every heading but the first block: top
    sellers space their sections that way, and Fab keeps empty paragraphs.
    """
    out: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append("<p>" + "<br>".join(paragraph) + "</p>")
            paragraph.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
            items.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(_HEADING):
            flush()
            if out:
                out.append("<p></p>")
            out.append(f"<h4>{_inline_html(line[len(_HEADING):].strip())}</h4>")
        elif line.startswith(_BULLET):
            if paragraph:
                flush()
            items.append(_inline_html(line[len(_BULLET):].strip()))
        elif not line:
            flush()
        else:
            if items:
                flush()
            paragraph.append(_inline_html(line))
    flush()
    return "".join(out)


def to_plain(text: str) -> str:
    """The description with the markup taken out, for plain-text pastes."""
    lines = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith(_HEADING):
            line = line.lstrip()[len(_HEADING):]
        lines.append(_inline_plain(line))
    return "\n".join(lines)


def problems(text: str) -> list[str]:
    """Markup outside the supported subset, which would reach Fab literally."""
    found = []
    if "`" in text:
        found.append("backticks")
    lines = text.splitlines()
    if any(
        line.lstrip().startswith("#") and not line.lstrip().startswith(_HEADING)
        for line in lines
    ):
        found.append("headings other than '## '")
    stripped = [_BOLD.sub("", _LINK.sub("", line)) for line in lines]
    if any("**" in line for line in stripped):
        found.append("unclosed bold markers")
    if any("](" in line for line in stripped):
        found.append("link syntax that is not [text](https://...)")
    return found
