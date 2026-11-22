@echo off
rem Google AI Pro 5TB & AI Ultra One-Click Wizard — Double-click to run on Windows
rem Changes to the script directory and launches wizard.py.

chcp 65001 >nul
cd /d "%~dp0"

py -3 --version >nul 2>nul
if %errorlevel%==0 (
  py -3 wizard.py
) else (
  python --version >nul 2>nul
  if %errorlevel%==0 (
    python wizard.py
  ) else (
    echo [X] Python not found. Please install Python 3.9+: https://www.python.org/downloads/
    echo     Make sure to check "Add python.exe to PATH" during installation.
  )
)

echo.
echo (Wizard finished. Press any key to close this window)
pause >nul
