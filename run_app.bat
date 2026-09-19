@echo off
setlocal EnableExtensions
title Ignite Agent-a-thon (Foundry snapshot)
echo ============================================================
echo  Agent-a-thon Foundry snapshot — NOT product IgniteChat
echo  Expect console lines: FOUNDRY BOOT / FOUNDRY create-if-missing
echo ============================================================
echo Starting Ignite Gemini Assistant via PyWebView...
echo Loading libraries, please wait...
cd /d "%~dp0app"

REM IMPORTANT: delete these vars (do not set them to empty strings).
REM An empty PYTHONNET_CORECLR_RUNTIME_CONFIG forces CoreCLR and breaks
REM x64 Python on Windows ARM (hostfxr error 0xc1).
set PYTHONNET_RUNTIME=
set PYTHONNET_CORECLR_RUNTIME_CONFIG=

REM Prefer x64 Python. Native ARM64 Python + pywebview/pythonnet crashes
REM with System.Windows.Forms / missing Forms assembly.
REM App supports Python 3.10+; architecture must be x64 (not ARM64).

set "PY_EXE="

if exist "%~dp0.venv_x64\Scripts\python.exe" (
  set "PY_EXE=%~dp0.venv_x64\Scripts\python.exe"
)

REM Store / py launcher installs (newest first)
for %%V in (3.14 3.13 3.12 3.11 3.10) do (
  if not defined PY_EXE if exist "%LocalAppData%\Python\pythoncore-%%V-64\python.exe" (
    set "PY_EXE=%LocalAppData%\Python\pythoncore-%%V-64\python.exe"
  )
)

REM Classic CPython installs under Local\Programs
for %%V in (Python314 Python313 Python312 Python311 Python310) do (
  if not defined PY_EXE if exist "%LocalAppData%\Programs\Python\%%V\python.exe" (
    set "PY_EXE=%LocalAppData%\Programs\Python\%%V\python.exe"
  )
)

if defined PY_EXE (
  echo Using Python x64: %PY_EXE%
  set "PYTHONNET_RUNTIME=netfx"
  "%PY_EXE%" -c "import struct,sys; assert struct.calcsize('P')*8==64, 'Need x64 Python, not ARM64'; print('Python', sys.version)" || goto :bad_arch
  "%PY_EXE%" launcher_webview.py
  goto :check_exit
)

where py >nul 2>nul
if errorlevel 1 goto :no_python

REM py launcher: force 64-bit tags when available
for %%V in (3.14-64 3.13-64 3.12-64 3.11-64 3.10-64 3.14 3.13 3.12) do (
  py -%%V -c "import webview, struct, sys; raise SystemExit(0 if struct.calcsize('P')*8==64 else 1)" 2>&1 | findstr /I "error trace" >nul
  if errorlevel 1 (
    echo Using py -%%V ...
    set "PYTHONNET_RUNTIME=netfx"
    py -%%V launcher_webview.py
    goto :check_exit
  )
)

goto :no_python

:bad_arch
echo.
echo ERROR: Found a Python that is not x64 ^(likely ARM64^).
echo Install Python 3.12+ Windows installer as 64-bit / x86-64 ^(NOT ARM64^).
echo.
pause
exit /b 1

:no_python
echo.
echo ERROR: No x64 Python 3.10+ found.
echo Install Python 3.12 ^(or 3.13/3.14^) Windows installer as 64-bit / x86-64, then retry.
echo Do NOT use Python ARM64 for this app ^(pywebview will crash^).
echo.
pause
exit /b 1

:check_exit
if errorlevel 1 (
  echo.
  echo App exited with an error.
  echo Check app\crash_log\crash_log.txt for details.
  echo.
  pause
  exit /b 1
)
exit /b 0
