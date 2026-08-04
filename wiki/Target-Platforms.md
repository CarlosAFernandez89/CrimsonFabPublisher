# Target Platforms

Win64 works out of the box on a Windows host. Everything else needs a toolchain.

On the **Build** page, any platform you can't currently build shows an amber **⚠**. Hover it
for a one-line summary; click it for step-by-step instructions specific to your selected
engine.

## Linux

Unreal cross-compiles Linux binaries on Windows using a clang toolchain that Epic
distributes **separately from the engine**.

### The version has to match exactly

This is the part that catches people. Every engine release pins one toolchain version in:

```
<engine>\Engine\Config\Linux\Linux_SDK.json
```

```json
{
    "MainVersion" : "v25_clang-18.1.0-rockylinux8",
    "MinVersion"  : "v25_clang-18.1.0-rockylinux8",
    "MaxVersion"  : "v25_clang-18.1.0-rockylinux8"
}
```

`MinVersion` and `MaxVersion` are usually the *same value* — there is no tolerance window. A
newer toolchain is not "good enough"; the engine rejects it.

Worked example from one machine with three engines installed:

| Engine | Requires |
|---|---|
| UE 5.6 | `v25_clang-18.1.0-rockylinux8` |
| UE 5.7 | `v26_clang-20.1.8-rockylinux8` |
| UE 5.8 | `v26_clang-20.1.8-rockylinux8` |

So a single v26 install covers 5.7 and 5.8 but **not** 5.6. Check your own engines by opening
that JSON file — don't assume.

> Older sources are misleading here. The version constants are no longer in
> `LinuxPlatformSDK.Versions.cs` (it just points at the JSON), and the
> `v11_clang-5.0.0-centos7` string in `LinuxPlatformSDK.cs` is only an example in a comment.

### Setup

1. Find the toolchain version your engine pins (the JSON above)
2. Download that exact version's installer from Epic's
   [Linux development requirements](https://dev.epicgames.com/documentation/en-us/unreal-engine/linux-development-requirements-for-unreal-engine)
3. Run it — it sets `LINUX_MULTIARCH_ROOT` for you, usually under `C:\UnrealToolchains\`
4. **Restart the app** — see [Troubleshooting](Troubleshooting) if the variable doesn't appear

Multiple toolchains coexist happily under `C:\UnrealToolchains\`. `LINUX_MULTIARCH_ROOT`
points at one at a time, so repoint it when switching engines.

### The app checks this for you

Selecting an engine re-evaluates every target. If your toolchain doesn't match, the Linux
checkbox is disabled and the reason names both versions:

```
v26_clang-20.1.8-rockylinux8 installed, this engine needs v25_clang-18.1.0-rockylinux8
```

If a platform was ticked and becomes invalid after an engine switch, it is unticked and noted
in the log — better than failing twenty minutes into a build.

The check is deliberately **permissive**: a target is only disabled when a mismatch is
positively established. An engine layout the app can't read never blocks a build you could
otherwise do.

## Android

1. Install **Android Studio** — the engine's setup script drives its SDK manager
2. Run `<engine>\Engine\Extras\Android\SetupAndroid.bat`
3. Restart the app

Let that script choose versions. It installs the exact SDK, NDK and JDK your engine expects
and sets the environment variables; Unreal is strict about them.

Android declares a *range* of acceptable NDK revisions rather than a single pin, so a
mismatch here is shown as a note and does **not** disable the target.

## Mac and iOS

Apple's toolchain is macOS-only. These cannot be cross-compiled from Windows, so the app
marks them permanently unavailable on a Windows host.

Unreal can drive a networked Mac for iOS through its Remote Build options, but that is
configured per project in the editor — this app builds on the local host only.

To ship Mac or iOS, run the packaging step on a Mac with Xcode and the same engine version.
