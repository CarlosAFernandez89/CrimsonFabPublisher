# CrimsonFabPublisher

A Windows desktop tool for building a suite of interdependent Unreal Engine plugins into
FAB-ready submission zips.

It replaces the drag-and-drop `PackagePlugin.bat` workflow with something that understands
your whole plugin suite: it knows which plugins depend on which, what order they must build
in, and — crucially — **which ones actually changed since you last shipped them**.

## What it does

| | |
|---|---|
| **Scans** | Finds every `<Name>/<Name>.uplugin` under a folder you choose |
| **Classifies dependencies** | Each `.uplugin` dependency resolves as *suite*, *engine*, or *external* |
| **Orders builds** | Topological sort, so dependencies compile before dependents |
| **Detects change** | SHA-256 over each plugin's source; a rebuild alone never counts as a change |
| **Tracks impact** | Change one plugin and everything downstream is flagged for resubmission |
| **Builds** | Drives `RunUAT BuildPlugin` with the same flags as the original batch script |
| **Packages** | Produces `<Plugin>_UE_<version>_Submission.zip`, stripped of build artifacts |

## What it does *not* do

It does not upload anything. Despite the name, there is no Fab API integration, no
authentication, and no network access at all — `QtNetwork` is excluded from the build. The
final step is manual: the app opens the output folder and you drag the zips into the Fab
seller portal.

## Getting started

1. **[Installation](Installation)** — grab the exe or run from source
2. **[Getting Started](Getting-Started)** — your first scan and build
3. **[Target Platforms](Target-Platforms)** — enabling Linux, Android, Mac and iOS
4. **[Troubleshooting](Troubleshooting)** — when something says "not detected"

## Where your data lives

Nothing is written to the registry. Two files under `%APPDATA%\CrimsonFabPublisher\`:

- `config.json` — your settings (paths, engine, platforms, selection, exclude patterns)
- `state.json` — the build-history hashes that power change detection

Both are reachable from **Settings › Data**, along with a *Reset build history* action.
