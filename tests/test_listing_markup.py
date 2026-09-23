"""The description markup: what Fab's editor gets, and what is refused."""

from __future__ import annotations

import pytest

from fabpublisher.listing.markup import problems, to_html, to_plain

SAMPLE = (
    "**Inventory for any character.**\n"
    "\n"
    "[Docs](https://x.dev/docs) • [Support](https://x.dev/help)\n"
    "\n"
    "## ✨ Features\n"
    "\n"
    "- **Stacking** — items merge.\n"
    "- **Replication** — built in.\n"
    "\n"
    "## 🛠️ Getting Started\n"
    "\n"
    "Add the component.\n"
    "Then play."
)


# -------------------------------------------------------------------- html
def test_headings_become_h4_with_a_spacer_before_them():
    html = to_html(SAMPLE)

    assert "<p></p><h4>✨ Features</h4>" in html
    assert "<p></p><h4>🛠️ Getting Started</h4>" in html


def test_a_leading_heading_gets_no_spacer():
    assert to_html("## Title\n\nBody").startswith("<h4>Title</h4>")


def test_consecutive_bullets_form_one_list():
    html = to_html(SAMPLE)

    assert html.count("<ul>") == 1
    assert "<li><strong>Stacking</strong> — items merge.</li>" in html


def test_links_and_bold_render():
    html = to_html(SAMPLE)

    assert "<p><strong>Inventory for any character.</strong></p>" in html
    assert '<a href="https://x.dev/docs">Docs</a>' in html


def test_adjacent_lines_share_a_paragraph():
    assert "<p>Add the component.<br>Then play.</p>" in to_html(SAMPLE)


def test_text_is_escaped():
    html = to_html("Use <T> & friends")

    assert html == "<p>Use &lt;T&gt; &amp; friends</p>"


def test_a_list_ends_where_prose_starts():
    html = to_html("- one\nprose")

    assert html == "<ul><li>one</li></ul><p>prose</p>"


# ------------------------------------------------------------------- plain
def test_plain_text_drops_the_markup_but_keeps_the_shape():
    plain = to_plain(SAMPLE)

    assert "**" not in plain
    assert "##" not in plain
    assert "✨ Features" in plain
    assert "- Stacking — items merge." in plain
    assert "Docs (https://x.dev/docs)" in plain


def test_text_without_markup_is_unchanged():
    assert to_plain("Line one\n\nLine two") == "Line one\n\nLine two"


# ---------------------------------------------------------------- problems
def test_the_supported_subset_has_no_problems():
    assert problems(SAMPLE) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Call `Init()`", "backticks"),
        ("### Deep heading", "headings other than '## '"),
        ("# Top heading", "headings other than '## '"),
        ("**never closed", "unclosed bold markers"),
        ("[docs](docs.html)", "link syntax that is not [text](https://...)"),
    ],
    ids=["backtick", "h3", "h1", "bold", "relative-link"],
)
def test_unsupported_markup_is_named(text, expected):
    assert expected in problems(text)
