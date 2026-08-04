# Troubleshooting

## "Set LINUX_MULTIARCH_ROOT…" but I already installed the toolchain

Almost always a **stale environment block**, not a broken install.

A Windows process receives a *copy* of the environment when it starts, and never sees later
changes. If `explorer.exe` has been running since before the install, every cmd window and
every app you launch from the Start menu inherits its outdated copy — so "just open a new
window" doesn't help.

Check what is actually committed:

```powershell
[System.Environment]::GetEnvironmentVariable('LINUX_MULTIARCH_ROOT','Machine')
```

If that prints the path but `echo %LINUX_MULTIARCH_ROOT%` is empty, it's purely propagation.
Fix it, cheapest first:

1. Open **System Properties › Environment Variables** and click **OK** (not Cancel) — that
   broadcasts `WM_SETTINGCHANGE` and refreshes Explorer. Installers often write the registry
   directly without broadcasting, which is how this happens.
2. Restart `explorer.exe` from Task Manager, then open a new terminal
3. Sign out and back in

A full reboot works but is overkill. Whichever you use, launch the app *afterwards* — and if
you start it from an IDE, restart the IDE too, since it passes down its own stale copy.

## Linux is disabled and mentions two version numbers

```
v26_clang-20.1.8-rockylinux8 installed, this engine needs v25_clang-18.1.0-rockylinux8
```

Working as intended. Engines pin one exact toolchain version with no tolerance, and yours
doesn't match the selected engine. Either install the required version alongside your current
one, or switch to an engine that accepts what you have. See
[Target Platforms](Target-Platforms).

## No engine detected

The Epic Launcher registers engines in the registry; anything installed another way is
invisible to it. Add the folder manually — **Settings › Engine installations** — and see
[Engine Detection](Engine-Detection) for which cases this covers.

## A plugin shows "missing dep"

It declares a dependency that is neither another plugin in your folder nor part of the
selected engine. The build will fail unless that plugin is installed.

Check the detail panel — dependencies are listed with their resolved kind. A dependency can
be *engine* on one version and *external* on another, so try selecting a different engine
before assuming it's missing.

## Everything says "changed" after I just built

Expected the first time: a plugin with no recorded hash counts as changed. Build once and it
settles.

If it persists, something is rewriting files inside the plugin outside the excluded folders.
The excluded set is `Binaries/ Intermediate/ Saved/ DerivedDataCache/ .git/`; generated files
anywhere else will register as source changes.

## My plugin selection resets

Selections persist to `config.json` on close and at the start of every build. If the app was
force-killed, the last selection may not have been written.

## Cancel doesn't seem to stop anything

It should stop within a couple of seconds and kill the whole compiler tree. If `cl.exe`
processes survive, that's a bug worth reporting — include a log export.

## Windows says the exe is unsafe

The release binary is unsigned. **More info › Run anyway**. Signing needs a code-signing
certificate this project doesn't have.

## Reporting a problem

**Logs › Save as…** and attach the file. Because the shipped exe is windowed with no console,
that export is the only diagnostic channel there is.

Useful to include: your engine version, the selected platforms, and whether a dry run behaves
the same way.
