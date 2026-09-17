@echo off
:: Change working directory to the script's location
cd /d "%~dp0"

set "NOPAUSE=0"
if /I "%~1"=="/nopause" set "NOPAUSE=1"
if /I "%~1"=="--nopause" set "NOPAUSE=1"

title Build Ignite Chat Desktop App
echo ===================================================
echo Building Ignite Chat Desktop Executable
echo ===================================================
echo.

:: Close any running instances of the app to avoid locked file errors (WinError 5)
echo Closing any running instances of Ignite Chat...
taskkill /F /IM "Ignite Chat.exe" >nul 2>&1
taskkill /F /IM "msedgewebview2.exe" >nul 2>&1
powershell -Command "Get-Process | Where-Object { $_.Path -like '*dist\Ignite Chat*' } | Stop-Process -Force" >nul 2>&1
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*IgniteChatWebView2*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
echo.

:: Select Python binary (prefer .venv_x64)
set "PY_CMD=python"
if exist "%~dp0..\.venv_x64\Scripts\python.exe" (
    set "PY_CMD=%~dp0..\.venv_x64\Scripts\python.exe"
) else if exist "%~dp0.venv_x64\Scripts\python.exe" (
    set "PY_CMD=%~dp0.venv_x64\Scripts\python.exe"
)

:: Ensure pyinstaller is installed in the active environment
echo [1/3] Checking dependencies...
"%PY_CMD%" -m pip install pyinstaller python-dotenv --quiet
if %ERRORLEVEL% neq 0 (
    echo Error: Failed to install dependencies. Make sure Python is in your PATH.
    if "%NOPAUSE%"=="0" pause
    exit /b %ERRORLEVEL%
)

:: Clean temp build directory to ensure a fresh compilation
if exist "%TEMP%\IgniteChatBuild" (
    rmdir /s /q "%TEMP%\IgniteChatBuild" >nul 2>&1
)

:: Run PyInstaller to build a standalone, windowless directory app outside OneDrive in %TEMP%
echo [2/3] Compiling launcher_webview.py with PyInstaller in Temp folder...
"%PY_CMD%" -m PyInstaller --onedir --noconsole --noconfirm --name="Ignite Chat" --icon="icon.ico" --add-data "frontend;frontend" --add-data "assets;assets" --add-data "icon.ico;." --add-data "pythonnet.runtimeconfig.json;." --distpath "%TEMP%\IgniteChatBuild\dist" --workpath "%TEMP%\IgniteChatBuild\build" --collect-all google --collect-all azure launcher_webview.py
if %ERRORLEVEL% neq 0 (
    echo Error: Compilation failed.
    if "%NOPAUSE%"=="0" pause
    exit /b %ERRORLEVEL%
)

:: Clean up build artifacts, leaving only the executable folder
echo [3/3] Deploying build files to project directory...

:: Move/rename existing distribution to avoid locks
if exist "dist\Ignite Chat" (
    rmdir /s /q "dist\Ignite Chat" >nul 2>&1
    if exist "dist\Ignite Chat" (
        rename "dist\Ignite Chat" "Ignite Chat_old_%RANDOM%" >nul 2>&1
    )
)

:: Copy from Temp build to local dist folder
if not exist dist mkdir dist
robocopy "%TEMP%\IgniteChatBuild\dist\Ignite Chat" "dist\Ignite Chat" /E /MT /R:5 /W:1 >nul

:: Copy .env configuration file and .env.example template to compiled folder so API keys are loaded
:: Never ship secrets from CI (GitHub Actions has no local .env and must not invent one).
if not defined GITHUB_ACTIONS if exist .env (
    copy .env "dist\Ignite Chat\" >nul 2>&1
)
if exist .env.example (
    copy .env.example "dist\Ignite Chat\" >nul 2>&1
)
if exist pythonnet.runtimeconfig.json (
    copy pythonnet.runtimeconfig.json "dist\Ignite Chat\" >nul 2>&1
    copy pythonnet.runtimeconfig.json "dist\Ignite Chat\Ignite Chat.runtimeconfig.json" >nul 2>&1
)
if exist assets (
    robocopy assets "dist\Ignite Chat\assets" /E /MT /R:3 /W:1 >nul
)
if exist frontend (
    robocopy frontend "dist\Ignite Chat\frontend" /E /MT /R:3 /W:1 >nul
)

:: Compile Inno Setup Installer into repo-root release\ (gitignored)
echo.
if exist "%~dp0..\packaging\build_installer.bat" (
    call "%~dp0..\packaging\build_installer.bat" /nopause
) else (
    echo [Inno Setup] packaging\build_installer.bat not found. Skip installer.
)

:: Try to clean old renamed folders if they exist
for /d %%i in (dist\Ignite Chat_old_*) do rmdir /s /q "%%i" >nul 2>&1

:: Clean PyInstaller spec file
del /q "Ignite Chat.spec" >nul 2>&1

echo.
echo ===================================================
echo Build Successful!
echo Executable folder location: app\dist\Ignite Chat
if exist "dist\IgniteChat_Setup.exe" (
    echo Single Installer location: app\dist\IgniteChat_Setup.exe
)
echo Run the app using: app\dist\Ignite Chat\Ignite Chat.exe
echo ===================================================
echo.
if "%NOPAUSE%"=="0" pause
