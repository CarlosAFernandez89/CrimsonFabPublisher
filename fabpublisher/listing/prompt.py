"""Compose the Ask-Claude prompt, and read its answer back.

The requirements block is generated from `fabrules` rather than written out
here. That is the point: if the prompt restated Fab's rules in its own words it
would drift from the validator, and the model would be asked for copy the app
then rejects.

The template around it is editable, because what makes good listing copy for a
gameplay framework is not what makes it for an editor tool, and only the
publisher knows which they are shipping. `{placeholders}` are filled in; the
prose between them is theirs.

Pure functions only - no subprocess, no Qt. Running the CLI is the UI layer's
job; this module decides what to say and what came back.
"""

from __future__ import annotations

import json

from ..models import PluginInfo
from . import fabrules, schema

#: Exactly what the model must return. Anything else is discarded.
RESPONSE_SHAPE = {
    "title": "string",
    "tags": ["string"],
    "description": {"what": "string", "how": "string", "technical": "string"},
}

DRAFTABLE_KEYS = ("title", "tags", "description")

#: Fab's description is rich text, but it does not render markdown source.
#: The copy is written in the tiny markup `markup.py` converts, laid out as the
#: "Crimson Template": the skeleton every top-selling listing shares, dressed
#: between the plain developer style and the loud showcase style. Structure has
#: to be asked for explicitly, with an example, or the model returns one
#: unreadable paragraph.
DEFAULT_TEMPLATE = """You are writing the store listing copy for an Unreal Engine code plugin \
that is about to be submitted to Fab, Epic's asset marketplace.

## What the plugin is

{facts}

## What Fab requires of the copy

{requirements}

The category will be chosen from: {categories}.

## How the description is written

Fab's description is rich text: headings, bullet lists, bold and links. It
does not render markdown source, so write in this markup and nothing else -
the app converts it to Fab's formatting:

- A line starting "## " is a section heading.
- Lines starting "- " are bullet points.
- **Double asterisks** make bold.
- [Link text](https://example.com) is a link.
- A blank line separates paragraphs and sections.

No other markup: no backticks, no single asterisks or underscores, no other
heading levels. Do not refer to images, screenshots or figures, and never write
a placeholder for one. Pictures live in the media gallery, which is a separate
part of the listing - the description is text alone.

## The Crimson Template

Every description follows the same layout, in this order:

1. Hook - one bold sentence saying what the reader gets, not what the plugin
   is called internally.
2. Link bar - one line of links separated by " • ", built only from the URLs
   listed under "What the plugin is". Leave out any link that has no URL there
   and never invent one; if there are none, leave the link bar out.
3. Pitch - two or three short paragraphs: the problem the reader has, then how
   this plugin removes it, with one concrete proof point from the facts (C++
   class count, Blueprint coverage, replication, what it depends on).
4. "## ✨ Features" - six to twelve bullets, each "**Term** — one line of
   benefit". No emoji inside the bullets.
5. "## 🧩 Why It's Built This Way" - optional, one short paragraph or three
   bullets on design choices a developer will care about.
6. "## 🛠️ Getting Started" - three to five bullets, the practical steps.
7. "## 📋 Requirements" - dependencies and prerequisites, in prose.
8. "## ⚠️ Limitations" - only when there is something true to say; an honest
   caveat builds more trust than it costs.

Fab collapses the description after about ten lines, so the hook, link bar and
the start of the pitch are all most buyers read before deciding to click "Show
more". Make them carry the pitch on their own.

Headings are Title Case with exactly one leading emoji from this set: ✨ 🧩 🛠️
📋 ⚠️ 💬. This is a professional developer tool: use emoji sparingly - on
headings only, never in body text - and use no ALL CAPS, no text dividers and
no hype words. Keep paragraphs under about sixty words and the whole
description between 2,000 and 3,500 characters.

Say what the plugin does for the reader, not what its classes are called.

A well-shaped description looks like this (between the two example lines):

--- example start ---
**Drop-in inventory for any character, ready for multiplayer from the first slot.**

[Documentation](https://example.com/docs) • [Support](https://example.com/support)

Every project ends up rebuilding the same inventory: slots, stacking, weight,
and the replication bugs that come with them. It is weeks of work that ships
nothing new.

Add one component and your character has all of it. Items are data assets, so
designers add new ones without touching C++, and 40 C++ classes sit underneath
for when you do want to go deeper.

## ✨ Features

- **Fragment-based items** — behaviour composes instead of inheriting.
- **Replicated containers** — fast array serialisation, prediction included.
- **Full Blueprint API** — every operation is callable without C++.

## 🛠️ Getting Started

- Add CrimsonInventoryComponent to your pawn.
- Point it at a starting loadout data asset.
- Drive it from Blueprints or C++.

## 📋 Requirements

Needs the Gameplay Abilities plugin, which ships with the engine.
--- example end ---

## What you have to work with

{existing}

## Answer format

Reply with a single JSON object and nothing else - no preamble, no code fence,
no commentary. Its shape is exactly:

{response_shape}

Suggest tags a marketplace picker plausibly already contains - short,
conventional terms like "inventory", "multiplayer", "blueprint" - not invented
compounds or your own brand names. Anything Fab does not already know cannot be
selected, so an exotic tag is a wasted slot.

Split the description across the three fields in template order: `what` holds
the hook, link bar, pitch, Features and Why It's Built This Way; `how` holds
Getting Started; `technical` holds Requirements and Limitations. Each field is
a JSON string holding the markup above, its line breaks escaped as JSON
requires. The app appends the engine version, module list and required-plugin
list after `technical` itself, so do not repeat those.
"""

#: Placeholders the template may use, for the Settings hint.
PLACEHOLDERS = ("facts", "requirements", "categories", "existing", "response_shape")


def _facts(plugin: PluginInfo, folders: list[str], requirements=None) -> str:
    modules = ", ".join(f"{m.name} ({m.type})" for m in plugin.modules) or "none"
    rows = [
        f"Plugin id: {plugin.name}",
        f"Friendly name: {plugin.friendly_name or plugin.name}",
        f"Existing one-line description: {plugin.description or '(none)'}",
        f"Author's category: {plugin.category or '(none)'}",
        f"Engine version: {plugin.engine_version or '(unknown)'}",
        f"Documentation URL: {plugin.docs_url or '(none)'}",
        f"Support URL: {plugin.support_url or '(none)'}",
        f"Modules: {modules}",
    ]
    if requirements is not None:
        required = ", ".join(requirements.suite + requirements.unknown) or "none"
        engine = ", ".join(requirements.engine) or "none"
        rows.append(f"Required plugins the customer must install: {required}")
        rows.append(f"Engine plugins used: {engine}")
    rows += [
        f"Blueprints: {plugin.blueprint_count}",
        f"C++ classes: {plugin.cpp_class_count}",
        f"Folders present: {', '.join(folders) or 'none'}",
        f"Already listed on Fab: {'yes' if plugin.is_live else 'no'}",
    ]
    return "\n".join(rows)


def _requirements() -> str:
    """Fab's copy rules, rendered from the one table that records them."""
    return "\n".join(
        f"- {rule.text} [{rule.citation}]" for rule in fabrules.rules_for(fabrules.COPY)
    )


def _existing(authored: dict) -> str:
    kept = {k: v for k, v in authored.items() if k in DRAFTABLE_KEYS and v}
    if not kept:
        return "Nothing has been written yet."
    return (
        "Already written, and worth keeping unless you can clearly improve it:\n"
        + json.dumps(kept, indent=2, ensure_ascii=False)
    )


def fill(template: str, values: dict[str, str]) -> str:
    """Substitute `{name}` placeholders, leaving anything unknown alone.

    Deliberately not `str.format`: an edited template will contain stray braces
    sooner or later, and a KeyError that loses the user's prompt is a far worse
    outcome than a placeholder rendering literally.
    """
    result = template
    for name, value in values.items():
        result = result.replace("{" + name + "}", value)
    return result


def draft_prompt(
    plugin: PluginInfo,
    authored: dict | None = None,
    folders: list[str] | None = None,
    template: str = "",
    requirements=None,
) -> str:
    """The full prompt sent to the Claude CLI on stdin."""
    return fill(
        template or DEFAULT_TEMPLATE,
        {
            "facts": _facts(plugin, folders or [], requirements),
            "requirements": _requirements(),
            "categories": ", ".join(schema.CATEGORIES),
            "existing": _existing(authored or {}),
            "response_shape": json.dumps(RESPONSE_SHAPE, indent=2),
        },
    )


def improve_prompt(instruction: str) -> str:
    """A follow-up turn in the same session.

    Sent to a resumed session, so the model still has the original prompt, its
    own draft and every earlier round of feedback. Only the new instruction and
    a reminder of the answer format need to travel.
    """
    return (
        f"{instruction.strip()}\n\n"
        "Reply with the same JSON object shape as before and nothing else - no "
        "preamble, no code fence, no commentary. Include every field, not only "
        "the ones you changed."
    )


def extract_json_block(text: str) -> dict | None:
    """The first balanced JSON object in a reply, or None.

    Models wrap JSON in prose and fences however they like, so brace-matching
    the first complete object is more reliable than trusting the whole reply to
    parse. Returning None lets the caller keep the raw text rather than lose it.
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : index + 1])
                    except ValueError:
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break
        start = text.find("{", start + 1)
    return None


def merge_draft(authored: dict, draft: dict, overwrite: bool = False) -> dict:
    """Fold a draft into the authored file without clobbering your own words.

    By default only keys you have not written are taken, so re-running the
    drafter is safe. `overwrite` is the explicit "replace what I wrote" path,
    and is what a follow-up round uses - you asked for the change.
    """
    merged = dict(authored)
    for key in DRAFTABLE_KEYS:
        if key not in draft:
            continue
        value = draft[key]
        if key == "description" and isinstance(value, dict):
            existing = dict(merged.get("description") or {})
            for block in schema.DESCRIPTION_BLOCKS:
                if block in value and (overwrite or not existing.get(block)):
                    existing[block] = value[block]
            merged["description"] = existing
        elif overwrite or not merged.get(key):
            merged[key] = value
    return merged
