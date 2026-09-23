"""The drafting prompt, and reading a model's reply back.

The contract that matters here: the prompt is generated from the rule table, so
the model is told exactly what the validator will check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fabpublisher.dependencies import classify_dependencies
from fabpublisher.discovery import discover_plugins
from fabpublisher.listing import fabrules
from fabpublisher.listing.prompt import (
    draft_prompt,
    extract_json_block,
    merge_draft,
)


@pytest.fixture
def plugin(suite: Path):
    found = discover_plugins(suite)
    classify_dependencies(found, {"GameplayAbilities"})
    return next(p for p in found if p.name == "Ability")


# -------------------------------------------------------------------- prompt
def test_every_copy_rule_reaches_the_prompt(plugin):
    """The anti-drift guard: add a rule, and the model is told about it."""
    text = draft_prompt(plugin)

    for rule in fabrules.rules_for(fabrules.COPY):
        assert rule.text in text, f"{rule.id} never reaches the model"


def test_documented_rules_are_cited_in_the_prompt(plugin):
    text = draft_prompt(plugin)

    assert "Fab 1.8.4.a/b" in text
    assert "Fab 4.3.6.1.d" in text


def test_prompt_states_the_plugin_facts(plugin):
    text = draft_prompt(plugin, folders=["Source", "Resources"])

    assert "Ability" in text
    assert "5.8.0" in text
    assert "Source, Resources" in text


def test_prompt_names_the_prerequisites_when_they_are_known(plugin):
    """So the drafter can write about them instead of inventing them."""
    from fabpublisher.listing.requires import Requirements

    text = draft_prompt(
        plugin,
        requirements=Requirements(suite=("Common",), engine=("GameplayAbilities",)),
    )

    assert "Required plugins the customer must install: Common" in text
    assert "Engine plugins used: GameplayAbilities" in text


def test_prompt_lays_out_the_crimson_template(plugin):
    text = draft_prompt(plugin)

    for section in ("✨ Features", "🛠️ Getting Started", "📋 Requirements", "⚠️ Limitations"):
        assert section in text
    assert "Fab collapses the description" in text
    # An example is the instruction that actually lands.
    assert "--- example start ---" in text


def test_prompt_teaches_only_the_supported_markup(plugin):
    text = draft_prompt(plugin)

    assert 'A line starting "## " is a section heading.' in text
    assert "No other markup: no backticks" in text


def test_prompt_offers_only_known_urls_for_the_link_bar(plugin):
    plugin.docs_url = "https://docs.example.com"
    text = draft_prompt(plugin)

    assert "Documentation URL: https://docs.example.com" in text
    assert "Support URL: (none)" in text
    assert "never invent one" in text


def test_prompt_keeps_pictures_out_of_the_description(plugin):
    """Images belong to the media gallery; the description is text alone."""
    text = draft_prompt(plugin)

    assert "Do not refer to images, screenshots or figures" in text
    assert "[IMAGE:" not in text


def test_prompt_allows_emoji_but_asks_for_restraint(plugin):
    text = draft_prompt(plugin)

    assert "sparingly" in text
    assert "professional developer tool" in text


def test_prompt_offers_the_category_vocabulary(plugin):
    assert "Gameplay Features" in draft_prompt(plugin)


def test_prompt_shows_existing_copy_so_it_is_not_thrown_away(plugin):
    text = draft_prompt(plugin, {"title": "Ability System"})

    assert "Ability System" in text
    assert "worth keeping" in text


def test_prompt_says_so_when_nothing_is_written_yet(plugin):
    assert "Nothing has been written yet." in draft_prompt(plugin)


def test_prompt_demands_bare_json(plugin):
    text = draft_prompt(plugin)

    assert "single JSON object and nothing else" in text
    assert "no code fence" in text


# ------------------------------------------------------------------ extract
def test_extracts_a_bare_object():
    assert extract_json_block('{"title": "X"}') == {"title": "X"}


def test_extracts_json_wrapped_in_prose_and_a_fence():
    reply = 'Sure! Here you go:\n```json\n{"title": "X", "tags": ["a"]}\n```\nHope that helps.'

    assert extract_json_block(reply) == {"title": "X", "tags": ["a"]}


def test_handles_nested_objects_and_braces_inside_strings():
    reply = '{"description": {"what": "Use {id} carefully"}, "tags": []}'

    parsed = extract_json_block(reply)

    assert parsed["description"]["what"] == "Use {id} carefully"


def test_skips_a_broken_object_and_finds_the_next():
    reply = 'noise {not json at all} then {"title": "X"}'

    assert extract_json_block(reply) == {"title": "X"}


@pytest.mark.parametrize(
    "reply", ["", "no braces here", "{unclosed", "[1, 2, 3]"], ids=["empty", "prose", "unclosed", "array"]
)
def test_returns_none_when_there_is_no_object(reply):
    """None means "keep the raw text", never "silently discard it"."""
    assert extract_json_block(reply) is None


# -------------------------------------------------------------------- merge
def test_merge_fills_only_what_is_unwritten():
    authored = {"title": "Mine", "tags": []}
    draft = {"title": "Theirs", "tags": ["a", "b"]}

    merged = merge_draft(authored, draft)

    assert merged["title"] == "Mine", "a re-run must not clobber your own words"
    assert merged["tags"] == ["a", "b"]


def test_overwrite_replaces_authored_copy():
    merged = merge_draft({"title": "Mine"}, {"title": "Theirs"}, overwrite=True)

    assert merged["title"] == "Theirs"


def test_description_blocks_merge_individually():
    authored = {"description": {"what": "Mine."}}
    draft = {"description": {"what": "Theirs.", "how": "Do this."}}

    merged = merge_draft(authored, draft)

    assert merged["description"] == {"what": "Mine.", "how": "Do this."}


def test_merge_ignores_keys_outside_the_draftable_set():
    merged = merge_draft({}, {"price": {"personal": 1}, "title": "X"})

    assert "price" not in merged
    assert merged["title"] == "X"


def test_merge_does_not_mutate_the_original():
    authored = {"description": {"what": "Mine."}}

    merge_draft(authored, {"description": {"how": "New."}})

    assert authored == {"description": {"what": "Mine."}}
