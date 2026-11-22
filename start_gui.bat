@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Google AI Pro / Ultra — 1-Click Desktop GUI

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw app.py
    exit /b 0
)

where python >nul 2>&1
if %errorlevel%==0 (
    python app.py
    exit /b 0
)

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 app.py
    exit /b 0
)

echo [ERROR] Python 3.10+ not found on this computer.
echo Please download and install Python from https://www.python.org/downloads/ (check "Add Python to PATH").
pause
