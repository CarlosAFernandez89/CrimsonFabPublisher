# Listings

Building the zip is half a submission. The other half is the listing — title, description,
tags, category, prices, thumbnail, gallery, technical details, FAQ, changelog, declarations —
and Fab has no API for it, so it gets typed into the web form by hand.

The **Listings** page does not type it for you. It gives you the text to paste, checks it
against Fab's published requirements first, and remembers what you submitted so the next
update tells you exactly what moved.

## Why the memory matters

Fab splits edits into two classes, and it publishes which is which:

| Editing this | Costs you |
|---|---|
| Title, description, thumbnail, media, technical details, format files | **A new review** |
| Product type, category, license, prices, tags, forum link, AI declarations, platform support | Nothing — applies instantly |

Without a record of the last submission you cannot answer *"what do I actually have to touch,
and will it cost me a review cycle?"* — so every update means re-reading the whole form. That
record is what **Accept** writes.

## The workspace

Your listing copy lives in a folder you choose, set on the **Settings** page. It defaults to:

```
Documents\CrimsonFabPublisher\Listings\
```

```
<workspace>/
  _defaults.json          suite-wide defaults, written once for every plugin
  <PluginId>.json         one plugin's authored copy
  media/<PluginId>/       its thumbnail and gallery images
  _snapshots/<PluginId>.json   what was last submitted — the diff baseline
  STATUS.md               a table of every listing, regenerated on each Build
```

Point it at a repository you control if you want history. The snapshots are the only record
of what you actually submitted, and `STATUS.md` is deterministic — it only changes when
something really changed, so it reads as a submission log rather than noise.

Generated output goes somewhere else entirely, next to your zips, and is disposable:

```
<output folder>/_Listings/<PluginId>/
```

## The four things it does

**Check** — composes each listing, validates it, audits the package, and diffs it against the
last snapshot. Writes nothing. This is also what fills the Diff tab, which is why there is no
separate Diff button: it would hash the same zips for less output.

**Build bundles** — everything Check does, then writes the paste-ready files:

| File | What it is for |
|---|---|
| `listing.md` | The whole listing in Fab-form order. Keep it open beside the browser. |
| `description.html` | The description formatted. Open it in a browser, copy, and paste into Fab. |
| `description.txt` | The description with the markup stripped, for anywhere that takes plain text. |
| `tags.txt` | One tag per line, because Fab's picker takes them one at a time. |
| `technical.txt`, `faq.md`, `changelog.md` | Per-section paste sources. |
| `checklist.md` | A checkbox per field in form order, ending at *Submit for review*. |
| `media/01-thumbnail.png`, `02-…` | Numbered copies in upload order — drag the folder in. |
| `listing.json` | The machine form. This is what the diff compares. |
| `meta.json` | Run metadata. Never compared. |

**Accept** — records what you submitted, so the next Check has something to measure against.
It refuses while a listing still has errors: a snapshot of copy Fab would have rejected
becomes a baseline that makes every later diff misleading. You can force past it.

**Ask Claude** — drafts the description, title and tags from what the app already knows about
the plugin: its descriptor, modules, dependencies, Blueprint and C++ counts, and which folders
it ships. Output streams into the page and the Logs as it arrives, and Cancel stops it. If the
[Claude CLI](https://claude.com/claude-code) is not installed the button copies the prompt
instead, so the feature degrades rather than disappearing.

Drafts follow the *Crimson Template*: a bold hook, a link bar built only from
the `.uplugin`'s `DocsURL` and `SupportURL`, a short pitch, then **✨ Features**,
**🛠️ Getting Started**, **📋 Requirements** and **⚠️ Limitations**. They are
written in a small markup: `## ` headings, `- ` bullets, `**bold**` and
`[text](https://…)` links. Nothing else is allowed, and the validator names
anything outside that set.

**Copy description** — puts the built description on the clipboard as
formatted text, with a plain-text fallback, ready to paste into Fab's
description field. It copies what the last Check composed.

## The one rule

**Never edit copy in the Fab form.** Change the listing file and run Build again.

Anything typed straight into Fab is an edit the snapshot never sees, and from that point on
every diff is wrong — it will tell you a field is unchanged when Fab is showing something
else. This is repeated at the top of every generated checklist because it is the single
largest behavioural risk in the workflow.

## Where the values come from

Precedence runs **authored → derived from the plugin → suite default → empty**. A `null`,
`""` or `[]` in your file means *"I have not set this"*, not *"set it to nothing"* — so
deleting a value falls back rather than blanking the field.

Anything the app can work out, it works out: the title from the plugin id (splitting only on
lower-to-upper, so `MyPluginUI` becomes `My Plugin UI`, not `My Plugin U I`), engine versions
from the descriptor, target platforms from `SupportedTargetPlatforms`, and the technical
paragraph from the modules and dependency list — which is also how it satisfies Fab's
requirement that the technical text names your prerequisites.

The **Provenance** tab shows, per field, whether the value was authored, derived or defaulted,
and which source produced it.

## Editing

The **Fields** tab has widgets for the things that change often — title with a live character
count, subcategory, prices, tags, the three description areas, declarations. The **Raw JSON**
tab is the escape hatch for anything the form does not model; invalid JSON is reported and
refused rather than written.

The file, not the widget tree, is the source of truth. Both tabs write to
`<workspace>/<PluginId>.json` and re-read from disk when you switch, so there is nothing to
fall out of step.

## What gets checked

Two separate questions, on two tabs.

The **Diff** tab's issue list answers *is the listing copy complete* — title length, the three
content areas Fab wants a description to cover, tag counts, thumbnail dimensions and size,
gallery contents, engine versions, platform lists. Every message names the key that fixes it.

The **Audit** tab answers *would Fab reject the package itself* — the `.uplugin` requirements
(`EngineVersion`, a per-module `PlatformAllowList` or `PlatformDenyList`, `FabURL`), the
170-character path limit, English-alphanumeric file names, a copyright notice in every source
file, shipped executables, and folders that need a `FilterPlugin.ini`. Each row cites the
section of [Fab's technical requirements](https://www.fab.com/o/technical-requirements) it
comes from.

Every rule the app knows lives in one table, `fabpublisher/listing/fabrules.py`, each with its
section number and whether it is **documented** by Fab or merely **observed** in the publisher
portal. The validator checks against that table and the Ask Claude prompt is generated from
it, so the two cannot drift into disagreeing about what a passing listing looks like.

## Statuses

| | |
|---|---|
| `NEW` | Never submitted. |
| `PENDING` | A snapshot exists but the listing is not live on Fab yet. |
| `changed` | Something moved since the last Accept. |
| `clean` | Nothing has moved. |
| `blocked` | Errors to fix before it can be accepted. |
| `excluded` | `"publish": false` in that plugin's file. |

A dot in the **Live** column means the descriptor carries a Fab product URL, so the checklist
says *update it, do not create a new one*.

## Excluding a plugin

Not everything you build is for sale. Create `<PluginId>.json` containing:

```json
{ "publish": false }
```

It stays visible in the table as `excluded` but is left out of Check, Build and the status
table — better than nine permanent errors training you to ignore the error column.
