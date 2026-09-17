@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Configure Ignite Gemini Assistant Startup Auto-Run
echo ===================================================
echo Configure Ignite Gemini Assistant Startup Auto-Run
echo ===================================================
echo.

set "SHORTCUT_PATH=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Ignite Chat.lnk"
set "ICON_PATH=%~dp0icon.ico"
set "EXE_PATH=%~dp0dist\Ignite Chat.exe"
set "LAUNCHER_SCRIPT=%~dp0launcher_webview.py"

choice /c YN /m "Do you want to enable Ignite Chat to run automatically on Windows startup?"
if %ERRORLEVEL% equ 2 goto disable_startup

:enable_startup
echo.
echo Creating startup shortcut...

if exist "%EXE_PATH%" (
    echo Found compiled executable: %EXE_PATH%
    powershell -NoProfile -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%SHORTCUT_PATH%'); $Shortcut.TargetPath = '%EXE_PATH%'; $Shortcut.WorkingDirectory = '%~dp0'; if (Test-Path '%ICON_PATH%') { $Shortcut.IconLocation = '%ICON_PATH%' }; $Shortcut.Save();"
    goto shortcut_done
)

echo Executable not found. Falling back to launcher_webview.py...
if not exist "%LAUNCHER_SCRIPT%" (
    echo Error: launcher_webview.py not found at %LAUNCHER_SCRIPT%
    echo Run this script from the app folder, or build first with build_desktop.bat.
    pause
    exit /b 1
)

set "PYTHONW_EXE="
if exist "%~dp0..\.venv_x64\Scripts\pythonw.exe" set "PYTHONW_EXE=%~dp0..\.venv_x64\Scripts\pythonw.exe"
if not defined PYTHONW_EXE if exist "%~dp0.venv_x64\Scripts\pythonw.exe" set "PYTHONW_EXE=%~dp0.venv_x64\Scripts\pythonw.exe"
if not defined PYTHONW_EXE (
    for /f "delims=" %%I in ('where pythonw.exe 2^>nul') do (
        if not defined PYTHONW_EXE set "PYTHONW_EXE=%%I"
    )
)
if not defined PYTHONW_EXE set "PYTHONW_EXE=pythonw.exe"

echo Using: !PYTHONW_EXE! "%LAUNCHER_SCRIPT%"
powershell -NoProfile -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%SHORTCUT_PATH%'); $Shortcut.TargetPath = '!PYTHONW_EXE!'; $Shortcut.Arguments = '\"%LAUNCHER_SCRIPT%\"'; $Shortcut.WorkingDirectory = '%~dp0'; if (Test-Path '%ICON_PATH%') { $Shortcut.IconLocation = '%ICON_PATH%' }; $Shortcut.Save();"

:shortcut_done
if %ERRORLEVEL% equ 0 (
    echo.
    echo ===================================================
    echo Startup auto-run enabled successfully!
    echo Shortcut created: %SHORTCUT_PATH%
    echo ===================================================
) else (
    echo.
    echo Error: Failed to create startup shortcut.
)
echo.
pause
exit /b 0

:disable_startup
if exist "%SHORTCUT_PATH%" (
    del /q "%SHORTCUT_PATH%"
    echo.
    echo ===================================================
    echo Startup auto-run disabled. Shortcut removed.
    echo ===================================================
) else (
    echo.
    echo Auto-run was not active (shortcut does not exist).
)
echo.
pause
exit /b 0
