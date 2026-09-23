# Changelog

Release pages on GitHub are built from the matching section of this file.
Earlier releases are described on their
[release pages](https://github.com/CarlosAFernandez89/CrimsonFabPublisher/releases).

## 1.2 — 2026-09-23

Building the zip was only half of a Fab submission. The other half — the listing
page itself — was still typed into the web form by hand, every time, with no
record of what you had submitted. 1.2 adds a **Listings** page that stages that
half too.

### New: the Listings page

A fifth page, between **Build** and **Logs**, with one row per plugin and a
detail panel beside it.

**Check** composes every listing, validates it against Fab's requirements,
audits the plugin package, and compares it with what you last submitted. It
writes nothing.

**Build bundles** writes paste-ready files for each listing into
`<output folder>/_Listings/<Plugin>/`:

- `listing.md` — the whole listing in the order Fab's form asks for it
- `description.txt` — the description, ready to paste
- `tags.txt` — one suggested tag per line, since Fab's picker takes them one
  at a time
- `technical.txt`, `faq.md`, `changelog.md` — per-section paste sources
- `checklist.md` — a checkbox for every form field, ending at *Submit for review*
- `media/` — the thumbnail and gallery, numbered in upload order
- `listing.json` — the machine-readable listing that change tracking compares

It also regenerates `STATUS.md`, a table of every listing: tier, prices,
whether it is live, what is blocking it and what has changed.

**Accept** records what you just submitted, so the next Check can tell you
what moved. It refuses while a listing still has errors — a snapshot of copy
Fab would reject makes every later comparison misleading — and can be forced.

### Know which edits cost you a review

Fab publishes which listing edits send a product back through review (title,
description, thumbnail, media, technical details, files) and which apply
instantly (category, license, prices, tags, declarations, platforms). After an
Accept, every change is sorted into those two groups, so an update tells you
exactly what to touch and whether it will cost a review cycle. Anything Fab's
documentation does not classify is treated as review-triggering and flagged,
rather than guessed.

On an update, the checklist opens with a *Changed since last submission*
section split the same way, and says *update it, do not create a new one*
whenever the plugin's descriptor already carries a Fab listing URL.

### Checked against Fab's published requirements

Every rule the app enforces comes from one table, citing the section of
[Fab's technical requirements](https://www.fab.com/o/technical-requirements) it
comes from — or marked as observed from the publisher portal where the
document says nothing. Every problem names the field that fixes it.

The **Audit** tab asks a separate question — *would Fab reject the package
itself?* — and checks the plugin folder for:

- `EngineVersion`, a per-module `PlatformAllowList` or `PlatformDenyList`, and
  `FabURL` in the `.uplugin`
- dependencies on other user-made plugins
- a publisher copyright notice in every source and header file
- file paths over 170 characters, and names outside English letters, digits
  and underscores
- shipped `.exe` / `.msi` files, and extra folders without a
  `Config/FilterPlugin.ini`

Findings are copyable — select rows and press Ctrl+C, right-click, or use
*Copy all* — so they can be taken wherever the fix happens.

### Required plugins, worked out for you

Reviewers expect a listing to name everything a buyer must install. The app now
reads each module's `.Build.cs` as well as the `.uplugin`, traces every module
back to the plugin that ships it, and writes a *Required plugins* line (plus
*Engine plugins used*, which some reviewers ask for) into the technical
section. Core engine modules such as `Core` or `UMG` are recognised and left
out. Set `technical.include_engine_plugins` to `false` in a listing to omit the
engine list.

### Ask Claude

With the [Claude CLI](https://claude.com/claude-code) installed, **Ask Claude**
drafts the title, tags and description from what the app already knows about
the plugin — its modules, dependencies, Blueprint and C++ counts. The request
includes Fab's copy rules straight from the requirements table, so the draft
aims at what the validator checks. Drafts are structured into short headed
sections rather than one wall of text, and never overwrite copy you have
already written.

**Ask for improvements…** takes an instruction in plain words — *"make the
technical section shorter"* — and continues the same conversation, so Claude
still has its own draft in context. Output streams into the page and the Logs
while it runs, and Cancel stops it.

The drafting prompt is editable under **Settings › Fab listings › Drafting
prompt**. Without the CLI, the button copies the prompt to the clipboard
instead.

### Editing

- **Fields** — title with a live character count, product type, category,
  tier, license, both prices, the three description areas, tags and
  declarations
- **Media** — thumbnail and gallery with their measured size and dimensions
- **Diff** — the review/instant breakdown against your last Accept
- **Provenance** — for every field, whether it was written by you, derived
  from the plugin, or filled from your suite-wide defaults
- **Raw JSON** — the listing file itself, for anything the form does not
  cover; invalid JSON is refused rather than saved

Tags are treated as suggestions. Fab only accepts tags its picker already
offers and does not publish that list, so the app suggests conventional terms
and the checklist tells you to drop any the picker does not have.

### Your listing files

Listing copy, media and submission snapshots live in a folder you choose under
**Settings › Fab listings**, defaulting to
`Documents\CrimsonFabPublisher\Listings` (redirected Documents folders, such as
OneDrive's, are followed). None of it is written into the app's own folder.
Keep it in a repository of your own if you want the submission history
versioned.

Put suite-wide values — category, tags, media paths, platforms — in
`_defaults.json` once. A plugin you do not sell can be excluded with
`{ "publish": false }` in its own listing file.

### Other changes

- The `.uplugin` reader now picks up `Description`, `Category`, `CreatedBy`,
  `CreatedByURL`, `DocsURL`, `SupportURL`, `FabURL`, `MarketplaceURL`,
  `SupportedTargetPlatforms` and each module's platform lists. A plugin counts
  as already listed when either URL is set.
- Settings gains a **Fab listings** card: listings folder, Claude CLI location,
  the drafting prompt, and whether FAQ and changelog edits should count as
  review-triggering.

### Upgrading

Nothing to migrate. New settings take their defaults, and the listings folder
is created the first time the page opens.

### Worth knowing

- Fab does not publish its tag list or confirm which picker values exist, so
  the category list and tag suggestions are best effort. A category the app
  does not recognise is a warning, not an error.
- Fab's documentation is silent on whether FAQ and changelog edits trigger a
  review. Both are assumed to, and each can be switched off in Settings once
  you have seen what Fab does.
