# Packaging

## What gets run

For each plugin, in build order:

```
RunUAT.bat BuildPlugin
    -Plugin=<path>\<Name>.uplugin
    -Package=<temp>\CrimsonFabPublisher_Work\<Name>_Build
    -Rocket -StrictIncludes -NoHostPlatform -CreateSubFolder
    -TargetPlatforms=Win64+Linux
```

Those flags mirror the original `PackagePlugin.bat` exactly, so build behaviour is unchanged
from the script this tool replaces.

Output streams into the app's log line by line. Use **Dry run** to see the exact command
without executing it.

## The zip

On success the staged output is zipped to:

```
<Plugin>_UE_<version>_Submission.zip
```

with ` (source)` inserted for source-built engines, e.g.
`CrimsonCore_UE_5.6 (source)_Submission.zip`.

Zips land in the output folder (**Settings › Paths**), which defaults to your plugins folder.
The staging directory is always deleted afterwards, success or failure.

The exact filenames are previewed on the Build page before you run anything.

## Exclusions

These are **always** stripped, and cannot be turned off:

```
Binaries/  Intermediate/  Saved/  DerivedDataCache/  .git/
```

Add your own in **Settings › Packaging**, one pattern per line. Three forms are supported:

| Pattern | Matches |
|---|---|
| `Docs/` | a directory anywhere in the tree |
| `Source/Thirdparty/*.lib` | a path glob |
| `*.pdb` | a filename glob at any depth |

Blank lines and `#` comments are ignored. The always-excluded list is shown right below the
editor, so it's clear why `Binaries/` never appears in your zip.

## Size limit

Fab rejects submissions over **15 GB**. After each successful package the zip is measured and
a warning is logged if it exceeds that. Worth watching if a plugin carries heavy `Content/`.

## Cancelling

**Cancel** stops within a couple of seconds. It kills the entire `RunUAT` process tree —
`taskkill /T /F` — because killing only the launcher leaves UBT, MSBuild and every `cl.exe`
running with no window to close them from.

A cancelled plugin returns to `queued` rather than `failed`; it was never really attempted.
Partial staging output is cleaned up. Closing the window mid-build stops the build first
rather than terminating a running thread.

## Logs

Everything is captured with timestamps, severity and the plugin that produced it. The
**Logs** page filters by level and by plugin, and **Save as…** exports what you're currently
viewing.

The shipped exe is a windowed app with no console, so this export is the **only** way to hand
over a diagnostic. Reach for it before reporting a build problem.

Severity on RunUAT output is a display hint derived from the text, and never affects success
— that comes solely from the process exit code. The default filter shows everything, so a
misclassified line can be mis-coloured but never hidden.
