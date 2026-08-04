# How Change Detection Works

The point of the app: after editing one plugin in a suite of twenty, know exactly which ones
need resubmitting — and no more than that.

## Source hashing

On every scan, each plugin gets a SHA-256 over its meaningful source tree. Both the relative
path and the file bytes feed the digest, so additions, deletions, renames and edits are all
detected.

These folders never contribute:

```
Binaries/  Intermediate/  Saved/  DerivedDataCache/  .git/  __pycache__/
```

That exclusion is what makes a **rebuild alone never register as a change**. Compiling
churns `Binaries/` and `Intermediate/` constantly; if those counted, everything would look
dirty forever.

The hash is compared against the one stored when that plugin last built successfully
(`state.json`). A plugin with no stored hash — never built — counts as changed.

## Dependency classification

Each `Plugins` entry in a `.uplugin` resolves to one of three kinds:

| Kind | Meaning |
|---|---|
| **suite** | Another plugin in your managed folder — drives build order |
| **engine** | Ships inside the selected engine's `Engine/Plugins` tree |
| **external** | Neither — must be installed separately, and the build will fail without it |

This is **engine-aware**: the same dependency can be *engine* against one version and
*external* against another, because Epic moves plugins in and out of the engine between
releases. Switching engines re-runs the classification.

## Build order

The suite dependency graph is topologically sorted, giving each plugin the order index shown
in the `#` column. Dependencies always build before dependents.

A dependency cycle doesn't crash anything — it's reported in the log and every plugin falls
back to order `0`.

## Resubmission impact

Change one plugin and every plugin **downstream** of it is flagged too:

```
CrimsonCommon  (edited)      -> changed
CrimsonInventory             -> needs resubmit (dep)      depends on Common
CrimsonCore                  -> needs resubmit (dep)      depends on Inventory
```

This is transitive. Fab requires you to resubmit a dependent plugin when the thing it links
against changes, and this is the part that's easy to get wrong by hand.

## Auto-included dependencies

Selecting a plugin to build automatically pulls in its transitive suite dependencies, so you
can't accidentally build `CrimsonCore` against a stale `CrimsonCommon`. The **Build queue**
badges anything added this way as `(auto — dependency)`.

## Committing the result

After a plugin builds **successfully**, its current hash is written to `state.json` and it
drops back to `up-to-date`. This happens per plugin, not at the end of the run, so a crash or
cancel halfway through doesn't lose the work already done.

A **dry run** never commits hashes — nothing was actually built.

If a build fails, its dependents are skipped rather than built against a broken artifact.

## Resetting

**Settings › Data › Reset build history** clears every stored hash. Everything then reads as
`changed` until built again. Nothing on disk is touched — this only forgets what was built.
