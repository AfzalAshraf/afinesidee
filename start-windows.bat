@echo off
setlocal
cd /d "%~dp0"
title Sidee Enhanced

REM Sidee Enhanced launcher.
REM start-windows.ps1 is an unsigned local setup script, so it MUST be started
REM with a per-process execution-policy bypass (below). Do NOT run the .ps1
REM directly: Windows then reports "is not digitally signed" on machines whose
REM policy is AllSigned / RemoteSigned. This .bat already supplies the bypass.
if not exist "%~dp0start-windows.ps1" (
    echo.
    echo Sidee could not start: start-windows.ps1 is missing from this folder.
    echo Extract the ENTIRE downloaded ZIP here, keeping both launcher files.
    echo.
    pause
    exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-windows.ps1" %*
if errorlevel 1 (
    echo.
    echo Sidee could not start. Read the message above, then try again.
    echo.
    echo If it says "not digitally signed" or mentions execution policy, make
    echo sure you opened START-WINDOWS.BAT and not start-windows.ps1 directly.
    echo From a PowerShell prompt you can also run:
    echo   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-windows.ps1"
    echo.
    echo If your organisation enforces a script policy, ask your administrator,
    echo or install Python 3.9+ and run: python sidee.py
    echo.
    pause
    exit /b 1
)
exit /b 0
