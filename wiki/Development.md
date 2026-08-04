# Development

## Layout

```
fabpublisher/            domain layer — no Qt imports at all
  models.py              dataclasses and enums
  uplugin.py             .uplugin parser (utf-8-sig; UE writes BOMs)
  discovery.py           find plugins / engine built-ins
  engines.py             engine detection + manual roots
  platforms.py           toolchain availability, pinned SDK versions, setup guides
  dependencies.py        classify, topological order, transitive closure both ways
  state.py               content hashing, StateStore
  shipfilter.py          gitignore-ish exclusion
  validation.py          FAB pre-flight checks
  builder.py             RunUAT invocation, zip packaging, process-tree kill
  scan_service.py        the whole scan pipeline, returns data
  config.py              JSON persistence

fabpublisher/ui/
  main_window.py         shell — wiring only, computes nothing
  app_settings.py        observable settings; widgets bind to it, never the reverse
  build_controller.py    owns a run; pure preflight()
  log_model.py           records with level/timestamp/source
  nav_sidebar.py         status_strip.py  plugin_table_model.py  status_delegate.py
  theme/                 tokens.py, crimson.qss, icons.py (QPainter-drawn)
  pages/                 plugins, build, logs, settings
```

The rule that keeps this maintainable: **the domain layer imports no Qt**, so every algorithm
is testable without a `QApplication`. Anything that needs a widget lives under `ui/`.

Colours exist only in `theme/tokens.py`. Models expose state through custom roles; views
decide what colour that state is.

## Tests

```bash
set QT_QPA_PLATFORM=offscreen
python -m pytest -q
```

145 tests, about 1.5 seconds. The offscreen platform lets the UI smoke tests build real
widgets with no display.

Coverage worth knowing about:

- `test_scan_service.py` — statuses, change impact, cycle handling, builtin caching
- `test_platform_setup.py` — toolchain version windows, setup guidance for every platform
- `test_engines.py` — registry sources, manual roots, source-vs-installed detection
- `test_ui_smoke.py` — constructs the real window, visits every page, paints every status

Two guard tests fail deliberately if you extend an enum without updating its presentation:
every `PluginStatus` and `LogLevel` must have a colour, and every `Platform` must have a
setup guide.

The UI fixture stubs engine detection, so the suite doesn't depend on what's installed on the
machine running it.

## Building the exe

```powershell
.\build_exe.ps1
```

or directly:

```bash
python -m PyInstaller --noconfirm --clean CrimsonFabPublisher.spec
```

The spec bundles `app.ico` and `theme/crimson.qss`, and excludes Qt modules the app never
touches (QML, Quick, WebEngine, Charts, **QtNetwork**, tkinter).

> **Watch this one.** If `crimson.qss` is missing from the bundle, `apply_theme` degrades to
> palette-only instead of raising — the app starts and looks *nearly* right. That failure is
> invisible when running from source, so CI greps the built exe for the string.

## CI

`.github/workflows/build.yml` runs on Windows for every push and PR: tests → build →
verify the bundle → upload the exe as an artifact.

Pushing a `v*` tag additionally publishes a GitHub Release with the exe attached.

```bash
git tag -a v0.1.0 -m "CrimsonFabPublisher v0.1.0"
git push origin v0.1.0
```

Keep `__version__` in `fabpublisher/__init__.py` aligned with the tag.

CI has no Unreal Engine, so it verifies the app **builds and starts** — not that it packages
a plugin. That still needs a real machine.

## Conventions

`CLAUDE.md` in the repo root captures the working style: smallest change that solves the
problem, no speculative abstraction, no unrequested configurability, and match the
surrounding code rather than improving adjacent things while passing through.
