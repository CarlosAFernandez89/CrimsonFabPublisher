# Getting Started

## 1. Point it at your plugins

On first launch the **Plugins** page shows an empty state. Click **Choose folder…** and
select the folder that *contains* your plugin directories — not a plugin itself.

```
E:\Dev\Plugins\              <-- choose this
├── CrimsonCommon\
│   └── CrimsonCommon.uplugin
├── CrimsonInventory\
│   └── CrimsonInventory.uplugin
└── CrimsonCore\
    └── CrimsonCore.uplugin
```

The app looks exactly one level deep for `<Name>/<Name>.uplugin`. Malformed descriptors are
skipped rather than aborting the scan.

## 2. Read the table

| Column | Meaning |
|---|---|
| **#** | Build order. `00` builds first; dependencies always precede dependents |
| **☐** | Tick to include in the next build |
| **Plugin** | Folder/descriptor name |
| **Version** | `VersionName` from the `.uplugin` |
| **Engine** | `EngineVersion` from the `.uplugin`; amber if it differs from the selected engine |
| **Modules** | Module count — hover for names, types and loading phases |
| **Deps** | Suite dependency count, plus `· N!` in red for unresolvable external ones |
| **Status** | See below |

### Statuses

| Status | Meaning |
|---|---|
| `up-to-date` | Source is unchanged since the last successful build |
| `changed` | Source differs from the last build, or it was never built |
| `needs resubmit (dep)` | Unchanged itself, but something it depends on changed |
| `missing dep` | Declares a dependency that is neither in the suite nor in the engine |
| `queued` / `building` | During a run |
| `success` / `failed` | Result of the last run |

`missing dep` **outranks** `changed`, because an unresolvable dependency predicts a hard
build failure — that matters more than knowing the source moved. The change state is still
visible in the detail panel on the right.

## 3. Choose what to build

The selection chips act on whatever the filters currently show:

- **All** / **None** / **Invert**
- **Changed** — everything the scan says needs rebuilding, including dependency-impacted plugins
- Or tick rows manually. Select a range and press **Space** to toggle them all.

You never need to hand-pick dependencies. Ticking `CrimsonCore` automatically pulls in
`CrimsonInventory` and `CrimsonCommon` — the **Build** page shows exactly what will run.

## 4. Set up the run

On the **Build** page:

- **Engine** — which installed engine to build against
- **Target platforms** — Win64 works out of the box; the rest need toolchains,
  see [Target Platforms](Target-Platforms)
- **Build queue** — the ordered list of what will actually build, with auto-included
  dependencies badged
- **Output** — where zips land and their exact filenames
- **Preflight** — anything blocking the build, spelled out

The **Build selected** button stays disabled while preflight has blockers, and tells you why.

## 5. Build

**Dry run** logs the exact `RunUAT` command line for each plugin without executing anything.
Worth doing once.

**Build selected** runs for real. The status strip at the bottom stays visible from every
page, showing progress, the current plugin, the platforms and elapsed time.

**Cancel** stops within a couple of seconds — it kills the whole compiler process tree, not
just the launcher.

When it finishes, the output folder opens automatically (toggleable in
**Settings › Defaults**). Drag the zips into the Fab seller portal.
