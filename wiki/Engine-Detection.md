# Engine Detection

## Nothing is searched for on disk

The app does **not** scan your drives looking for Unreal. It reads three specific locations
that Epic itself creates:

| Source | What it reads |
|---|---|
| `HKLM\SOFTWARE\EpicGames\Unreal Engine\<ver>` | the `InstalledDirectory` value |
| `%ProgramData%\Epic\UnrealEngineLauncher\LauncherInstalled.dat` | one known JSON manifest |
| `HKCU\Software\Epic Games\Unreal Engine\Builds` | registered source builds |

Then one existence check per candidate for `Engine\Build\BatchFiles\RunUAT.bat`. That's two
registry keys, one file, and a handful of stat calls — no directory traversal.

Because the registry stores **absolute paths**, it does not matter which drive anything is
on. An engine on `F:\` is found by an app running from `E:\`.

## When automatic detection misses

Detection genuinely fails in these cases:

- The Epic Launcher was never installed
- A portable / xcopy engine that was never registered
- A source build not registered under `HKCU\...\Builds`
- An install made under a **different Windows account** (`HKCU` is per-user)
- An engine that was moved after being registered

## Adding an engine by hand

**Settings › Engine installations › Add engine folder…**

Pick the engine **root** — the folder that contains `Engine\`:

```
F:\Epic Games\UE_5.6\        <-- this
└── Engine\
    └── Build\
        └── BatchFiles\
            └── RunUAT.bat
```

You can add as many as you like. The app validates the folder before accepting it and
refuses anything without a `RunUAT.bat`.

For each added root it works out:

- **Version** — from `Engine\Build\Build.version`, truncated to major.minor so a hand-added
  engine produces the same `UE_5.6` label (and therefore the same zip filename) as an
  auto-detected one. Falls back to the folder name.
- **Installed vs source** — an installed build ships `Engine\Build\InstalledBuild.txt`;
  a source build does not. Source builds label as `UE_5.7 (source)` and name their zips
  accordingly.

The Settings page lists what was found automatically alongside your manual entries. A root
that stops being valid (engine moved or deleted) shows in red rather than silently
disappearing.

If a manual root duplicates an auto-detected one, the detected entry wins, so a previously
saved engine selection keeps resolving.

## Two engines, same version

Perfectly fine. The Build page shows the selected engine's full path next to the dropdown,
and each dropdown entry has its path as a tooltip.
