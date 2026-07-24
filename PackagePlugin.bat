@echo off
setlocal

:: ==========================================
:: CONFIGURATION
:: ==========================================
:: Change this path to your Epic Games Engine installation folder
set "ENGINE_ROOT=F:\Epic Games\UE_5.6"
set "TARGET_PLATFORMS=Win64+Linux"
:: ==========================================

for %%i in ("%ENGINE_ROOT%") do set "UE_VER=%%~nxi"
set "UAT_PATH=%ENGINE_ROOT%\Engine\Build\BatchFiles\RunUAT.bat"

if "%~1" == "" (
    echo [ERROR] Drag and drop your plugin folder onto this file.
    pause
    exit /b
)

set "PLUGIN_DIR=%~1"
set "PLUGIN_NAME=%~n1"
for %%f in ("%PLUGIN_DIR%\*.uplugin") do set "PLUGIN_FILE=%%f"

if not defined PLUGIN_FILE (
    echo [ERROR] No .uplugin file found in: "%PLUGIN_DIR%"
    pause
    exit /b
)

:: Set Output Paths
set "OUTPUT_PATH=%~dp1%PLUGIN_NAME%_%UE_VER%_Build"
set "ZIP_FILE=%~dp1%PLUGIN_NAME%_%UE_VER%_Submission.zip"

echo ========================================================
echo STEP 1: COMPILING (Win64 Only)
echo ========================================================

call "%UAT_PATH%" BuildPlugin ^
 -Plugin="%PLUGIN_FILE%" ^
 -Package="%OUTPUT_PATH%" ^
 -Rocket ^
 -StrictIncludes ^
 -NoHostPlatform ^
 -TargetPlatforms=%TARGET_PLATFORMS% ^
 -CreateSubFolder

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FAILURE] Build failed with Exit Code %ERRORLEVEL%
    echo The Zip process will not start.
    pause
    exit /b
)

echo.
echo ========================================================
echo STEP 2: CLEANING & ZIPPING
echo ========================================================

if exist "%OUTPUT_PATH%" (
    :: Cleanup
    if exist "%OUTPUT_PATH%\Binaries" rd /s /q "%OUTPUT_PATH%\Binaries"
    if exist "%OUTPUT_PATH%\Intermediate" rd /s /q "%OUTPUT_PATH%\Intermediate"
    
    :: Zip using PowerShell with explicit paths to avoid the "Path:" prompt
    if exist "%ZIP_FILE%" del /f /q "%ZIP_FILE%"
    powershell -Command "Compress-Archive -Path '%OUTPUT_PATH%\*' -DestinationPath '%ZIP_FILE%' -Force"
    
    echo [SUCCESS] Zip Created: %ZIP_FILE%
    rd /s /q "%OUTPUT_PATH%"
    explorer /select,"%ZIP_FILE%"
) else (
    echo [ERROR] Output folder not found. Nothing to zip.
)

pause