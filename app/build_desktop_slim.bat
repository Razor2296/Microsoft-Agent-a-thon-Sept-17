@echo off
REM Build a thin desktop package (UI + remote client). Requires PyInstaller.
setlocal
cd /d "%~dp0"

echo [IgniteChat] Installing slim desktop deps...
python -m pip install -r requirements-desktop.txt pyinstaller
if errorlevel 1 exit /b 1

echo [IgniteChat] Building launcher_webview slim binary...
python -m PyInstaller --noconfirm --clean ^
  --name IgniteChatSlim ^
  --windowed ^
  --add-data "frontend;frontend" ^
  --add-data "assets;assets" ^
  --add-data "pythonnet.runtimeconfig.json;." ^
  --hidden-import main.remote_api_proxy ^
  launcher_webview.py

echo.
echo Done. Set IGNITE_RUNTIME_MODE=remote and IGNITE_API_BASE_URL before running.
echo See docs\HYBRID_ACA.md for details.
endlocal
