# Builds CrimsonFabPublisher into a single distributable .exe using PyInstaller.
# Usage:  right-click > Run with PowerShell, or:  .\build_exe.ps1
#
# Output:  dist\CrimsonFabPublisher.exe

# NOTE: pip and PyInstaller both write normal progress to stderr. We deliberately
# do NOT use "$ErrorActionPreference = 'Stop'" here, because that would make those
# harmless stderr lines abort the build. Instead we check $LASTEXITCODE ourselves.

$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "[ERROR] .venv not found. Create it and run: pip install -r requirements.txt" -ForegroundColor Red
    exit 1
}

Write-Host "==> Ensuring PyInstaller is installed..." -ForegroundColor Cyan
& $python -m pip install --quiet --disable-pip-version-check pyinstaller 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to install PyInstaller." -ForegroundColor Red
    exit 1
}

Write-Host "==> Cleaning previous build..." -ForegroundColor Cyan
if (Test-Path (Join-Path $root "build")) { Remove-Item -Recurse -Force (Join-Path $root "build") }
if (Test-Path (Join-Path $root "dist"))  { Remove-Item -Recurse -Force (Join-Path $root "dist") }

Write-Host "==> Building CrimsonFabPublisher.exe (this takes ~1 minute)..." -ForegroundColor Cyan
# Merge stderr into stdout so PyInstaller's progress logs don't raise NativeCommandError.
& $python -m PyInstaller --noconfirm --clean "CrimsonFabPublisher.spec" 2>&1 | ForEach-Object { "$_" } | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] PyInstaller build failed (exit $LASTEXITCODE)." -ForegroundColor Red
    exit 1
}

$exe = Join-Path $root "dist\CrimsonFabPublisher.exe"
if (Test-Path $exe) {
    $sizeMB = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host ""
    Write-Host "[SUCCESS] Built: $exe  ($sizeMB MB)" -ForegroundColor Green
    Write-Host "Distribute that single .exe. Config/state are written to %APPDATA%\CrimsonFabPublisher." -ForegroundColor Green
} else {
    Write-Host "[FAILURE] Build did not produce dist\CrimsonFabPublisher.exe" -ForegroundColor Red
    exit 1
}
