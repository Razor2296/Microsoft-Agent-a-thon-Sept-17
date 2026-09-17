@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "NOPAUSE=0"
if /I "%~1"=="/nopause" set "NOPAUSE=1"
if /I "%~1"=="--nopause" set "NOPAUSE=1"

title Build Ignite Chat Windows Installer
echo ===================================================
echo Ignite Chat — packaging installer ^(outside app/^)
echo ===================================================
echo.
echo Output folder:  ..\release\IgniteChat_Setup.exe
echo Source folder:  ..\app\dist\Ignite Chat\
echo.

if not exist "..\app\dist\Ignite Chat\Ignite Chat.exe" (
    echo ERROR: PyInstaller build missing.
    echo Run app\build_desktop.bat first, then this script.
    if "%NOPAUSE%"=="0" pause
    exit /b 1
)

set "ISCC="
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not defined ISCC (
    echo ERROR: Inno Setup 6 not found ^(ISCC.exe^).
    echo Install with: winget install --id JRSoftware.InnoSetup -e
    if "%NOPAUSE%"=="0" pause
    exit /b 1
)

if not exist "..\release" mkdir "..\release"

echo Using: %ISCC%
echo Compiling setup_installer.iss ...
"%ISCC%" "%~dp0setup_installer.iss"
if errorlevel 1 (
    echo ERROR: Installer compilation failed.
    if "%NOPAUSE%"=="0" pause
    exit /b 1
)

echo.
echo ===================================================
echo OK — installer ready ^(gitignored^):
echo   %~dp0..\release\IgniteChat_Setup.exe
echo ===================================================
echo.
dir /b "..\release\IgniteChat_Setup.exe"
echo.
if "%NOPAUSE%"=="0" pause
endlocal
