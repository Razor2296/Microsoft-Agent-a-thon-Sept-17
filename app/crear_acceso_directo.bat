@echo off
title Crear Acceso Directo - Ignite Chat
echo ===================================================
echo Creando acceso directo en el Escritorio...
echo ===================================================
echo.

:: Path settings
set "ICON_PATH=%~dp0icon.ico"
set "EXE_PATH=%~dp0dist\Ignite Chat.exe"
set "LAUNCHER_SCRIPT=%~dp0launcher_webview.py"

:: Check if the compiled executable exists
if exist "%EXE_PATH%" (
    echo Se encontro el ejecutable compilado: %EXE_PATH%
    powershell -Command "$DesktopPath = [Environment]::GetFolderPath('Desktop'); $ShortcutPath = Join-Path $DesktopPath 'Ignite Chat.lnk'; $WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut($ShortcutPath); $Shortcut.TargetPath = '%EXE_PATH%'; $Shortcut.WorkingDirectory = '%~dp0'; $Shortcut.IconLocation = '%ICON_PATH%'; $Shortcut.Save();"
) else (
    echo Executable no compilado. Usando launcher_webview.py con pythonw.exe...
    
    :: Search for pythonw.exe
    for /f "delims=" %%I in ('where pythonw.exe 2^>nul') do set "PYTHONW_EXE=%%I"
    if "%PYTHONW_EXE%"=="" set "PYTHONW_EXE=pythonw.exe"
    
    powershell -Command "$DesktopPath = [Environment]::GetFolderPath('Desktop'); $ShortcutPath = Join-Path $DesktopPath 'Ignite Chat.lnk'; $WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut($ShortcutPath); $Shortcut.TargetPath = '%PYTHONW_EXE%'; $Shortcut.Arguments = '\"%LAUNCHER_SCRIPT%\"'; $Shortcut.WorkingDirectory = '%~dp0'; $Shortcut.IconLocation = '%ICON_PATH%'; $Shortcut.Save();"
)

if %ERRORLEVEL% equ 0 (
    echo.
    echo ===================================================
    echo !Acceso directo creado con exito en el Escritorio!
    echo Ubicacion: %SHORTCUT_PATH%
    echo ===================================================
) else (
    echo.
    echo Error: No se pudo crear el acceso directo.
)
echo.
pause
exit /b 0
