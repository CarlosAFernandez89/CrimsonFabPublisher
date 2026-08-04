# Installation

## Option 1 — download the release (recommended)

1. Go to [Releases](../../releases/latest)
2. Download `CrimsonFabPublisher.exe`
3. Run it

That's the whole install. It is a single self-contained executable (~45 MB) with Python and
Qt bundled — nothing to install, nothing added to `PATH`, no registry keys written.

> **SmartScreen:** the exe is unsigned, so Windows may show *"Windows protected your PC"*.
> Click **More info › Run anyway**. Signing requires a code-signing certificate, which this
> project does not have.

### Requirements

- Windows 10 or 11
- Unreal Engine installed (any version with `RunUAT.bat`) — see [Engine Detection](Engine-Detection)

## Option 2 — run from source

Useful if you want to modify it or run the test suite.

```bash
git clone https://github.com/CarlosAFernandez89/CrimsonFabPublisher.git
cd CrimsonFabPublisher
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Python 3.11 or newer. Development happens on 3.14.

## Option 3 — build the exe yourself

```powershell
.\build_exe.ps1
```

Output lands in `dist\CrimsonFabPublisher.exe`. See [Development](Development) for what the
build actually does and how CI verifies it.

## Uninstalling

Delete the exe. To also remove your settings and build history, delete
`%APPDATA%\CrimsonFabPublisher\`.
